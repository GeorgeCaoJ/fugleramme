"""Which detections are birds.

A station classifies more than birds, and can run a bat or multi-taxa model beside
the one that hears them. Two halves, because there are two ways to not be a bird:

The v2.4 label set is an allowlist, and that is what catches a bat whatever its
genus - artwork filenames are pinned to those labels, so a name outside the set
could never be drawn anyway.

`NON_BIRD_GENERA` covers the 101 labels inside v2.4 that are noise classes, frogs,
crickets, squirrels and other mammals. It was read off eBird's own taxonomy, which
prefixes a non-bird taxon's species code with `t-`, and cross-checked against
BirdNET-Go's genus map, which disagreed nowhere.

An unreadable label file fails open: the odd frog on the glass beats a blank one.
"""

from __future__ import annotations

import logging
from functools import cache

from .config import REPO_ROOT
from .names import normalize

log = logging.getLogger(__name__)

LABELS = REPO_ROOT / "assets" / "birdnet_labels_v2.4.txt"
# BirdNET v2.4 Chinese common names (Sci_中文), used when the detector's zh
# dictionary is missing a species - e.g. the fake detector's short list.
LABELS_ZH = REPO_ROOT / "assets" / "birdnet_labels_zh.txt"

# Both spellings where a species has been reclassified, since `normalize` hands
# over the current one: the label file says "Orocharis saltator", the detector
# says "Hapithus saltator". "human" and "power" are two-word noise labels
# ("Human vocal", "Power tools"), which read as a genus like any other.
_GENERA = """
dog engine environmental fireworks gun human noise power siren
acris anaxyrus dryophytes eleutherodactylus gastrophryne hyliola incilius
lithobates pseudacris scaphiopus spea
allonemobius amblycorypha anaxipha apis atlanticus conocephalus cyrtoxipha
eunemobius gryllus hapithus microcentrum miogryllus neoconocephalus neonemobius
oecanthus orchelimum orocharis phyllopalpus pterophylla scudderia
alouatta canis odocoileus sciurus tamias tamiasciurus
"""

NON_BIRD_GENERA = frozenset(_GENERA.split())


@cache
def _label_rows() -> list[tuple[str, str]]:
    """`(scientific, common)` rows as written in the v2.4 label file."""
    try:
        text = LABELS.read_text()
    except OSError as error:
        log.warning("No label list at %s (%s): only the genus check applies", LABELS, error)
        return []
    rows = []
    for line in text.splitlines():
        if not line:
            continue
        scientific, _, common = line.partition("_")
        rows.append((scientific, common))
    return rows


@cache
def _labels() -> dict[str, str]:
    """Every v2.4 name as an artwork key, against the common name beside it in the
    file, so a reclassified species answers to the label's spelling and the
    detector's alike. Empty if the file cannot be read, which turns the allowlist
    off rather than emptying the page."""
    return {normalize(scientific): common for scientific, common in _label_rows()}


def common_of(scientific_name: str) -> str:
    """The label's own English common name, or "" for a name v2.4 never emitted.
    Needs no detector and no dictionary, unlike every other name here."""
    return _labels().get(normalize(scientific_name), "")


@cache
def scientific_of_common(common_name: str) -> str:
    """Reverse of `common_of`: English common → scientific, or "" if unknown.

    BirdNET-Go's Raven file table often carries Common Name without Scientific
    Name; upload analysis needs this to map back onto artwork keys.
    """
    want = common_name.strip().lower()
    if not want:
        return ""
    for scientific, common in _label_rows():
        if common.lower() == want:
            return scientific
    return ""


@cache
def _zh_names() -> dict[str, str]:
    """Scientific → Chinese common name from the vendored BirdNET zh label file."""
    try:
        text = LABELS_ZH.read_text(encoding="utf-8")
    except OSError as error:
        log.warning("No Chinese label list at %s (%s)", LABELS_ZH, error)
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or "_" not in line:
            continue
        scientific, _, chinese = line.partition("_")
        if scientific and chinese:
            out[scientific] = chinese
    return out


def chinese_of(scientific_name: str) -> str:
    """Chinese common name for a BirdNET species, or "" if unknown."""
    names = _zh_names()
    if scientific_name in names:
        return names[scientific_name]
    # Tolerant of spelling variants the English label file already normalizes.
    return names.get(next((s for s in names if normalize(s) == normalize(scientific_name)), ""), "")


def is_bird(scientific_name: str) -> bool:
    key = normalize(scientific_name)
    known = _labels()
    if known and key not in known:
        return False  # another model's label: nothing here can draw it
    return key.partition("-")[0] not in NON_BIRD_GENERA
