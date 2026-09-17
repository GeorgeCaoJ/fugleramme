"""Vendored typefaces for the species names on the page.

Latin italics (scientific names are conventionally italic) span old-style,
Didone, calligraphic, transitional and slab, picked for how they survive the
panel's six colors. Chinese has its own faces - a Song serif and a Kai -
because those italics have no ideographs, and a CJK-only fallback has no Latin
letters or ASCII digits. Mixed labels are drawn with both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from PIL import ImageFont

from ..config import REPO_ROOT

FONTS_DIR = REPO_ROOT / "assets" / "fonts"

# Latin label faces: key -> (admin label, file under FONTS_DIR)
FONTS: dict[str, tuple[str, str]] = {
    "gentium": ("Gentium Book Plus", "gentiumbookplus/GentiumBookPlus-Italic.ttf"),
    "garamond": ("EB Garamond", "ebgaramond/EBGaramond-Italic.ttf"),
    "cormorant": ("Cormorant Garamond", "cormorantgaramond/CormorantGaramond-Italic.ttf"),
    "baskerville": ("Libre Baskerville", "librebaskerville/LibreBaskerville-Italic.ttf"),
    "playfair": ("Playfair Display", "playfairdisplay/PlayfairDisplay-Italic.ttf"),
    "alegreya": ("Alegreya", "alegreya/Alegreya-Italic.ttf"),
    "bitter": ("Bitter", "bitter/Bitter-Italic.ttf"),
}

DEFAULT_FONT = "gentium"

# Chinese faces: key -> (admin label, regular file, bold/heavy file or "")
CJK_FONTS: dict[str, tuple[str, str, str]] = {
    "song": (
        "思源宋体",
        "notoserifcjk/NotoSerifCJKsc-Regular.otf",
        "notoserifcjk/NotoSerifCJKsc-Bold.otf",
    ),
    "wenkai": (
        "霞鹜文楷",
        "lxgwwenkai/LXGWWenKai-Regular.ttf",
        "lxgwwenkai/LXGWWenKai-Medium.ttf",  # no Bold cut; Medium is the heavy option
    ),
}

DEFAULT_CJK_FONT = "song"

# Last-resort ideograph face when a configured CJK file is missing.
_CJK_FALLBACK = "droidsansfallback/DroidSansFallback.ttf"
_SYSTEM_CJK = (
    "/usr/share/fonts/google-droid-fonts/DroidSansFallback.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)

# Fraction of the page's short side, so a name holds its proportion at any resolution.
LABEL_SIZES: dict[str, tuple[str, float]] = {
    "small": ("Small", 0.024),
    "medium": ("Medium", 0.032),
    "large": ("Large", 0.042),
    "xlarge": ("Extra large", 0.055),
}

DEFAULT_LABEL_SIZE = "medium"


def is_cjk(ch: str) -> bool:
    """True for a CJK ideograph (not Latin, digits, or punctuation)."""
    return (
        "\u3400" <= ch <= "\u4dbf"  # CJK Extension A
        or "\u4e00" <= ch <= "\u9fff"  # CJK Unified
        or "\uf900" <= ch <= "\ufaff"  # CJK Compatibility
    )


def needs_cjk(text: str) -> bool:
    """True when `text` contains any CJK ideograph."""
    return any(is_cjk(ch) for ch in text)


def is_cjk_language(code: str) -> bool:
    """True when a language code draws ideographs (Chinese)."""
    return code == "zh"


def load(key: str, size: int) -> ImageFont.FreeTypeFont:
    """Open a Latin label font at a pixel size. Uncached on purpose: the render
    loop and the HTTP server draw on separate threads, and a FreeType face is
    not shareable."""
    _name, filename = FONTS.get(key, FONTS[DEFAULT_FONT])
    font = ImageFont.truetype(str(FONTS_DIR / filename), size)
    _pin_weight(font)
    return font


def load_cjk(key: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Open a Chinese label font. `bold` picks the heavy cut when present."""
    ordered: list[Path] = []
    entry = CJK_FONTS.get(key) or CJK_FONTS[DEFAULT_CJK_FONT]
    _label, regular, heavy = entry
    if bold and heavy:
        ordered.append(FONTS_DIR / heavy)
    ordered.append(FONTS_DIR / regular)
    for alt_key, (_lab, alt_reg, alt_heavy) in CJK_FONTS.items():
        if alt_key == key:
            continue
        if bold and alt_heavy:
            ordered.append(FONTS_DIR / alt_heavy)
        ordered.append(FONTS_DIR / alt_reg)
    ordered.append(FONTS_DIR / _CJK_FALLBACK)
    ordered.extend(Path(p) for p in _SYSTEM_CJK)
    for path in ordered:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return load(DEFAULT_FONT, size)


def faces(
    latin_key: str, cjk_key: str, size: int, text: str, cjk_bold: bool = False
) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont | None]:
    """`(latin, cjk_or_none)` for drawing `text`. CJK is loaded only when needed."""
    latin = load(latin_key, size)
    return latin, load_cjk(cjk_key, size, cjk_bold) if needs_cjk(text) else None


def _pin_weight(font: ImageFont.FreeTypeFont) -> None:
    """Pillow instantiates a variable font at each axis's minimum, which would
    draw Bitter as Thin."""
    try:
        # Pillow's Axis marks every field optional; FreeType fills them.
        axes = cast(list[dict[str, Any]], font.get_variation_axes())
    except OSError:
        return  # static font
    values = []
    for axis in axes:
        name = axis["name"]
        want = (
            400
            if (name.decode() if isinstance(name, bytes) else name) == "Weight"
            else axis["default"]
        )
        values.append(max(axis["minimum"], min(axis["maximum"], want)))
    font.set_variation_by_axes(values)
