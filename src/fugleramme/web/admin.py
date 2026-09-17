"""The admin page: everything at `/admin` that is not HTTP.

Markup, style and behaviour live in `static/admin.{html,css,js}`; this fills the
template's slots. Pure string builders, so none of it needs a server to test.
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
from . import STATIC_DIR, hostinfo, zh

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

# The stored detector password never reaches the page; posting this back
# unchanged means "leave it alone".
PASSWORD_SET = "\u2022" * 8

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

_ASPECT = zh.ASPECT

# Style and plate names that don't title-case into something readable.
_NAMES = {
    "vonwright": "von Wright",
    "vonwright-rawpixel": "von Wright (rawpixel)",
    "gould-asia": "Gould (Birds of Asia)",
}


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. settings._coerce validates the rest."""
    changes: dict[str, str | bool | int] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    for field in form.get(CHECKBOXES, [""])[0].split():
        changes[field] = field in form
    if changes.pop("limit_mode", None) == "all":
        changes["species_limit"] = NO_LIMIT  # the box is disabled, so it posts nothing
    if changes.get("detector_password") == PASSWORD_SET:
        del changes["detector_password"]  # untouched, so the stored one stands
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
        # Unlisted (a hand-filled style keeps no manifest): name the style itself.
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


def _fix(problem: str) -> str:
    """A problem and the tab that fixes it, worded the same wherever it turns up."""
    return (
        f'{html.escape(zh.failure(problem))}。'
        f'请到 <a href="#detector" data-tab="system">系统 → 检测器</a> 查看。'
    )


def _outage(state: str) -> str:
    """What to show where a bird would have been. Only a refusal names the
    password; anything else reads as unreachable, which is what the page saw."""
    return zh.FAILURES[NEEDS_PASSWORD] if state == "auth" else zh.FAILURES["detector unreachable"]


def _detector(state: str, version: str, reading: bool, names_failure: str = "") -> str:
    """The configured BirdNET-Go's state, and the version it reports.

    `state` is `/health` asked without credentials, so under PrivateMode it is
    401 for every frame alike - the ones holding a working password included.
    Only `reading`, whether the page's own calls came back, tells those apart.
    Miss that and a frame with everything configured is told to fix it.

    A detector that answers and holds something back is not unreachable either,
    so the row says what it wants instead: a locale list refusing us is
    BirdNET-Go's settings behind authentication while the detections stay open.
    """
    if not reading:
        if state == "auth":
            return f'<span class="bad">运行中 · {zh.FAILURES[NEEDS_PASSWORD]}</span>'
        return '<span class="bad">不可达</span>'
    running = "运行中" + (f" · {version}" if version else "")
    if names_failure == NEEDS_PASSWORD:  # the settings only: birds yes, names no
        return f'<span class="warn">{running} · {zh.FAILURES[NEEDS_PASSWORD]}</span>'
    return f'<span class="ok">{running}</span>'


