"""The admin page: everything at `/admin` that is not HTTP.

Markup, style and behaviour live in `static/admin.{html,css,js}`; this fills the
template's slots. Copy comes from `i18n` (en/zh) so the chrome is bilingual.
"""

from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from urllib.parse import urlparse

from .. import __version__, modes, updates
from ..api import probe
from ..config import BIRDNET_PORT, DOCS_URL, WEB_HEIGHTS
from ..languages import NONE, Namer, catalog, catalog_failure, ordered
from ..modes import MODES
from ..names import available_styles, image_for, origin_of, source_of
from ..render.collage import NO_LIMIT, RANKINGS
from ..render.fonts import CJK_FONTS, FONTS, LABEL_SIZES
from ..render.packing import LAYOUTS
from ..settings import (
    DEFAULT_LIMIT,
    LIMIT_CEILING,
    LOOKBACK_OPTIONS,
    MARGIN_CEILING,
    REFRESH_OPTIONS,
    ROTATIONS,
    Settings,
    lookback_order,
    merged,
)
from ..source import NEEDS_PASSWORD, Unavailable
from ..status import Status
from . import STATIC_DIR, hostinfo, i18n
from .i18n import UI

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

# The stored detector password never reaches the page; posting this back
# unchanged means "leave it alone".
PASSWORD_SET = "\u2022" * 8

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

# Style and plate names that don't title-case into something readable.
_NAMES = {
    "vonwright": "von Wright",
    "vonwright-rawpixel": "von Wright (rawpixel)",
    "gould-asia": "Gould (Birds of Asia)",
}


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value."""
    changes: dict[str, str | bool | int] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    for field in form.get(CHECKBOXES, [""])[0].split():
        changes[field] = field in form
    if changes.pop("limit_mode", None) == "all":
        changes["species_limit"] = NO_LIMIT
    if changes.get("detector_password") == PASSWORD_SET:
        del changes["detector_password"]
    return changes


def subjects(ctx: modes.Context) -> list[tuple[str, str | None, str]]:
    """What the current mode's page is about, each with the plate its artwork
    was cut from - None when it has none to draw - and the plate's citation."""
    rows: list[tuple[str, str | None, str]] = []
    for name in modes.subjects(ctx):
        pick = image_for(name, ctx.images_dir, ctx.style, ctx.picks)
        if not pick:
            rows.append((name, None, ""))
            continue
        rows.append((name, source_of(pick) or ctx.style, origin_of(pick)))
    return rows


def _display_name(name: str) -> str:
    return _NAMES.get(name, name.replace("-", " ").title())


def _options(values, selected, label=str) -> str:
    return "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>{label(v)}</option>'
        for v in values
    )


def _radios(field: str, options: list[tuple[str, str]], active: str) -> str:
    return "".join(
        f'<label class="src"><input type="radio" name="{field}" value="{value}"'
        f"{' checked' if value == active else ''}> {label}</label>"
        for value, label in options
    )


def _checkbox(field: str, label: str, checked: bool, disabled: bool = False) -> str:
    return (
        f'<label class="src"><input type="checkbox" name="{field}"'
        f"{' checked' if checked else ''}{' disabled' if disabled else ''}> {label}</label>"
    )


def _action(action: str, label: str) -> str:
    return (
        f'<form class="inline {action}" method="post" action="/admin">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<button type="submit">{label}</button></form>'
    )


def _state(ok: bool, good: str, bad: str) -> str:
    return f'<span class="{"ok" if ok else "bad"}">{good if ok else bad}</span>'


def _ui() -> UI:
    return i18n.get()


def _fix(problem: str) -> str:
    ui = _ui()
    return f"{html.escape(ui.failure(problem))}. {ui.t('fix_see')}"


def _outage(state: str) -> str:
    ui = _ui()
    return ui.t("needs_password") if state == "auth" else ui.t("detector_unreachable")


def _detector(state: str, version: str, reading: bool, names_failure: str = "") -> str:
    ui = _ui()
    if not reading:
        if state == "auth":
            return f'<span class="bad">{ui.t("running")} · {ui.t("needs_password")}</span>'
        return f'<span class="bad">{ui.t("unreachable")}</span>'
    running = ui.t("running") + (f" · {version}" if version else "")
    if names_failure == NEEDS_PASSWORD:
        return f'<span class="warn">{running} · {ui.t("needs_password")}</span>'
    return f'<span class="ok">{running}</span>'


