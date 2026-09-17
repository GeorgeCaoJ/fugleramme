"""Run BirdNET-Go file analysis and turn the Raven table into detections.

BirdNET-Go has no HTTP upload-analyze API; the `file` subcommand is the
supported offline path and uses the same model as realtime. Results are then
injected via `UploadOverlay` so the existing preview pipeline can draw them.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .source import Detection
from .taxa import is_bird, scientific_of_common

log = logging.getLogger(__name__)

# Vendored tools live under the repo's .tools/ (gitignored).
_TOOLS = Path(__file__).resolve().parents[2] / ".tools"
_BIRDNET_GO_DIR = _TOOLS / "birdnet-go"
_BIRDA_DIR = _TOOLS / "birda"

DEFAULT_THRESHOLD = 0.3
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".webm",
    ".m4a",
    ".aac",
    ".wma",
    ".aiff",
    ".aif",
}

# Docker image used to run birda when the host glibc is too old.
BIRDA_DOCKER_IMAGE = os.environ.get("BIRDA_DOCKER_IMAGE", "ubuntu:24.04")

# Negative ids so overlay hits never collide with BirdNET-Go's positive note ids.
_NEXT_ID = -1


class AnalyzeError(Exception):
    """User-facing failure: missing binary, bad audio, or a failed run."""


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def birdnet_bin() -> Path | None:
    """Resolve a BirdNET-Go binary (legacy `file` subcommand), if present."""
    env = os.environ.get("BIRDNET_GO_BIN", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    for name in ("birdnet-go", "birdnet"):
        found = shutil.which(name)
        if found:
            return Path(found)
    candidate = _BIRDNET_GO_DIR / "birdnet-go"
    return candidate if _executable(candidate) else None


def birda_bin() -> Path | None:
    """Resolve birda (official offline analyzer, same BirdNET models)."""
    env = os.environ.get("BIRDA_BIN", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    found = shutil.which("birda")
    if found:
        return Path(found)
    candidate = _BIRDA_DIR / "birda"
    return candidate if candidate.is_file() else None


def docker_bin() -> str | None:
    return shutil.which("docker")


def parse_raven_table(text: str, *, now: datetime | None = None, threshold: float = DEFAULT_THRESHOLD) -> list[Detection]:
    """Parse BirdNET-Go / Raven selection-table output into bird detections.

    Rows below `threshold`, or non-birds, are dropped. Multiple hits for one
    species collapse to the highest-confidence row (still one Detection each
    species, newest-first by begin time).
    """
    global _NEXT_ID
    now = now or datetime.now().astimezone()
    # Raven tables are tab-separated; some builds emit spaces. csv handles both
    # when we sniff for a delimiter, but tabs are the documented default.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    sample = lines[0]
    delim = "\t" if "\t" in sample else ","
    reader = csv.DictReader(lines, delimiter=delim)
    if not reader.fieldnames:
        return []

    def col(*names: str) -> str | None:
        lower = {f.lower(): f for f in reader.fieldnames or []}
        for name in names:
            if name.lower() in lower:
                return lower[name.lower()]
        return None

    sci_key = col("Scientific Name", "scientific_name", "ScientificName")
    common_key = col("Common Name", "common_name", "CommonName")
    conf_key = col("Confidence", "confidence")
    begin_key = col("Begin Time (s)", "Begin Time", "start_s", "Start (s)")

    best: dict[str, tuple[float, float, str]] = {}  # sci -> (conf, begin, common)
    for row in reader:
        try:
            conf = float((row.get(conf_key) or "0").strip())
        except (TypeError, ValueError):
            continue
        if conf < threshold:
            continue
        scientific = (row.get(sci_key) or "").strip()
        common = (row.get(common_key) or "").strip()
        if not scientific and common:
            scientific = scientific_of_common(common)
        if not scientific or not is_bird(scientific):
            continue
        try:
            begin = float((row.get(begin_key) or "0").strip())
        except (TypeError, ValueError):
            begin = 0.0
        prev = best.get(scientific)
        if prev is None or conf > prev[0]:
            best[scientific] = (conf, begin, common)

    ordered = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))
    out: list[Detection] = []
    for scientific, (conf, begin, _common) in ordered:
        _NEXT_ID -= 1
        out.append(
            Detection(
                id=_NEXT_ID,
                detected_at=now - timedelta(seconds=max(0.0, begin)),
                scientific_name=scientific,
                confidence=conf,
                clip_path=None,
            )
        )
    # Newest first for latest()/recent().
    out.sort(key=lambda d: d.detected_at, reverse=True)
    return out


def _find_result_table(audio: Path, cwd: Path) -> Path | None:
    """Locate Raven/CSV output written next to `audio` or under cwd."""
    stem = audio.name
    candidates = [
        cwd / "output" / f"{stem}.txt",
        cwd / "output" / f"{audio.stem}.txt",
        audio.with_suffix(audio.suffix + ".txt"),
        audio.with_suffix(".txt"),
        cwd / f"{audio.stem}.BirdNET.results.csv",
        audio.with_name(f"{audio.stem}.BirdNET.results.csv"),
        cwd / f"{stem}.txt",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for pattern in ("*.BirdNET.results.csv", "*.txt"):
        hits = sorted(cwd.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    return None


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    log.info("Running %s", " ".join(cmd))
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
    except FileNotFoundError as exc:
        raise AnalyzeError(f"无法启动分析工具：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalyzeError("识别超时，请换更短的音频再试。") from exc


def _to_wav(audio: Path, dest_dir: Path, *, timeout: int = 120) -> Path:
    """Transcode any supported upload to 48 kHz mono PCM WAV for BirdNET/birda.

    Browser recordings are often webm/opus; birda rejects those with
    \"no valid audio files\". WAV at 48 kHz is what BirdNET expects.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        if audio.suffix.lower() == ".wav":
            out = dest_dir / "audio.wav"
            shutil.copy2(audio, out)
            return out
        raise AnalyzeError("需要 ffmpeg 将音频转为 WAV，请先安装 ffmpeg。")

    out = dest_dir / "audio.wav"
    # -y overwrite; mono; 48 kHz; 16-bit PCM - BirdNET's preferred input.
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(audio),
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    proc = _run(cmd, cwd=dest_dir, env=os.environ.copy(), timeout=timeout)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 44:
        detail = (proc.stderr or proc.stdout or "").strip()[-300:]
        raise AnalyzeError(f"音频转 WAV 失败。{detail}")
    return out


