"""Admin UI locales: English and Chinese.

Bird names still come from BirdNET-Go dictionaries; this module only covers the
admin chrome. Preference: Cookie `admin_lang`, then Accept-Language, else en.
"""

from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass

from ..render.collage import RANK_MOST_HEARD, RANK_RAREST, RANK_RAREST_EVER
from ..source import NEEDS_PASSWORD

LOCALES = ("en", "zh")
COOKIE = "admin_lang"
HTML_LANG = {"en": "en", "zh": "zh-CN"}

# English is the source locale (original project copy).
EN: dict[str, str] = {
    "title": "Fugleramme admin",
    "nav_kiosk": "Kiosk",
    "nav_birdnet_title": "Detections and statistics",
    "nav_docs": "Docs",
    "tab_display": "Display",
    "tab_system": "System",
    "mode": "Mode",
    "mode_collage": "Collage (default)",
    "mode_latest": "Latest visit",
    "mode_arrival": "First appearance",
    "resolution": "Resolution",
    "resolution_hint": "Affects the web preview only",
    "rotation": "Rotation",
    "rotation_hint": "Which way the frame is hung",
    "landscape": "(landscape)",
    "portrait": "(portrait)",
    "margin": "Margin",
    "margin_hint": "Leaves a blank band for a mat pressed against the glass",
    "refresh": "Panel refresh",
    "refresh_hint": "How long the picture must stay before a new bird can redraw it",
    "lookback": "Lookback",
    "lookback_hint": "How far back the frame looks",
    "save": "Save",
    "preview": "Preview",
    "rendering": "Rendering…",
    "shot_alt": "Current page",
    "analyze_title": "Audio recognition",
    "analyze_note": "Upload a recording for BirdNET analysis; results show as the latest recognition in the preview above.",
    "analyze_file": "Audio file",
    "analyze_btn": "Recognize",
    "species_on_page": "Species on the page",
    "updates": "Updates",
    "version": "Version",
    "update": "Update",
    "detector": "Detector",
    "system": "System",
    "panel": "Inky panel",
    "host": "Host",
    "network": "Network",
    "disk": "Disk",
    "started": "Started",
    "kiosk_size": "Kiosk size",
    "activity": "Activity",
    "rendered": "Last render",
    "latest": "Latest detection",
    "bird_names": "Species names",
    "show_names": "Display bird names",
    "primary_lang": "Primary language",
    "secondary_lang": "Secondary language",
    "western_font": "Western typeface",
    "chinese_font": "Chinese typeface",
    "bold": "Bold",
    "font_shared": "Secondary language shares the western typeface",
    "text_size": "Text size",
    "artwork_style": "Artwork style",
    "address": "Address",
    "credentials": "Credentials",
    "basic_auth": "(Basic Authentication)",
    "password": "Password",
    "test_connection": "Test connection",
    "check": "Check",
    "retry": "Retry",
    "install": "Install",
    "up_to_date": "up to date",
    "available": "available",
    "installing": "installing…",
    "auto_update": "Install new releases automatically",
    "auto_update_container": "Install new releases automatically <small>· disabled in container mode</small>",
    "layout": "Layout",
    "layout_spiral": "Spiral",
    "layout_spiral_blurb": "Grows outward from the middle",
    "layout_voids": "Voids",
    "layout_voids_blurb": "Fills the emptiest spot first",
    "species_limit": "Species on the page",
    "species_limit_hint": "More than {n} make the page very crowded",
    "at_most": "At most",
    "show_all": "Show all",
    "which_to_keep": "Which ones to keep",
    "species_count_aria": "How many species",
    "rank_heard": "The most heard",
    "rank_rarest": "The rarest in the window",
    "rank_rarest_ever": "The rarest ever",
    "size_small": "Small",
    "size_medium": "Medium",
    "size_large": "Large",
    "size_xlarge": "Extra large",
    "lang_sci": "Scientific",
    "lang_en": "English",
    "lang_nb": "Norwegian",
    "lang_zh": "Chinese",
    "lang_none": "None",
    "unavailable": "(unavailable)",
    "no_art": "no art",
    "none_yet": "none yet",
    "not_yet": "not yet",
    "push_failing": "panel push failing ({error})",
    "panel_detected": "detected · {size}",
    "panel_assumed": "not detected · assuming {size}",
    "online": "online",
    "offline": "offline",
    "running": "running",
    "unreachable": "unreachable",
    "connected": "connected",
    "needs_password": "needs a password",
    "detector_unreachable": "detector unreachable",
    "detector_serves_none": "detector serves none",
    "unreadable_locales": "unreadable locale list",
    "detector_answered": "detector answered {detail}",
    "no_languages": "No languages: {detail}",
    "fix_see": 'See <a href="#detector" data-tab="system">System → Detector</a>.',
    "lookback_hours": "{hours} hours",
    "refresh_at_most": "At most every {minutes} minutes",
    "refresh_0": "As soon as anything changes",
    "refresh_5": "At most every 5 minutes",
    "refresh_10": "At most every 10 minutes",
    "refresh_15": "At most every 15 minutes",
    "refresh_30": "At most every 30 minutes",
    "refresh_60": "At most every hour",
    "lookback_0.25": "Last 15 minutes",
    "lookback_0.5": "Last 30 minutes",
    "lookback_1": "Last hour",
    "lookback_3": "Last 3 hours",
    "lookback_6": "Last 6 hours",
    "lookback_12": "Last 12 hours",
    "lookback_24": "Today (24 hours)",
    "lookback_72": "Last 3 days",
    "lookback_168": "Last week",
    "lookback_720": "Last 30 days",
    "lookback_0": "All time",
    "js_testing": "testing…",
    "js_no_answer": "the frame did not answer",
    "js_preview_unavailable": "Preview unavailable",
    "js_updated": "updated to v{version}",
    "js_pick_file": "Choose an audio file first",
    "js_analyzing": "Recognizing…",
    "js_no_response": "the frame did not answer",
    "js_cannot_recognize": "Could not recognize",
    "analyze_no_file": "No file received",
    "analyze_too_large": "File too large (25 MB limit)",
    "analyze_pick_file": "Choose an audio file",
    "analyze_bad_format": "Unsupported format: {suffix}",
    "analyze_disabled": "Upload recognition is not enabled",
    "analyze_busy": "A recognition job is already running",
    "analyze_ok": "Recognized {n} species with artwork",
    "analyze_skipped": " ({n} without artwork skipped)",
    "analyze_no_art": "Birds recognized, but none have artwork in this style",
    "analyze_fail": "Could not recognize",
}