def _answers() -> dict[str, tuple[str, str]]:
    ui = _ui()
    return {
        "ok": (ui.t("connected"), _detector("ok", "", reading=True)),
        "auth": ("", _detector("auth", "", reading=False)),
        "names": (
            ui.t("connected"),
            _detector("ok", "", reading=True, names_failure=NEEDS_PASSWORD),
        ),
        "unreachable": (ui.t("unreachable"), _detector("down", "", reading=False)),
    }


def _duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _ago(dt: datetime) -> str:
    return f"{_duration(int((datetime.now(UTC) - dt).total_seconds()))} ago"


def _stamp(dt: datetime) -> str:
    local = dt.astimezone()
    fmt = "%H:%M" if local.date() == datetime.now().astimezone().date() else "%-d %b %H:%M"
    return f'<time title="{_ago(dt)}">{local.strftime(fmt)}</time>'


def _species_li(name: str, source: str | None, url: str) -> str:
    if source is None:
        return f'<li class="noart">{name} <small>{_ui().t("no_art")}</small></li>'
    plate = _display_name(source)
    if url:
        plate = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{plate}</a>'
    return f"<li>{name} <small>{plate}</small></li>"


def species_html(species: list[tuple[str, str | None, str]], name_of: Namer) -> str:
    return (
        "".join(_species_li(name_of.inline(name), source, url) for name, source, url in species)
        or f'<li class="empty">{_ui().t("none_yet")}</li>'
    )


def _language_select(
    field: str, languages: list[tuple[str, str]], selected: str, optional: bool = False
) -> str:
    ui = _ui()
    items = [(NONE, ui.language_name(NONE))] if optional else []
    items += [(code, ui.language_name(code, name)) for code, name in languages if code != NONE]
    if selected not in dict(items):
        items.append((selected, f"{ui.language_name(selected, selected)} {ui.t('unavailable')}"))
    labels = dict(items)
    codes = [code for code, _ in items]
    return f'<select name="{field}">{_options(codes, selected, labels.get)}</select>'


def _update(status: Status) -> str:
    ui = _ui()
    if status.updating or status.update_requested:
        label, value = status.update_phase or ui.t("installing"), ""
        if status.update_percent is not None:
            label, value = f"{label} {status.update_percent}%", f' value="{status.update_percent}"'
        return f'<span id="phase">{label}</span><progress id="bar" max="100"{value}></progress>'
    if status.update_error:
        return f'<span class="bad">{status.update_error}</span>{_action("check", ui.t("retry"))}'
    if status.update_available:
        install = (
            f'·<pre class="cmd">{html.escape(updates.CONTAINER_COMMAND)}</pre>'
            if updates.in_container()
            else _action("update", ui.t("install"))
        )
        return f'<span class="warn">{status.update_available} {ui.t("available")}</span>{install}'
    return f'<span id="state">{ui.t("up_to_date")}</span>{_action("check", ui.t("check"))}'


def _auto_update(settings: Settings) -> str:
    ui = _ui()
    if updates.in_container():
        return f'<div class="block off">{_checkbox("auto_update", ui.t("auto_update_container"), False, True)}</div>'
    return (
        '<form class="block" method="post" action="/admin">'
        f'<input type="hidden" name="{CHECKBOXES}" value="auto_update">'
        f"{_checkbox('auto_update', ui.t('auto_update'), settings.auto_update)}"
        f'<button type="submit">{ui.t("save")}</button></form>'
    )