def _detections_from_proc(
    proc: subprocess.CompletedProcess[str], local: Path, cwd: Path, threshold: float
) -> list[Detection]:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise AnalyzeError(f"分析失败（退出码 {proc.returncode}）。{detail}")
    table = _find_result_table(local, cwd)
    if table is not None:
        text = table.read_text(encoding="utf-8", errors="replace")
        # CSV from birda may start with a UTF-8 BOM.
        text = text.lstrip("\ufeff")
        detections = parse_raven_table(text, threshold=threshold)
        if detections:
            return detections
        raise AnalyzeError("无法识别")
    stdout = proc.stdout or ""
    if "Confidence" in stdout or "confidence" in stdout.lower():
        detections = parse_raven_table(stdout, threshold=threshold)
        if detections:
            return detections
    raise AnalyzeError("无法识别")


def _analyze_with_birdnet_go(
    wav: Path, binary: Path, threshold: float, timeout: int, work: Path
) -> list[Detection]:
    env = os.environ.copy()
    lib_dir = str(binary.resolve().parent)
    env["LD_LIBRARY_PATH"] = lib_dir + (
        os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    proc = _run(
        [str(binary), "file", str(wav), "--threshold", str(threshold)],
        cwd=work,
        env=env,
        timeout=timeout,
    )
    return _detections_from_proc(proc, wav, work, threshold)


def _analyze_with_birda_native(
    wav: Path, binary: Path, threshold: float, timeout: int, work: Path
) -> list[Detection]:
    env = os.environ.copy()
    lib_dir = str(binary.resolve().parent)
    env["LD_LIBRARY_PATH"] = lib_dir + (
        os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    proc = _run(
        [str(binary), "-c", str(threshold), "-f", "csv", "--no-progress", str(wav)],
        cwd=work,
        env=env,
        timeout=timeout,
    )
    return _detections_from_proc(proc, wav, work, threshold)


def _analyze_with_birda_docker(
    wav: Path, birda_dir: Path, threshold: float, timeout: int, work: Path
) -> list[Detection]:
    """Run vendored birda inside Ubuntu so a new enough glibc is available."""
    docker = docker_bin()
    if docker is None:
        raise AnalyzeError("未找到 docker，无法在容器中运行 birda。")
    home = Path(os.environ.get("BIRDA_HOME", str(_TOOLS / "birda-home")))
    home.mkdir(parents=True, exist_ok=True)
    # wav already lives under work/; mount that directory as /data.
    cmd = [
        docker,
        "run",
        "--rm",
        "-v",
        f"{birda_dir.resolve()}:/opt/birda:ro",
        "-v",
        f"{work.resolve()}:/data",
        "-v",
        f"{home.resolve()}:/root",
        "-e",
        "LD_LIBRARY_PATH=/opt/birda",
        "-e",
        "HOME=/root",
        "-w",
        "/data",
        BIRDA_DOCKER_IMAGE,
        "/opt/birda/birda",
        "-c",
        str(threshold),
        "-f",
        "csv",
        "--no-progress",
        f"/data/{wav.name}",
    ]
    proc = _run(cmd, cwd=work, env=os.environ.copy(), timeout=timeout)
    return _detections_from_proc(proc, wav, work, threshold)


def run_file_analysis(
    audio: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    timeout: int = 300,
    binary: Path | None = None,
) -> list[Detection]:
    """Analyze `audio` with BirdNET (via BirdNET-Go `file` or birda) → detections.

    Any upload is first converted to 48 kHz mono WAV. Prefer dockerised birda on
    this host (glibc too old for the vendored binaries), then native tools.
    """
    if not audio.is_file():
        raise AnalyzeError("音频文件不存在。")

    def _is_no_birds(exc: AnalyzeError) -> bool:
        return str(exc).strip() == "无法识别"

    with tempfile.TemporaryDirectory(prefix="fugleramme-analyze-") as tmp:
        work = Path(tmp)
        wav = _to_wav(audio, work)

        if binary is not None:
            name = binary.name.lower()
            if "birda" in name:
                return _analyze_with_birda_native(wav, binary, threshold, timeout, work)
            return _analyze_with_birdnet_go(wav, binary, threshold, timeout, work)

        errors: list[str] = []

        # Docker first: host glibc/libstdc++ often cannot run the vendored builds.
        if _BIRDA_DIR.is_dir() and (_BIRDA_DIR / "birda").is_file() and docker_bin():
            try:
                return _analyze_with_birda_docker(wav, _BIRDA_DIR, threshold, timeout, work)
            except AnalyzeError as exc:
                if _is_no_birds(exc):
                    raise
                errors.append(str(exc))

        birda = birda_bin()
        if birda is not None:
            try:
                return _analyze_with_birda_native(wav, birda, threshold, timeout, work)
            except AnalyzeError as exc:
                if _is_no_birds(exc):
                    raise
                errors.append(str(exc))

        go = birdnet_bin()
        if go is not None:
            try:
                return _analyze_with_birdnet_go(wav, go, threshold, timeout, work)
            except AnalyzeError as exc:
                if _is_no_birds(exc):
                    raise
                errors.append(str(exc))

        detail = (" ".join(errors)).strip()
        raise AnalyzeError(
            "未找到可用的 BirdNET 分析工具（BirdNET-Go / birda）。"
            + (
                f" {detail}"
                if detail
                else " 请安装 BirdNET-Go 或 birda，或设置 BIRDNET_GO_BIN / BIRDA_BIN。"
            )
        )