ZH: dict[str, str] = {
    "title": "Fugleramme 管理",
    "nav_kiosk": "展示页",
    "nav_birdnet_title": "检测与统计",
    "nav_docs": "文档",
    "tab_display": "显示",
    "tab_system": "系统",
    "mode": "模式",
    "mode_collage": "拼贴（默认）",
    "mode_latest": "当前最新到访",
    "mode_arrival": "首次出现",
    "resolution": "分辨率",
    "resolution_hint": "仅影响网页预览",
    "rotation": "旋转",
    "rotation_hint": "相框悬挂方向",
    "landscape": "（横向）",
    "portrait": "（纵向）",
    "margin": "边距",
    "margin_hint": "为压在屏幕上的卡纸留出空白边",
    "refresh": "墨水屏刷新",
    "refresh_hint": "画面至少保持多久后，才允许因新鸟而重绘",
    "lookback": "回看窗口",
    "lookback_hint": "相框向前看多久",
    "save": "保存",
    "preview": "预览",
    "rendering": "正在渲染…",
    "shot_alt": "当前画面",
    "analyze_title": "音频识别",
    "analyze_note": "上传录音后调用 BirdNET 分析，结果会作为最新识别显示在上方预览中。",
    "analyze_file": "音频文件",
    "analyze_btn": "开始识别",
    "species_on_page": "画面上的鸟",
    "updates": "更新",
    "version": "版本",
    "update": "更新",
    "detector": "检测器",
    "system": "系统",
    "panel": "Inky 墨水屏",
    "host": "主机",
    "network": "网络",
    "disk": "磁盘",
    "started": "启动时间",
    "kiosk_size": "展示页分辨率",
    "activity": "活动",
    "rendered": "上次渲染",
    "latest": "最近检测",
    "bird_names": "鸟类名称",
    "show_names": "显示鸟名",
    "primary_lang": "主语言",
    "secondary_lang": "第二语言",
    "western_font": "西文字体",
    "chinese_font": "中文字体",
    "bold": "加粗",
    "font_shared": "第二语言与主语言共用西文字体",
    "text_size": "字号",
    "artwork_style": "插画风格",
    "address": "地址",
    "credentials": "凭证",
    "basic_auth": "（Basic Authentication）",
    "password": "密码",
    "test_connection": "测试连接",
    "check": "检查",
    "retry": "重试",
    "install": "安装",
    "up_to_date": "已是最新",
    "available": "可用",
    "installing": "正在安装…",
    "auto_update": "自动安装新版本",
    "auto_update_container": "自动安装新版本 <small>· 容器模式下不可用</small>",
    "layout": "布局",
    "layout_spiral": "螺旋",
    "layout_spiral_blurb": "从中间向外展开",
    "layout_voids": "填空",
    "layout_voids_blurb": "优先填到最空的位置",
    "species_limit": "画面上的物种",
    "species_limit_hint": "超过 {n} 种会显得很拥挤",
    "at_most": "最多",
    "show_all": "全部显示",
    "which_to_keep": "保留哪些",
    "species_count_aria": "物种数量",
    "rank_heard": "出现最多的",
    "rank_rarest": "窗口内最稀有的",
    "rank_rarest_ever": "历史最稀有的",
    "size_small": "小",
    "size_medium": "中",
    "size_large": "大",
    "size_xlarge": "特大",
    "lang_sci": "学名",
    "lang_en": "英语",
    "lang_nb": "挪威语",
    "lang_zh": "中文",
    "lang_none": "无",
    "unavailable": "（不可用）",
    "no_art": "无插画",
    "none_yet": "暂无",
    "not_yet": "尚未渲染",
    "push_failing": "墨水屏推送失败（{error}）",
    "panel_detected": "已检测到 · {size}",
    "panel_assumed": "未检测到 · 假定 {size}",
    "online": "在线",
    "offline": "离线",
    "running": "运行中",
    "unreachable": "不可达",
    "connected": "已连接",
    "needs_password": "需要密码",
    "detector_unreachable": "检测器不可达",
    "detector_serves_none": "检测器未提供语言包",
    "unreadable_locales": "语言列表无法解析",
    "detector_answered": "检测器返回 {detail}",
    "no_languages": "无可用语言：{detail}",
    "fix_see": '请到 <a href="#detector" data-tab="system">系统 → 检测器</a> 查看。',
    "lookback_hours": "{hours} 小时",
    "refresh_at_most": "最多每 {minutes} 分钟",
    "refresh_0": "一有变化就刷新",
    "refresh_5": "最多每 5 分钟",
    "refresh_10": "最多每 10 分钟",
    "refresh_15": "最多每 15 分钟",
    "refresh_30": "最多每 30 分钟",
    "refresh_60": "最多每小时",
    "lookback_0.25": "最近 15 分钟",
    "lookback_0.5": "最近 30 分钟",
    "lookback_1": "最近 1 小时",
    "lookback_3": "最近 3 小时",
    "lookback_6": "最近 6 小时",
    "lookback_12": "最近 12 小时",
    "lookback_24": "今天（24 小时）",
    "lookback_72": "最近 3 天",
    "lookback_168": "最近一周",
    "lookback_720": "最近 30 天",
    "lookback_0": "全部时间",
    "js_testing": "测试中…",
    "js_no_answer": "服务未响应",
    "js_preview_unavailable": "预览不可用",
    "js_updated": "已更新至 v{version}",
    "js_pick_file": "请先选择音频文件",
    "js_analyzing": "识别中…",
    "js_no_response": "服务未响应",
    "js_cannot_recognize": "无法识别",
    "analyze_no_file": "未收到文件",
    "analyze_too_large": "文件过大（上限 25MB）",
    "analyze_pick_file": "请选择音频文件",
    "analyze_bad_format": "不支持的格式：{suffix}",
    "analyze_disabled": "上传识别未启用",
    "analyze_busy": "已有识别任务在进行，请稍候",
    "analyze_ok": "识别到 {n} 种有插画的鸟",
    "analyze_skipped": "（另有 {n} 种无插画已跳过）",
    "analyze_no_art": "识别到鸟类，但当前插画风格中没有对应插画",
    "analyze_fail": "无法识别",
}