def _names_field(settings: Settings, languages: list[tuple[str, str]], failure: str) -> str:
    ui = _ui()
    note = (
        f'<p class="note bad">{_fix(ui.t("no_languages", detail=ui.failure(failure)))}</p>'
        if failure
        else ""
    )
    western = (
        f'<div class="font-panel" id="font-western" data-script="western">'
        f'<label class="sub"><small>{ui.t("western_font")}</small>'
        f'<select name="label_font">'
        f"{_options(FONTS, settings.label_font, lambda k: FONTS[k][0])}</select></label>"
        f"</div>"
    )
    chinese = (
        f'<div class="font-panel" id="font-cjk" data-script="cjk">'
        f'<label class="sub"><small>{ui.t("chinese_font")}</small>'
        f'<select name="cjk_font">'
        f"{_options(CJK_FONTS, settings.cjk_font, lambda k: CJK_FONTS[k][0])}</select></label>"
        f"{_checkbox('cjk_bold', ui.t('bold'), settings.cjk_bold)}"
        f"</div>"
    )
    shared = (
        f'<p class="font-shared" id="font-western-shared" hidden>'
        f"{ui.t('font_shared')}</p>"
    )
    return (
        f'<div class="field" id="names"><span>{ui.t("bird_names")}</span>'
        f"{_checkbox('show_names', ui.t('show_names'), settings.show_names)}"
        f"{note}"
        f'<div class="lang-cols">'
        f'<div class="lang-col" id="lang-primary" data-slot="primary">'
        f'<small class="lang-title">{ui.t("primary_lang")}</small>'
        f'<label class="sub">'
        f"{_language_select('primary_language', languages, settings.primary_language)}</label>"
        f'<div class="font-slot"></div>'
        f"</div>"
        f'<div class="lang-col" id="lang-secondary" data-slot="secondary">'
        f'<small class="lang-title">{ui.t("secondary_lang")}</small>'
        f'<label class="sub">'
        f"{_language_select('secondary_language', languages, settings.secondary_language, optional=True)}</label>"
        f'<div class="font-slot"></div>'
        f"{shared}"
        f"</div>"
        f"</div>"
        f'<div id="font-dock" hidden>{western}{chinese}</div>'
        f'<label class="sub"><small>{ui.t("text_size")}</small><select name="label_size">'
        f"{_options(LABEL_SIZES, settings.label_size, lambda k: ui.label_size(k, LABEL_SIZES[k][0]))}</select></label>"
        f"</div>"
    )


def _text_field(field: str, label: str, value: str, kind: str = "text", hint: str = "") -> str:
    return (
        f"<label><span>{label}{f' <small>{hint}</small>' if hint else ''}</span>"
        f'<input type="{kind}" name="{field}" value="{html.escape(value, quote=True)}"></label>'
    )


def _detector_field(settings: Settings) -> str:
    ui = _ui()
    return (
        _text_field("detector_url", ui.t("address"), settings.detector_url, "url")
        + f'<details id="credentials"{" open" if settings.detector_password else ""}>'
        + f"<summary>{ui.t('credentials')} <small>{ui.t('basic_auth')}</small></summary>"
        + _text_field(
            "detector_password",
            ui.t("password"),
            PASSWORD_SET if settings.detector_password else "",
            "password",
        )
        + "</details>"
    )


def birdnet_link(url: str) -> tuple[str, int | None]:
    parsed = urlparse(url)
    if parsed.hostname in _LOOPBACK:
        return url, parsed.port or BIRDNET_PORT
    return url, None


def connection(form: dict[str, list[str]], settings: Settings, lang: str = "en") -> dict:
    token = i18n.use(UI(lang))
    try:
        tried = merged(settings, **form_changes(form))
        state, detail = probe(
            tried.detector_url, tried.detector_username, tried.detector_password
        )
        lead, row = _answers()[state]
        ui = _ui()
        return {
            "state": state,
            "text": " · ".join(
                part for part in (lead, ui.failure(detail) if detail else "") if part
            ),
            "status": row,
        }
    finally:
        i18n._current.reset(token)


def _lookbacks(settings: Settings) -> str:
    ui = _ui()
    labels = {hours: ui.lookback_hours(hours) for hours, _ in LOOKBACK_OPTIONS}
    labels.setdefault(settings.lookback_hours, ui.lookback_hours(settings.lookback_hours))
    return _options(sorted(labels, key=lookback_order), settings.lookback_hours, labels.get)


def _refreshes(settings: Settings) -> str:
    ui = _ui()
    labels = {minutes: ui.refresh_minutes(minutes) for minutes, _ in REFRESH_OPTIONS}
    labels.setdefault(settings.refresh_minutes, ui.refresh_minutes(settings.refresh_minutes))
    return _options(sorted(labels), settings.refresh_minutes, labels.get)


def _hint(text: str) -> str:
    note = html.escape(text, quote=True)
    return f'<span class="hint" tabindex="0" role="img" aria-label="{note}"></span>'


