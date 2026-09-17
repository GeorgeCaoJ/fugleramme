"""Deprecated: admin chrome copy lives in `i18n`. Kept as a thin re-export."""

from __future__ import annotations

from ..source import NEEDS_PASSWORD
from .i18n import UI

# Legacy helpers used by older tests/imports.
_ui = UI("zh")

MODES = {k: _ui.mode(k) for k in ("collage", "latest", "arrival")}
ASPECT = {0: _ui.aspect(0), 90: _ui.aspect(90)}
LABEL_SIZES = {k: _ui.label_size(k) for k in ("small", "medium", "large", "xlarge")}
LANGUAGES = {k: _ui.language_name(k) for k in ("sci", "en", "nb", "zh", "")}
FAILURES = {
    NEEDS_PASSWORD: _ui.t("needs_password"),
    "detector unreachable": _ui.t("detector_unreachable"),
    "detector serves none": _ui.t("detector_serves_none"),
    "unreadable locale list": _ui.t("unreadable_locales"),
}


def failure(text: str) -> str:
    return _ui.failure(text)


def language_name(code: str, fallback: str = "") -> str:
    return _ui.language_name(code, fallback)


def lookback_hours(hours: float) -> str:
    return _ui.lookback_hours(hours)


def refresh_minutes(minutes: int) -> str:
    return _ui.refresh_minutes(minutes)