_CATALOGS = {"en": EN, "zh": ZH}

_MODE_KEYS = {"collage": "mode_collage", "latest": "mode_latest", "arrival": "mode_arrival"}
_RANK_KEYS = {
    RANK_MOST_HEARD: "rank_heard",
    RANK_RAREST: "rank_rarest",
    RANK_RAREST_EVER: "rank_rarest_ever",
}
_LAYOUT_KEYS = {
    "spiral": ("layout_spiral", "layout_spiral_blurb"),
    "voids": ("layout_voids", "layout_voids_blurb"),
}
_SIZE_KEYS = {
    "small": "size_small",
    "medium": "size_medium",
    "large": "size_large",
    "xlarge": "size_xlarge",
}
_LANG_KEYS = {"sci": "lang_sci", "en": "lang_en", "nb": "lang_nb", "zh": "lang_zh", "": "lang_none"}
_FAILURE_KEYS = {
    NEEDS_PASSWORD: "needs_password",
    "detector unreachable": "detector_unreachable",
    "detector serves none": "detector_serves_none",
    "unreadable locale list": "unreadable_locales",
}


@dataclass(frozen=True)
class UI:
    code: str = "en"

    def __post_init__(self) -> None:
        if self.code not in _CATALOGS:
            object.__setattr__(self, "code", "en")

    @property
    def html_lang(self) -> str:
        return HTML_LANG[self.code]

    def t(self, key: str, **kwargs: object) -> str:
        catalog = _CATALOGS[self.code]
        text = catalog.get(key) or EN.get(key) or key
        return text.format(**kwargs) if kwargs else text

    def mode(self, key: str, fallback: str = "") -> str:
        mk = _MODE_KEYS.get(key)
        return self.t(mk) if mk else (fallback or key)

    def ranking(self, key: str, fallback: str = "") -> str:
        return self.t(_RANK_KEYS[key]) if key in _RANK_KEYS else fallback or key

    def layout(self, key: str) -> tuple[str, str]:
        label_key, blurb_key = _LAYOUT_KEYS.get(key, ("", ""))
        return self.t(label_key), self.t(blurb_key)

    def label_size(self, key: str, fallback: str = "") -> str:
        return self.t(_SIZE_KEYS[key]) if key in _SIZE_KEYS else fallback or key

    def language_name(self, code: str, fallback: str = "") -> str:
        return self.t(_LANG_KEYS[code]) if code in _LANG_KEYS else (fallback or code)

    def aspect(self, rotation_mod: int) -> str:
        return self.t("portrait" if rotation_mod else "landscape")

    def failure(self, text: str) -> str:
        if text in _FAILURE_KEYS:
            return self.t(_FAILURE_KEYS[text])
        if text.startswith("detector answered "):
            return self.t("detector_answered", detail=text.removeprefix("detector answered "))
        return text

    def lookback_hours(self, hours: float) -> str:
        key = f"lookback_{hours:g}" if hours != int(hours) else f"lookback_{int(hours)}"
        # 0.25 / 0.5 need the float form used above; also try exact dict keys.
        for candidate in (f"lookback_{hours}", f"lookback_{hours:g}", key):
            if candidate in EN:
                return self.t(candidate)
        return self.t("lookback_hours", hours=hours)

    def refresh_minutes(self, minutes: int) -> str:
        key = f"refresh_{minutes}"
        if key in EN:
            return self.t(key)
        return self.t("refresh_at_most", minutes=minutes)