def _species_field(settings: Settings) -> str:
    ui = _ui()
    limited = settings.species_limit != NO_LIMIT
    count = settings.species_limit if limited else DEFAULT_LIMIT
    ranking = [(key, ui.ranking(key, label)) for key, label in RANKINGS.items()]
    return (
        f'<div class="field" id="limit">'
        f"<span>{ui.t('species_limit')} "
        f"{_hint(ui.t('species_limit_hint', n=DEFAULT_LIMIT))}</span>"
        f'<div class="src"><label class="src"><input type="radio" name="limit_mode"'
        f' value="some"{" checked" if limited else ""}> {ui.t("at_most")}</label>'
        f'<input type="number" name="species_limit" min="1" max="{LIMIT_CEILING}"'
        f' value="{count}"{"" if limited else " disabled"}'
        f' aria-label="{ui.t("species_count_aria")}"></div>'
        f'<label class="src"><input type="radio" name="limit_mode" value="all"'
        f"{'' if limited else ' checked'}> {ui.t('show_all')}</label>"
        f'<div class="sub" id="ranking"><small>{ui.t("which_to_keep")}</small>'
        f"{_radios('ranking', ranking, settings.ranking)}</div>"
        f"</div>"
    )


def _radio_field(
    label: str, name: str, options: list[tuple[str, str]], active: str, id: str = ""
) -> str:
    tag = f' id="{id}"' if id else ""
    return f'<div class="field"{tag}><span>{label}</span>{_radios(name, options, active)}</div>'


def _layout_field(settings: Settings) -> str:
    ui = _ui()
    hint = "\n\n".join(
        f"{ui.layout(key)[0]}: {ui.layout(key)[1]}" for key, _layout in LAYOUTS.items()
    )
    options = [(key, ui.layout(key)[0]) for key in LAYOUTS]
    return _radio_field(
        f"{ui.t('layout')} {_hint(hint)}", "layout", options, settings.layout, id="layout"
    )


def page(
    ctx: modes.Context,
    settings: Settings,
    status: Status,
    panel_size: tuple[int, int],
    detected: bool,
    names_dir: Path,
    lang: str = "en",
) -> str:
    """The admin page. `lang` selects en/zh chrome copy."""
    token = i18n.use(UI(lang))
    try:
        return _page(ctx, settings, status, panel_size, detected, names_dir)
    finally:
        i18n._current.reset(token)