# A probe's answer in the test's own words, and the status row it leaves behind.
# The row comes from `_detector`, so the test and a page load cannot describe one
# detector differently. "auth" leads with nothing: the detail is the whole answer.
_ANSWERS = {
    "ok": ("已连接", _detector("ok", "", reading=True)),
    "auth": ("", _detector("auth", "", reading=False)),
    "names": ("已连接", _detector("ok", "", reading=True, names_failure=NEEDS_PASSWORD)),
    "unreachable": ("不可达", _detector("down", "", reading=False)),
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
    # Marks species counted in the window but omitted from the collage (#9); else
    # names the plate the artwork was cut from, per the style's manifest.
    if source is None:
        return f'<li class="noart">{name} <small>无插画</small></li>'
    plate = _display_name(source)
    if url:
        plate = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{plate}</a>'
    return f"<li>{name} <small>{plate}</small></li>"


def species_html(species: list[tuple[str, str | None, str]], name_of: Namer) -> str:
    return (
        "".join(_species_li(name_of.inline(name), source, url) for name, source, url in species)
        or '<li class="empty">暂无</li>'
    )


def _language_select(
    field: str, languages: list[tuple[str, str]], selected: str, optional: bool = False
) -> str:
    """A language dropdown, BirdNET-Go's offering in preference order. A saved code
    it is not serving stays selectable, so an outage cannot quietly reset the
    frame's language on the next Save."""
    items = [(NONE, zh.language_name(NONE))] if optional else []
    items += [(code, zh.language_name(code, name)) for code, name in languages if code != NONE]
    if selected not in dict(items):
        items.append((selected, f"{zh.language_name(selected, selected)}（不可用）"))
    labels = dict(items)
    codes = [code for code, _ in items]
    return f'<select name="{field}">{_options(codes, selected, labels.get)}</select>'


def _update(status: Status) -> str:
    # `requested` counts as installing: the loop only picks it up a tick later.
    if status.updating or status.update_requested:
        # A phase with no percent leaves the bar valueless, which renders indeterminate.
        label, value = status.update_phase or "正在安装…", ""
        if status.update_percent is not None:
            label, value = f"{label} {status.update_percent}%", f' value="{status.update_percent}"'
        return f'<span id="phase">{label}</span><progress id="bar" max="100"{value}></progress>'
    if status.update_error:
        return f'<span class="bad">{status.update_error}</span>{_action("check", "重试")}'
    if status.update_available:
        # The command stands in for the button: the image is the host's to replace.
        install = (
            f'·<pre class="cmd">{html.escape(updates.CONTAINER_COMMAND)}</pre>'
            if updates.in_container()
            else _action("update", "安装")
        )
        return f'<span class="warn">{status.update_available} 可用</span>{install}'
    return f'<span id="state">已是最新</span>{_action("check", "检查")}'


def _auto_update(settings: Settings) -> str:
    """The auto-install toggle, shown disabled in a container: nothing in here can
    pull an image, and a switch that does nothing is worse than no switch."""
    if updates.in_container():
        label = "自动安装新版本 <small>· 容器模式下不可用</small>"
        return f'<div class="block off">{_checkbox("auto_update", label, False, True)}</div>'
    return (
        '<form class="block" method="post" action="/admin">'
        f'<input type="hidden" name="{CHECKBOXES}" value="auto_update">'
        f"{_checkbox('auto_update', '自动安装新版本', settings.auto_update)}"
        '<button type="submit">保存</button></form>'
    )


def _names_field(settings: Settings, languages: list[tuple[str, str]], failure: str) -> str:
    """The names block as two language columns. Each column holds its language
    pick; font controls are moved into the column that needs them by admin.js."""
    note = (
        f'<p class="note bad">{_fix(f"无可用语言：{zh.failure(failure)}")}</p>'
        if failure
        else ""
    )
    western = (
        f'<div class="font-panel" id="font-western" data-script="western">'
        f'<label class="sub"><small>西文字体</small>'
        f'<select name="label_font">'
        f"{_options(FONTS, settings.label_font, lambda k: FONTS[k][0])}</select></label>"
        f"</div>"
    )
    chinese = (
        f'<div class="font-panel" id="font-cjk" data-script="cjk">'
        f'<label class="sub"><small>中文字体</small>'
        f'<select name="cjk_font">'
        f"{_options(CJK_FONTS, settings.cjk_font, lambda k: CJK_FONTS[k][0])}</select></label>"
        f"{_checkbox('cjk_bold', '加粗', settings.cjk_bold)}"
        f"</div>"
    )
    shared = (
        f'<p class="font-shared" id="font-western-shared" hidden>'
        f"第二语言与主语言共用西文字体</p>"
    )
    return (
        f'<div class="field" id="names"><span>鸟类名称</span>'
        f"{_checkbox('show_names', '显示鸟名', settings.show_names)}"
        f"{note}"
        f'<div class="lang-cols">'
        f'<div class="lang-col" id="lang-primary" data-slot="primary">'
        f'<small class="lang-title">主语言</small>'
        f'<label class="sub">'
        f"{_language_select('primary_language', languages, settings.primary_language)}</label>"
        f'<div class="font-slot"></div>'
        f"</div>"
        f'<div class="lang-col" id="lang-secondary" data-slot="secondary">'
        f'<small class="lang-title">第二语言</small>'
        f'<label class="sub">'
        f"{_language_select('secondary_language', languages, settings.secondary_language, optional=True)}</label>"
        f'<div class="font-slot"></div>'
        f"{shared}"
        f"</div>"
        f"</div>"
        f'<div id="font-dock" hidden>{western}{chinese}</div>'
        f'<label class="sub"><small>字号</small><select name="label_size">'
        f"{_options(LABEL_SIZES, settings.label_size, lambda k: zh.LABEL_SIZES.get(k, LABEL_SIZES[k][0]))}</select></label>"
        f"</div>"
    )


def _text_field(field: str, label: str, value: str, kind: str = "text", hint: str = "") -> str:
    return (
        f"<label><span>{label}{f' <small>{hint}</small>' if hint else ''}</span>"
        f'<input type="{kind}" name="{field}" value="{html.escape(value, quote=True)}"></label>'
    )


def _detector_field(settings: Settings) -> str:
    """Where the frame reads from. Credentials fold away until one is stored -
    or until a test comes back asking for them, which admin.js opens.

    A password only: the username BirdNET-Go's API insists on is a fixed client
    id (`api.CLIENT_ID`). An install that changed `security.basicauth.clientid`
    sets `detector_username` in settings.json instead.
    """
    return (
        _text_field("detector_url", "地址", settings.detector_url, "url")
        + f'<details id="credentials"{" open" if settings.detector_password else ""}>'
        + "<summary>凭证 <small>（Basic Authentication）</small></summary>"
        + _text_field(
            "detector_password",
            "密码",
            PASSWORD_SET if settings.detector_password else "",
            "password",
        )
        + "</details>"
    )


def birdnet_link(url: str) -> tuple[str, int | None]:
    """The nav link to BirdNET-Go: (address, port to substitute this page's host
    on). A loopback address is loopback from the Pi only, so a remote browser
    cannot follow it; anything else is reached exactly as configured."""
    parsed = urlparse(url)
    if parsed.hostname in _LOOPBACK:
        return url, parsed.port or BIRDNET_PORT
    return url, None


def connection(form: dict[str, list[str]], settings: Settings) -> dict:
    """The connection test, over the values the form is holding rather than the
    saved ones - validated and placeholder-resolved exactly as Save would.

    `status` is the row `_detector` would render for the same answer, so a test
    and a page load can never describe one detector differently."""
    tried = merged(settings, **form_changes(form))
    state, detail = probe(tried.detector_url, tried.detector_username, tried.detector_password)
    lead, row = _ANSWERS[state]
    return {
        "state": state,
        "text": " · ".join(part for part in (lead, zh.failure(detail) if detail else "") if part),
        "status": row,
    }


def _lookbacks(settings: Settings) -> str:
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = {hours: zh.lookback_hours(hours) for hours, _ in LOOKBACK_OPTIONS}
    labels.setdefault(settings.lookback_hours, zh.lookback_hours(settings.lookback_hours))
    return _options(sorted(labels, key=lookback_order), settings.lookback_hours, labels.get)


def _refreshes(settings: Settings) -> str:
    labels = {minutes: zh.refresh_minutes(minutes) for minutes, _ in REFRESH_OPTIONS}
    labels.setdefault(settings.refresh_minutes, zh.refresh_minutes(settings.refresh_minutes))
    return _options(sorted(labels), settings.refresh_minutes, labels.get)


def _hint(text: str) -> str:
    """The note beside a field label. A span, not a button: a <label> may hold
    only one labelable element and that is the select. admin.css draws the
    bubble from `aria-label`, so one attribute is both the text and the name."""
    note = html.escape(text, quote=True)
    return f'<span class="hint" tabindex="0" role="img" aria-label="{note}"></span>'


def _species_field(settings: Settings) -> str:
    """How many species the collage shows, and which ones it keeps (#53).

    The count is disabled under "Show all", so it posts nothing - `form_changes`
    reads the radio instead.
    """
    limited = settings.species_limit != NO_LIMIT
    count = settings.species_limit if limited else DEFAULT_LIMIT
    ranking = [(key, zh.RANKINGS.get(key, label)) for key, label in RANKINGS.items()]
    return (
        f'<div class="field" id="limit">'
        f"<span>画面上的物种 "
        f"{_hint(f'超过 {DEFAULT_LIMIT} 种会显得很拥挤')}</span>"
        f'<div class="src"><label class="src"><input type="radio" name="limit_mode"'
        f' value="some"{" checked" if limited else ""}> 最多</label>'
        f'<input type="number" name="species_limit" min="1" max="{LIMIT_CEILING}"'
        f' value="{count}"{"" if limited else " disabled"}'
        f' aria-label="物种数量"></div>'
        f'<label class="src"><input type="radio" name="limit_mode" value="all"'
        f"{'' if limited else ' checked'}> 全部显示</label>"
        f'<div class="sub" id="ranking"><small>保留哪些</small>'
        f"{_radios('ranking', ranking, settings.ranking)}</div>"
        f"</div>"
    )


def _radio_field(
    label: str, name: str, options: list[tuple[str, str]], active: str, id: str = ""
) -> str:
    tag = f' id="{id}"' if id else ""
    return f'<div class="field"{tag}><span>{label}</span>{_radios(name, options, active)}</div>'


def _layout_field(settings: Settings) -> str:
    """How the collage packs its birds (#47). Dimmed with the lookback for the
    modes that draw one bird."""
    hint = "\n\n".join(
        f"{zh.LAYOUTS.get(key, (layout.label, layout.blurb))[0]}："
        f"{zh.LAYOUTS.get(key, (layout.label, layout.blurb))[1]}"
        for key, layout in LAYOUTS.items()
    )
    options = [
        (key, zh.LAYOUTS.get(key, (layout.label, layout.blurb))[0])
        for key, layout in LAYOUTS.items()
    ]
    return _radio_field(f"布局 {_hint(hint)}", "layout", options, settings.layout, id="layout")


def page(
    ctx: modes.Context,
    settings: Settings,
    status: Status,
    panel_size: tuple[int, int],
    detected: bool,
    names_dir: Path,
) -> str:
    """The admin page. Everything about the frame comes off `ctx`, so the
    listing always describes the page the preview is rendering.

    Renders with the detector down on purpose: this is the page you reach for
    when it is, so the rows that need it say so rather than vanish.
    """
    languages = ordered(catalog(names_dir))
    names_failure = catalog_failure()
    detector_state, detector_version = hostinfo.detector(settings.detector_url)
    try:
        latest, rows = ctx.source.latest(), subjects(ctx)
    except Unavailable:
        latest, rows = None, None
    windowed = modes.mode_of(settings.mode).windowed
    online, iface = hostinfo.online()
    rendered = _stamp(status.rendered_at) if status.rendered_at else "尚未渲染"
    if status.push_error:
        rendered += f" · 墨水屏推送失败（{status.push_error}）"
    w, h = settings.web_size(panel_size)
    glass = f"{panel_size[0]}×{panel_size[1]}"
    birdnet_url, birdnet_port = birdnet_link(settings.detector_url)
    return Template((STATIC_DIR / "admin.html").read_text()).substitute(
        version=__version__,
        docs_url=DOCS_URL,
        checkboxes=CHECKBOXES,
        config=json.dumps(
            {
                "birdnetUrl": birdnet_url,
                "birdnetPort": birdnet_port,
                "version": __version__,
                "windowedModes": [k for k, m in MODES.items() if m.windowed],
                "panel": [max(panel_size), min(panel_size)],  # landscape, as oriented() reads it
            }
        ),
        mode_field=_radio_field(
            "模式",
            "mode",
            [(k, zh.MODES.get(k, m.label)) for k, m in MODES.items()],
            settings.mode,
        ),
        resolutions=_options(
            WEB_HEIGHTS,
            settings.web_resolution,
            lambda r: "{} ({}×{})".format(
                r, *replace(settings, web_resolution=r).web_size(panel_size)
            ),
        ),
        rotations=_options(ROTATIONS, settings.rotation, lambda r: f"{r}° {_ASPECT[r % 180]}"),
        margin=settings.margin,
        margin_max=MARGIN_CEILING,
        refreshes=_refreshes(settings),
        lookback_off="" if windowed else ' class="off"',
        lookback_disabled="" if windowed else " disabled",
        lookbacks=_lookbacks(settings),
        limit_field=_species_field(settings),
        layout_field=_layout_field(settings),
        names_field=_names_field(settings, languages, names_failure),
        style_field=_radio_field(
            "插画风格",
            "style",
            [(s, _display_name(s)) for s in available_styles(ctx.images_dir)],
            ctx.style,
        ),
        species_count=len(rows) if rows is not None else 0,
        species_rows=(
            species_html(rows, ctx.namer)
            if rows is not None
            else f'<li class="problem">{_fix(_outage(detector_state))}</li>'
        ),
        update=_update(status),
        auto_update=_auto_update(settings),
        panel=f"已检测到 · {glass}" if detected else f"未检测到 · 假定 {glass}",
        birdnet=_detector(detector_state, detector_version, rows is not None, names_failure),
        detector_field=_detector_field(settings),
        host=hostinfo.lan_address(updates.in_container()),
        online=_state(online, "在线", "离线") + (f" · {iface}" if iface else ""),
        disk=hostinfo.disk_free(names_dir),
        started=_stamp(status.started_at),
        kiosk_size=f"{w}×{h}",
        rendered=rendered,
        latest=(
            f"{ctx.namer.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
            if latest
            else ("暂无" if rows is not None else _outage(detector_state))
        ),
    )
