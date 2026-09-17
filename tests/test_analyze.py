"""BirdNET-Go Raven table parsing and overlay behaviour."""

from __future__ import annotations

from datetime import datetime, timezone

from fugleramme.analyze import parse_raven_table
from fugleramme.overlay import UploadOverlay
from fugleramme.source import Detection


RAVEN = """\
Selection\tView\tChannel\tBegin File\tBegin Time (s)\tEnd Time (s)\tLow Freq (Hz)\tHigh Freq (Hz)\tSpecies Code\tCommon Name\tConfidence
1\tSpectrogram 1\t1\tsound.wav\t0.0\t3.0\t0\t15000\teurbla\tEurasian Blackbird\t0.9016
2\tSpectrogram 1\t1\tsound.wav\t3.0\t6.0\t0\t15000\tgretit\tGreat Tit\t0.2293
3\tSpectrogram 1\t1\tsound.wav\t6.0\t9.0\t0\t15000\teng\tEngine\t0.8000
"""


def test_raven_table_keeps_birds_above_threshold():
    hits = parse_raven_table(RAVEN, now=datetime(2026, 1, 1, tzinfo=timezone.utc), threshold=0.3)
    names = {d.scientific_name for d in hits}
    assert "Turdus merula" in names  # Eurasian Blackbird
    assert "Parus major" not in names  # 0.229 below 0.3
    assert all("Engine" not in d.scientific_name for d in hits)


def test_raven_table_empty_means_no_birds():
    assert parse_raven_table("Selection\tConfidence\n", threshold=0.3) == []


class _Stub:
    base_url = "http://detector"

    def latest(self):
        return None

    def recent(self, limit=20):
        return [
            Detection(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "Pica pica", 0.5, None)
        ]

    def species_since(self, hours=24):
        return [("Pica pica", 2)]

    def life_list(self):
        return []

    def stats(self):
        return {}

    def close(self):
        pass


def test_overlay_prefers_upload_hits():
    overlay = UploadOverlay(_Stub())
    hit = Detection(-1, datetime(2026, 6, 1, tzinfo=timezone.utc), "Turdus merula", 0.9, None)
    other = Detection(-2, datetime(2026, 6, 1, tzinfo=timezone.utc), "Parus major", 0.8, None)
    overlay.set_upload([hit, other])
    assert overlay.latest() is hit or overlay.latest() is other
    assert overlay.latest_upload() is not None
    # Upload session is about these birds alone - not merged with the stub's Pica.
    assert {n for n, _ in overlay.species_since(24)} == {"Turdus merula", "Parus major"}
    assert len(overlay.recent(5)) == 2
    overlay.clear()
    assert overlay.latest() is None
    assert overlay.latest_upload() is None
    assert overlay.species_since(24) == [("Pica pica", 2)]


def test_drawable_filter_keeps_only_species_with_art(tmp_path):
    from fugleramme.names import drawable_keys, normalize

    birds = tmp_path / "classic" / "birds"
    birds.mkdir(parents=True)
    (birds / "poecile-atricapillus.webp").write_bytes(b"x")
    keys = drawable_keys(tmp_path, "classic")
    assert normalize("Poecile atricapillus") in keys
    assert normalize("Clamator coromandus") not in keys


def test_chinese_of_covers_species_missing_from_fake_dict():
    from fugleramme.taxa import chinese_of

    assert chinese_of("Cyanocitta cristata") == "冠蓝鸦"
    assert chinese_of("Turdus merula")  # BirdNET zh label (欧乌鸫)