def _page(
    ctx: modes.Context,
    settings: Settings,
    status: Status,
    panel_size: tuple[int, int],
    detected: bool,
    names_dir: Path,
) -> str:
    ui = _ui()
    languages = ordered(catalog(names_dir))
    names_failure = catalog_failure()
    detector_state, detector_version = hostinfo.detector(settings.detector_url)
    try:
        latest, rows = ctx.source.latest(), subjects(ctx)
    except Unavailable:
        latest, rows = None, None
    windowed = modes.mode_of(settings.mode).windowed
    online, iface = hostinfo.online()
    rendered = _stamp(status.rendered_at) if status.rendered_at else ui.t("not_yet")
    if status.push_error:
        rendered += f" · {ui.t('push_failing', error=status.push_error)}"
    w, h = settings.web_size(panel_size)
    glass = f"{panel_size[0]}×{panel_size[1]}"
    birdnet_url, birdnet_port = birdnet_link(settings.detector_url)
    count = len(rows) if rows is not None else 0
    return Template((STATIC_DIR / "admin.html").read_text()).substitute(
        html_lang=ui.html_lang,
        title=ui.t("title"),
        version=__version__,
        app_version=__version__,
        docs_url=DOCS_URL,
        checkboxes=CHECKBOXES,
        nav_kiosk=ui.t("nav_kiosk"),
        nav_birdnet_title=ui.t("nav_birdnet_title"),
        nav_docs=ui.t("nav_docs"),
        lang_en_selected=" selected" if ui.code == "en" else "",
        lang_zh_selected=" selected" if ui.code == "zh" else "",
        tab_display=ui.t("tab_display"),
        tab_system=ui.t("tab_system"),
        resolution=ui.t("resolution"),
        resolution_hint=ui.t("resolution_hint"),
        rotation=ui.t("rotation"),
        rotation_hint=ui.t("rotation_hint"),
        margin=ui.t("margin"),
        margin_hint=ui.t("margin_hint"),
        margin_value=settings.margin,
        margin_max=MARGIN_CEILING,
        refresh=ui.t("refresh"),
        refresh_hint=ui.t("refresh_hint"),
        lookback=ui.t("lookback"),
        lookback_hint=ui.t("lookback_hint"),
        save=ui.t("save"),
        preview=ui.t("preview"),
        rendering=ui.t("rendering"),
        shot_alt=ui.t("shot_alt"),
        analyze_title=ui.t("analyze_title"),
        analyze_note=ui.t("analyze_note"),
        analyze_file=ui.t("analyze_file"),
        analyze_btn=ui.t("analyze_btn"),
        species_heading=f'{ui.t("species_on_page")} (<span id="count">{count}</span>)',
        species_count=count,
        updates=ui.t("updates"),
        version_label=ui.t("version"),
        update=ui.t("update"),
        # version= also used in asset query strings below via __version__
        detector=ui.t("detector"),
        test_connection=ui.t("test_connection"),
        system=ui.t("system"),
        panel=ui.t("panel"),
        host=ui.t("host"),
        network=ui.t("network"),
        disk=ui.t("disk"),
        started=ui.t("started"),
        kiosk_size=ui.t("kiosk_size"),
        activity=ui.t("activity"),
        rendered=ui.t("rendered"),
        latest=ui.t("latest"),
        config=json.dumps(
            {
                "birdnetUrl": birdnet_url,
                "birdnetPort": birdnet_port,
                "version": __version__,
                "windowedModes": [k for k, m in MODES.items() if m.windowed],
                "panel": [max(panel_size), min(panel_size)],
                "lang": ui.code,
                "i18n": {
                    "testing": ui.t("js_testing"),
                    "noAnswer": ui.t("js_no_answer"),
                    "previewUnavailable": ui.t("js_preview_unavailable"),
                    "updated": ui.t("js_updated", version=__version__),
                    "pickFile": ui.t("js_pick_file"),
                    "analyzing": ui.t("js_analyzing"),
                    "noResponse": ui.t("js_no_response"),
                    "cannotRecognize": ui.t("js_cannot_recognize"),
                },
            }
        ),
        mode_field=_radio_field(
            ui.t("mode"),
            "mode",
            [(k, ui.mode(k, m.label)) for k, m in MODES.items()],
            settings.mode,
        ),
        resolutions=_options(
            WEB_HEIGHTS,
            settings.web_resolution,
            lambda r: "{} ({}×{})".format(
                r, *replace(settings, web_resolution=r).web_size(panel_size)
            ),
        ),
        rotations=_options(
            ROTATIONS, settings.rotation, lambda r: f"{r}° {ui.aspect(r % 180)}"
        ),
        refreshes=_refreshes(settings),
        lookback_off="" if windowed else ' class="off"',
        lookback_disabled="" if windowed else " disabled",
        lookbacks=_lookbacks(settings),
        limit_field=_species_field(settings),
        layout_field=_layout_field(settings),
        names_field=_names_field(settings, languages, names_failure),
        style_field=_radio_field(
            ui.t("artwork_style"),
            "style",
            [(s, _display_name(s)) for s in available_styles(ctx.images_dir)],
            ctx.style,
        ),
        species_rows=(
            species_html(rows, ctx.namer)
            if rows is not None
            else f'<li class="problem">{_fix(_outage(detector_state))}</li>'
        ),
        update_html=_update(status),
        auto_update=_auto_update(settings),
        panel_value=(
            ui.t("panel_detected", size=glass)
            if detected
            else ui.t("panel_assumed", size=glass)
        ),
        birdnet=_detector(detector_state, detector_version, rows is not None, names_failure),
        detector_field=_detector_field(settings),
        host_value=hostinfo.lan_address(updates.in_container()),
        online=_state(online, ui.t("online"), ui.t("offline"))
        + (f" · {iface}" if iface else ""),
        disk_value=hostinfo.disk_free(names_dir),
        started_value=_stamp(status.started_at),
        kiosk_size_value=f"{w}×{h}",
        rendered_value=rendered,
        latest_value=(
            f"{ctx.namer.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
            if latest
            else (ui.t("none_yet") if rows is not None else _outage(detector_state))
        ),
    )
