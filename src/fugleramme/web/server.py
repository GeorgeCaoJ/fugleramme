"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color page of what the frame is
showing, full-screen. It never reloads; instead it polls `/state` and swaps the
image only when the page actually changed, so a new bird appears within one poll
interval with no flash. Presentation settings live at `/admin` and are read per
request from the shared SettingsStore, so a change takes effect without a
restart. No auth: both views are open on the LAN.

Routing and transport only - the admin page itself is built in admin.py, and the
files under static/ are served as they are.

Stdlib http.server only, but threaded with a socket timeout: a serial server is
one silent client away from a dead kiosk, since a connection that never sends a
request blocks the accept loop forever. It shares the render loop's detector
source, so the two halves of a page cost one round trip between them.

A request that cannot reach the detector answers 503 rather than an empty page,
and the kiosk keeps the picture it is holding.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from .. import __version__, analyze, modes, updates
from ..languages import namer
from ..names import drawable_keys, normalize as name_key, resolve
from ..overlay import UploadOverlay
from ..panel import Panel, resolution_of
from ..picks import Picks
from ..settings import Settings, SettingsStore, merged
from ..source import Source, Unavailable
from ..status import Status
from . import STATIC_DIR, admin, i18n
from .i18n import UI
from .multipart import parse as parse_multipart

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

HTML = "text/html; charset=utf-8"
JSON = "application/json"

# Served verbatim. The admin's link carries ?v=<version>, so an update busts the cache.
FILES = {
    "/": ("kiosk.html", HTML),
    "/index.html": ("kiosk.html", HTML),
    "/admin.css": ("admin.css", "text/css; charset=utf-8"),
    "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
}


