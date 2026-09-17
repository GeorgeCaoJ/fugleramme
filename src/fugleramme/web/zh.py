"""Fixed Chinese UI copy for the admin page.

Bird names still come from BirdNET-Go dictionaries (`zh`); this module only
covers the admin chrome itself.
"""

from __future__ import annotations

from ..render.collage import RANK_MOST_HEARD, RANK_RAREST, RANK_RAREST_EVER
from ..source import NEEDS_PASSWORD

# Mode radio labels (keys match modes.MODES).
MODES = {
    "collage": "拼贴（默认）",
    "latest": "最新一只",
    "arrival": "最新到访",
}

LOOKBACK = {
    0.25: "最近 15 分钟",
    0.5: "最近 30 分钟",
    1: "最近 1 小时",
    3: "最近 3 小时",
    6: "最近 6 小时",
    12: "最近 12 小时",
    24: "今天（24 小时）",
    72: "最近 3 天",
    168: "最近一周",
    720: "最近 30 天",
    0: "全部时间",
}

REFRESH = {
    0: "一有变化就刷新",
    5: "最多每 5 分钟",
    10: "最多每 10 分钟",
    15: "最多每 15 分钟",
    30: "最多每 30 分钟",
    60: "最多每小时",
}

RANKINGS = {
    RANK_MOST_HEARD: "出现最多的",
    RANK_RAREST: "窗口内最稀有的",
    RANK_RAREST_EVER: "历史最稀有的",
}

LAYOUTS = {
    "spiral": ("螺旋", "从中间向外展开"),
    "voids": ("填空", "优先填到最空的位置"),
}

LABEL_SIZES = {
    "small": "小",
    "medium": "中",
    "large": "大",
    "xlarge": "特大",
}

# Language codes as shown in the admin dropdown.
LANGUAGES = {
    "sci": "学名",
    "en": "英语",
    "nb": "挪威语",
    "zh": "中文",
    "": "无",
}

ASPECT = {0: "（横向）", 90: "（纵向）"}

# Detector / outage fragments returned by probe / catalog_failure.
FAILURES = {
    NEEDS_PASSWORD: "需要密码",
    "detector unreachable": "检测器不可达",
    "detector serves none": "检测器未提供语言包",
    "unreadable locale list": "语言列表无法解析",
}


def failure(text: str) -> str:
    if text in FAILURES:
        return FAILURES[text]
    if text.startswith("detector answered "):
        return "检测器返回 " + text.removeprefix("detector answered ")
    return text


def language_name(code: str, fallback: str = "") -> str:
    return LANGUAGES.get(code) or fallback or code


def lookback_hours(hours: float) -> str:
    return LOOKBACK.get(hours, f"{hours} 小时")


def refresh_minutes(minutes: int) -> str:
    return REFRESH.get(minutes, f"最多每 {minutes} 分钟")
