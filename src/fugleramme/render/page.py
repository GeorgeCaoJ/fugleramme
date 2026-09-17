"""Page furniture shared by every display mode.

Getting an asset and a piece of text onto paper is the same job whether the page
holds forty birds or one, so the collage and the plate draw from here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import fonts
from .paper import TARGET_PAPER, paper_texture, process_sprite

INK = (30, 30, 30)
PANEL_INK = (0, 0, 0)  # exact palette black: the dither leaves it alone

MIN_LABEL_PX = 11
_CUTOFF = 110  # alpha threshold when flattening text for the panel
_LINE_SPACING = 0.1  # extra leading between a label's two lines, em
_PERCH_FILL = 0.7  # of the page's short side


def label_px(width: int, height: int, size_key: str) -> int:
    _name, scale = fonts.LABEL_SIZES.get(size_key, fonts.LABEL_SIZES[fonts.DEFAULT_LABEL_SIZE])
    return max(MIN_LABEL_PX, round(min(width, height) * scale))


def trim(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # trim by alpha, not by RGB
    return img.crop(bbox) if bbox else img


def fit(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale to fit inside `box`, keeping the aspect."""
    scale = min(box[0] / img.width, box[1] / img.height)
    return img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.Resampling.LANCZOS,
    )


def text_mask(
    text: str,
    font: ImageFont.FreeTypeFont,
    flat: bool,
    cjk_font: ImageFont.FreeTypeFont | None = None,
) -> Image.Image:
    """Text as an "L" alpha mask, +1px so the italic's overhang is not shaved.
    Newlines stack centred (a second language) on the text layout's own
    baselines - separately trimmed masks would sit unevenly. Flat drops the
    antialiasing, which would otherwise dither into colour speckle.

    When `cjk_font` is set, ideographs use that face and everything else keeps
    `font` - needed because the label italics have no CJK glyphs and the CJK
    fallback has no Latin letters or ASCII digits.
    """
    if cjk_font is not None and fonts.needs_cjk(text):
        mask = _mixed_text_mask(text, font, cjk_font)
    else:
        spacing = round(font.size * _LINE_SPACING)
        measure = ImageDraw.Draw(Image.new("L", (1, 1)))
        x0, y0, x1, y1 = measure.multiline_textbbox(
            (0, 0), text, font=font, spacing=spacing, align="center"
        )
        # Ceil: a multi-line bbox is fractional, and a short box shaves the text.
        mask = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(y1 - y0) + 2), 0)
        ImageDraw.Draw(mask).multiline_text(
            (1 - x0, 1 - y0), text, font=font, fill=255, spacing=spacing, align="center"
        )
    return mask.point(lambda v: 255 if v > _CUTOFF else 0) if flat else mask


def label_mask(
    text: str,
    font_key: str,
    size: int,
    flat: bool,
    cjk_font_key: str = fonts.DEFAULT_CJK_FONT,
    cjk_bold: bool = False,
) -> Image.Image:
    """Species-label mask: Latin face for Western text, Chinese face for ideographs."""
    latin, cjk = fonts.faces(font_key, cjk_font_key, size, text, cjk_bold)
    return text_mask(text, latin, flat, cjk_font=cjk)


def _script_runs(line: str) -> list[tuple[str, bool]]:
    """Split a line into `(text, use_cjk)` runs so each face draws what it can."""
    if not line:
        return [("", False)]
    runs: list[tuple[str, bool]] = []
    buf = line[0]
    flag = fonts.is_cjk(line[0])
    for ch in line[1:]:
        next_flag = fonts.is_cjk(ch)
        if next_flag != flag:
            runs.append((buf, flag))
            buf, flag = ch, next_flag
        else:
            buf += ch
    runs.append((buf, flag))
    return runs