def make_handler(
    source: Source,
    images_dir: Path,
    store: SettingsStore,
    picks: Picks,
    panel: Panel | None,
    status: Status,
):
    # Held across requests: an outage must not blank every viewer at once. Tied
    # to the detector that drew it, since another station's birds are not ours.
    last_page: bytes | None = None
    last_from = ""
    # The kiosk polls every few seconds, so one warning per failed request would
    # never stop. Say it once, and again on recovery.
    unreachable = False
    # One BirdNET-Go `file` run at a time: the model is heavy and not reentrant.
    analyze_lock = threading.Lock()

    def note(message: str, gone: bool) -> None:
        nonlocal unreachable
        if gone and not unreachable:
            log.warning("%s", message)
        elif not gone and unreachable:
            log.info("Detector reachable again")
        else:
            log.debug("%s", message)
        unreachable = gone

    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT
        head = False
        # Set when a route answered from a held copy rather than the detector, so
        # a served page is not mistaken for the detector having come back.
        degraded = False

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def log_error(self, fmt, *args):
            log.warning("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._body(body)

        def _send_cached(self, body: bytes, content_type: str):
            # no-cache + ETag lets an unchanged refresh return a bodyless 304.
            etag = f'"{hashlib.md5(body).hexdigest()}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.end_headers()
            self._body(body)

        def _body(self, body: bytes):
            if not self.head:
                self.wfile.write(body)

        def _query(self) -> dict[str, list[str]]:
            return parse_qs(urlparse(self.path).query, keep_blank_values=True)

        def _context(self, settings: Settings) -> modes.Context:
            return modes.context(
                source,
                images_dir,
                picks,
                settings,
                namer(settings.primary_language, settings.secondary_language, store.path.parent),
                settings.web_size(resolution_of(panel)),
            )

        def _edited(self) -> Settings:
            """Saved settings under the admin's unsaved form state, so the
            preview and its listing show a change before Save."""
            return merged(store.get(), **admin.form_changes(self._query()))

        def _page_png(self):
            nonlocal last_page, last_from
            if source.base_url != last_from:
                last_page, last_from = None, source.base_url
            try:
                last_page = modes.png_bytes(self._context(store.get()))
            except Unavailable as exc:
                if last_page is None:
                    raise
                self.degraded = True
                note(f"Detector unavailable, serving the last kiosk page ({exc})", True)
            self._send_cached(last_page, "image/png")

        def _preview_png(self):
            self._send_cached(modes.png_bytes(self._context(self._edited())), "image/png")

        def _state(self):
            # Cheap enough to poll: one grouped query, no render.
            token = modes.token(modes.state_key(self._context(store.get())))
            self._send(200, json.dumps({"token": token}).encode(), JSON)

        def _species(self):
            ctx = self._context(self._edited())
            rows = admin.subjects(ctx)
            self._send(
                200,
                json.dumps(
                    {"count": len(rows), "html": admin.species_html(rows, ctx.namer)}
                ).encode(),
                JSON,
            )

        def _locale(self) -> str:
            """Cookie override, else Accept-Language, else English."""
            return i18n.negotiate(
                i18n.parse_cookie(self.headers.get("Cookie")),
                self.headers.get("Accept-Language"),
            )

        def _admin(self):
            query = parse_qs(urlparse(self.path).query)
            wanted = (query.get("lang") or [None])[0]
            if wanted in i18n.LOCALES:
                self.send_response(303)
                self.send_header(
                    "Set-Cookie",
                    f"{i18n.COOKIE}={wanted}; Path=/; Max-Age=31536000; SameSite=Lax",
                )
                self.send_header("Location", "/admin")
                self.end_headers()
                return
            settings = store.get()
            html = admin.page(
                self._context(settings),
                settings,
                status,
                resolution_of(panel),
                panel is not None,
                store.path.parent,
                lang=self._locale(),
            )
            self._send(200, html.encode(), HTML)

        def _update(self):
            self._send(
                200,
                json.dumps(
                    {
                        "updating": bool(status.updating or status.update_requested),
                        "version": __version__,
                        "phase": status.update_phase,
                        "percent": status.update_percent,
                    }
                ).encode(),
                JSON,
            )

        def _health(self):
            self._send(200, b"ok", "text/plain")

        ROUTES: ClassVar[dict] = {
            "/collage.png": _page_png,
            "/preview.png": _preview_png,
            "/state": _state,
            "/species": _species,
            "/admin": _admin,
            "/update": _update,
            "/health": _health,
        }

        def do_GET(self):
            route = urlparse(self.path).path
            if route in FILES:
                name, content_type = FILES[route]
                self._send_cached((STATIC_DIR / name).read_bytes(), content_type)
            elif route in self.ROUTES:
                try:
                    self.ROUTES[route](self)
                    note("", self.degraded)
                except Unavailable as exc:
                    note(f"{route}: {exc}", True)
                    self._send(503, f"detector unavailable: {exc}".encode(), "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_HEAD(self):
            # Full GET, body dropped: a wrong Content-Length is worse than no HEAD.
            self.head = True
            self.do_GET()

        def _analyze_audio(self):
            """Upload an audio file, run BirdNET-Go `file`, inject into the overlay."""
            ui = UI(self._locale())
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                self._send(
                    400, json.dumps({"ok": False, "message": ui.t("analyze_no_file")}).encode(), JSON
                )
                return
            if length > analyze.MAX_UPLOAD_BYTES:
                self._send(
                    413,
                    json.dumps({"ok": False, "message": ui.t("analyze_too_large")}).encode(),
                    JSON,
                )
                return
            body = self.rfile.read(length)
            try:
                parts = parse_multipart(self.headers.get("Content-Type", ""), body)
            except ValueError as exc:
                self._send(400, json.dumps({"ok": False, "message": str(exc)}).encode(), JSON)
                return
            upload = parts.files.get("audio") or parts.files.get("file")
            if upload is None or not upload.data:
                self._send(
                    400,
                    json.dumps({"ok": False, "message": ui.t("analyze_pick_file")}).encode(),
                    JSON,
                )
                return
            suffix = Path(upload.filename or "audio.wav").suffix.lower() or ".wav"
            if suffix not in analyze.ALLOWED_SUFFIXES:
                self._send(
                    400,
                    json.dumps(
                        {"ok": False, "message": ui.t("analyze_bad_format", suffix=suffix)}
                    ).encode(),
                    JSON,
                )
                return
            if not isinstance(source, UploadOverlay):
                self._send(
                    500,
                    json.dumps({"ok": False, "message": ui.t("analyze_disabled")}).encode(),
                    JSON,
                )
                return
            if not analyze_lock.acquire(blocking=False):
                self._send(
                    409,
                    json.dumps({"ok": False, "message": ui.t("analyze_busy")}).encode(),
                    JSON,
                )
                return
            try:
                with tempfile.TemporaryDirectory(prefix="fugleramme-upload-") as tmp:
                    path = Path(tmp) / f"upload{suffix}"
                    path.write_bytes(upload.data)
                    try:
                        detections = analyze.run_file_analysis(path)
                    except analyze.AnalyzeError as exc:
                        source.clear()
                        msg = str(exc)
                        if msg in ("无法识别", "Could not recognize"):
                            msg = ui.t("analyze_fail")
                        self._send(
                            200,
                            json.dumps({"ok": False, "message": msg, "species": []}).encode(),
                            JSON,
                        )
                        return
                settings = store.get()
                style = resolve(settings.style, images_dir)
                drawable = drawable_keys(images_dir, style)
                # Skip species this style cannot draw - no "no art" rows on the page.
                kept = [d for d in detections if name_key(d.scientific_name) in drawable]
                if not kept:
                    source.clear()
                    self._send(
                        200,
                        json.dumps(
                            {
                                "ok": False,
                                "message": (
                                    ui.t("analyze_no_art") if detections else ui.t("analyze_fail")
                                ),
                                "species": [],
                                "skipped": len(detections),
                            }
                        ).encode(),
                        JSON,
                    )
                    return
                source.set_upload(kept)
                namer_of = namer(
                    settings.primary_language,
                    settings.secondary_language,
                    store.path.parent,
                )
                species = [
                    {
                        "scientific": d.scientific_name,
                        "name": namer_of.inline(d.scientific_name),
                        "confidence": round(d.confidence, 3),
                    }
                    for d in kept
                ]
                skipped = len(detections) - len(kept)
                message = ui.t("analyze_ok", n=len(species))
                if skipped:
                    message += ui.t("analyze_skipped", n=skipped)
                self._send(
                    200,
                    json.dumps(
                        {"ok": True, "message": message, "species": species, "skipped": skipped}
                    ).encode(),
                    JSON,
                )
            finally:
                analyze_lock.release()

        def do_POST(self):
            route = urlparse(self.path).path
            if route == "/analyze-audio":
                self._analyze_audio()
                return
            length = int(self.headers.get("Content-Length", 0))
            # keep_blank_values: an emptied field is a change, not an absent one.
            # "None" for the second language and a cleared credential both post blank.
            form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            # POST, not a query: the connection test carries a password.
            if route == "/detector":
                answer = admin.connection(form, store.get(), lang=self._locale())
                self._send(200, json.dumps(answer).encode(), JSON)
                return
            if route != "/admin":
                self._send(404, b"not found", "text/plain")
                return
            action = form.get("action", [""])[0]
            if action == "check":
                status.update_error = None
                status.update_available = updates.available(force=True)
            elif action == "update" and status.update_available and not updates.in_container():
                # The loop installs it: exiting mid-render or mid-push is not safe here.
                status.update_requested = status.update_available
            else:
                store.update(**admin.form_changes(form))
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

    return Handler


def serve(
    source: Source,
    images_dir: Path,
    host: str,
    port: int,
    store: SettingsStore,
    picks: Picks,
    panel: Panel | None = None,
    status: Status | None = None,
) -> None:
    """Blocking server loop."""
    handler = make_handler(source, images_dir, store, picks, panel, status or Status())
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.serve_forever()