_current: contextvars.ContextVar[UI] = contextvars.ContextVar("admin_ui", default=UI("en"))


def get() -> UI:
    return _current.get()


def use(ui: UI) -> contextvars.Token[UI]:
    return _current.set(ui)


def t(key: str, **kwargs: object) -> str:
    return get().t(key, **kwargs)


def negotiate(cookie: str | None = None, accept_language: str | None = None) -> str:
    """Pick en/zh: explicit cookie first, then Accept-Language, else English."""
    if cookie in LOCALES:
        return cookie  # type: ignore[return-value]
    for tag, _q in _parse_accept(accept_language or ""):
        primary = tag.split("-", 1)[0].lower()
        if primary == "zh":
            return "zh"
        if primary == "en":
            return "en"
    return "en"


def _parse_accept(header: str) -> list[tuple[str, float]]:
    parts: list[tuple[str, float]] = []
    for chunk in header.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ";q=" in chunk:
            tag, _, rest = chunk.partition(";q=")
            try:
                q = float(re.split(r"[;,\s]", rest, maxsplit=1)[0])
            except ValueError:
                q = 0.0
        else:
            tag, q = chunk, 1.0
        parts.append((tag.strip().lower(), q))
    parts.sort(key=lambda item: -item[1])
    return parts


def parse_cookie(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            return value.strip() or None
    return None