def _single_line_mask(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """One line with the same ink-bbox padding as the single-font path.

    Italics overhang their advance width; measuring by ink (not getlength) keeps
    a dual-language Latin line identical to sci-only Gentium.
    """
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = measure.textbbox((0, 0), text, font=font)
    mask = Image.new("L", (max(1, math.ceil(x1 - x0) + 2), max(1, math.ceil(y1 - y0) + 2)), 0)
    ImageDraw.Draw(mask).text((1 - x0, 1 - y0), text, font=font, fill=255)
    return mask


def _run_glyph(
    text: str, font: ImageFont.FreeTypeFont
) -> tuple[Image.Image, int, int, int]:
    """`(mask, ascent, descent, advance)` for a single-script run on a mixed line.

    The mask includes italic ink overhangs; `advance` is the pen step to the next
    run so neighbouring scripts still sit on the right letter spacing.
    """
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = measure.textbbox((0, 0), text, font=font, anchor="ls")
    ascent = max(0, math.ceil(-y0))
    descent = max(0, math.ceil(y1))
    left = math.floor(x0)  # negative when the italic leans left of the pen
    right = math.ceil(x1)
    mask = Image.new("L", (max(1, right - left), max(1, ascent + descent)), 0)
    ImageDraw.Draw(mask).text((-left, ascent), text, font=font, fill=255, anchor="ls")
    advance = max(1, math.ceil(font.getlength(text)))
    return mask, ascent, descent, advance


def _mixed_line_mask(
    line: str, latin: ImageFont.FreeTypeFont, cjk: ImageFont.FreeTypeFont
) -> Image.Image:
    """One line that may mix scripts. A single-script line uses the same path as
    sci-only; a mixed line (e.g. a Chinese date) composes runs on one baseline."""
    runs = _script_runs(line)
    if len(runs) == 1:
        run, use_cjk = runs[0]
        return _single_line_mask(run, cjk if use_cjk else latin)

    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    pieces: list[tuple[Image.Image, int, int, int, int]] = []
    for run, use_cjk in runs:
        font = cjk if use_cjk else latin
        mask, ascent, descent, advance = _run_glyph(run, font)
        rx0, _ry0, _rx1, _ry1 = measure.textbbox((0, 0), run, font=font, anchor="ls")
        ink_left = -math.floor(rx0) if rx0 < 0 else 0
        pieces.append((mask, ascent, descent, advance, ink_left))

    ascent = max((a for _m, a, _d, _adv, _il in pieces), default=0)
    descent = max((d for _m, _a, d, _adv, _il in pieces), default=0)
    origin = pieces[0][4]  # first run's left overhang before the pen
    advances = sum(adv for _m, _a, _d, adv, _il in pieces)
    last_mask, _la, _ld, _ladv, last_ink = pieces[-1]
    width = max(
        origin + advances,
        origin + advances - pieces[-1][3] + last_mask.width - last_ink,
    )
    row = Image.new("L", (max(1, width), max(1, ascent + descent)), 0)
    pen = origin
    for mask, run_ascent, _run_descent, advance, ink_left in pieces:
        row.paste(mask, (pen - ink_left, ascent - run_ascent), mask)
        pen += advance
    return row


def _mixed_text_mask(
    text: str, latin: ImageFont.FreeTypeFont, cjk: ImageFont.FreeTypeFont
) -> Image.Image:
    """Compose a multiline mask using the Latin face for non-ideographs and the
    CJK face for ideographs. Pure-Latin lines match the sci-only Gentium path."""
    spacing = round(latin.size * _LINE_SPACING)
    line_masks = [_mixed_line_mask(line, latin, cjk) for line in text.split("\n")]

    width = max((m.width for m in line_masks), default=1)
    height = sum(m.height for m in line_masks) + spacing * max(0, len(line_masks) - 1)
    out = Image.new("L", (width + 2, max(1, height) + 2), 0)
    y = 1
    for mask in line_masks:
        out.paste(mask, (1 + (width - mask.width) // 2, y), mask)
        y += mask.height + spacing
    return out


def stamp(canvas: Image.Image, mask: Image.Image, at: tuple[int, int], textured: bool) -> None:
    canvas.paste(Image.new("RGB", mask.size, INK if textured else PANEL_INK), at, mask)


def day_ordinal() -> int:
    """Today as a number that turns over daily.

    The panel and the kiosk each render their own copy, so a day-varying choice
    rolled at render time would leave them showing different pages - and the
    panel, which only re-renders when its key changes, would then hold its one
    roll for as long as the frame stayed quiet. Deriving it from the date makes
    both agree by construction and gives a silent frame something that moves.
    """
    return date.today().toordinal()


def draw_perch(
    canvas: Image.Image, perches: Sequence[Path], day: int, textured: bool = True
) -> None:
    """Nothing to show: a single empty perch, centered on the paper page."""
    if not perches:
        return
    perch = trim(perches[day % len(perches)])
    if (day // len(perches)) % 2:  # mirrored on the second lap, so it cycles twice as far
        perch = perch.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    target = int(min(canvas.width, canvas.height) * _PERCH_FILL)
    proc = process_sprite(fit(perch, (target, target)), textured=textured)
    canvas.paste(proc, ((canvas.width - proc.width) // 2, (canvas.height - proc.height) // 2), proc)


def blank(resolution: tuple[int, int], textured: bool) -> Image.Image:
    """An empty sheet: grained for the web, flat for the panel, whose dither
    would otherwise turn the grain into noise."""
    width, height = resolution
    if textured:
        return paper_texture(width, height)
    return Image.new("RGB", (width, height), TARGET_PAPER)
