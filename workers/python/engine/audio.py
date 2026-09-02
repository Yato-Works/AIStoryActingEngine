"""ffmpeg による音声連結。

winget 経由でインストールした ffmpeg は PATH が子プロセスに引き継がれない
ことがあるため、winget のインストール先を直接探すフォールバックを持つ。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # winget (Gyan.FFmpeg) のインストール先を探す
    root = os.environ.get("LOCALAPPDATA")
    if root:
        for cand in Path(root).glob(
            r"Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffmpeg.exe"
        ):
            return str(cand)
    return "ffmpeg"


# ---------------------------------------------------------------- Pause Engine
# 無音 gap_ms -> 人間の「間」3種類。毎回同じ無音だと AI っぽさMAX。
PAUSE_TYPES = ("silence", "breath", "vocal_tail")


def build_pause(gap_ms: int = 250, gap_type: str = "breath") -> Path:
    """gap_type ごとの自然な間を WAV として生成/キャッシュして返す。"""
    out_dir = Path.cwd() / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f".gap_{gap_ms}_{gap_type}.wav"
    if out.exists():
        return out
    ffmpeg = _find_ffmpeg()
    if gap_type == "breath":
        src = "anoisesrc=color=pink:amplitude=0.015:duration=1"
    elif gap_type == "vocal_tail":
        src = "anoisesrc=color=brown:amplitude=0.025:duration=1"
    else:
        src = "anullsrc=channel_layout=mono"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", src,
         "-t", f"{gap_ms / 1000:.3f}", "-ar", "24000", "-ac", "1",
         str(out)],
        check=True, capture_output=True,
    )
    return out


def concat_audio(files: list[Path], out_path: Path, gap_ms: int = 250, gap_type: str = "breath") -> Path:
    """wav/mp3 のリストを gap_ms / gap_type の自然な間で連結して1本のwavにする。

    gap_type: silence / breath / vocal_tail のうち選択。既存呼び出しサイトは
    gap_type を省略でき、デフォルト 'breath' になる (後方互換)。"""
    if not files:
        raise ValueError("連結する音声ファイルがありません")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.with_suffix(".txt")
    gap = build_pause(gap_ms, gap_type) if gap_ms > 0 else None
    nl = chr(10)
    with list_file.open("w", encoding="utf-8") as f:
        for i, pp in enumerate(files):
            if gap and i > 0:
                f.write(f"file '{gap.resolve()}'" + nl)
            f.write(f"file '{pp.resolve()}'" + nl)
    ffmpeg = _find_ffmpeg()
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
               "-i", str(list_file), "-ar", "24000", "-ac", "1",
               str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        list_file.unlink(missing_ok=True)
    return out_path


def probe_duration(path: Path) -> float | None:
    ffprobe = str(Path(_find_ffmpeg()).with_name("ffprobe.exe"))
    if not Path(ffprobe).exists() and shutil.which("ffprobe"):
        ffprobe = shutil.which("ffprobe")  # type: ignore[assignment]
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


# ----------------------------------------------------------------
# M4B（チャプター付きオーディオブック）
# ----------------------------------------------------------------

def _chapter_ranges(parts: list, durations: list[float],
                    gap_ms: int = 250) -> list[dict]:
    """(segment_id, chapter, path) と各ファイルの秒数 → 章の (start, end) ms。

    parts は音声の再生順に並んでいる前提。章の境界は「章番号が変わった時点」。
    """
    chapters: list[dict] = []
    t = 0.0
    for i, (_, chapter, _path) in enumerate(parts):
        if not chapters or chapters[-1]["chapter"] != chapter:
            if chapters:
                chapters[-1]["end"] = t
            chapters.append({"chapter": chapter, "start": t})
        t += durations[i] * 1000
        if gap_ms > 0 and i < len(parts) - 1:
            t += gap_ms
    if chapters:
        chapters[-1]["end"] = t
    return chapters


def build_chapter_meta(parts: list, durations: list[float],
                       chapter_titles: dict[int, str] | None = None,
                       title: str = "", gap_ms: int = 250) -> str:
    """FFmpeg の ffmetadata 形式（チャプター定義）を生成する純粋関数。"""
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={title}")
    for ch in _chapter_ranges(parts, durations, gap_ms):
        name = ((chapter_titles or {}).get(ch["chapter"])
                or f"第{ch['chapter']}章")
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={int(ch['start'])}", f"END={int(ch['end'])}",
                  f"title={name}"]
    return "\n".join(lines) + "\n"


def export_m4b(parts: list[tuple[str, int, Path]], out_path: Path,
               chapter_titles: dict[int, str] | None = None,
               title: str = "", gap_ms: int = 250) -> Path:
    """音声セグメント (id, chapter, path) を AAC 再エンコードで
    チャプター付き M4B にする。ソースが wav/mp3 混在でも decode するので安全。
    """
    if not parts:
        raise ValueError("連結する音声ファイルがありません")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_ffmpeg()

    durations = [probe_duration(p) or 0.0 for _, _, p in parts]
    list_file = out_path.with_suffix(".list.txt")
    meta_file = out_path.with_suffix(".meta.txt")

    gap: Path | None = None
    if gap_ms > 0:
        gap = out_path.parent / f".gap_{gap_ms}_m4b.wav"
        if not gap.exists():
            subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-t", f"{gap_ms / 1000:.3f}", str(gap)],
                check=True, capture_output=True,
            )

    with list_file.open("w", encoding="utf-8") as f:
        for i, (_, _, p) in enumerate(parts):
            if gap and i > 0:
                f.write(f"file '{gap.resolve()}'\n")
            f.write(f"file '{p.resolve()}'\n")
    meta_file.write_text(
        build_chapter_meta(parts, durations, chapter_titles, title, gap_ms),
        encoding="utf-8")

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-i", str(meta_file), "-map_metadata", "1", "-map", "0:a",
           "-c:a", "aac", "-b:a", "96k", "-ar", "24000", "-ac", "1",
           str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        list_file.unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)
    return out_path


import re as _re
from dataclasses import dataclass


@dataclass
class SpeechSegment:
    type: str          # "speech" | "vocalization" | "pause" | "hesitation"
    text: str = ""
    duration_ms: float | None = None
    strength: float | None = None
    kind: str | None = None

    def to_dict(self):
        return {"type": self.type, "text": self.text,
                "duration_ms": self.duration_ms,
                "strength": self.strength, "kind": self.kind}


_VOCALIZATION_PATTERNS = [
    (r"^え{1,3}[ー～~]*…+", "vocalization", 0.65),
    (r"^ん{1,2}[ー～~]*…+", "vocalization", 0.55),
    (r"^あ{1,2}あ{0,2}[ー～~]*…+", "vocalization", 0.50),
    (r"^[えやあ]{1,2}ー+", "vocalization", 0.50),
]


def plan_speech_segments(text, intent=None):
    """Text -> SpeechSegment list（Voice Director 方針: breath unit で切る）。

    例: 「え……それは……違う」
      -> [vocalization("え"), speech("それは"), pause(hesitation/320ms), speech("違う")]
    """
    intent_key = (intent or "").lower().replace(" ", "_")
    segments = []
    rest = text
    for pat, vtype, strength in _VOCALIZATION_PATTERNS:
        m = _re.match(pat, rest)
        if m:
            vtxt = m.group(0)
            core = _re.sub(r"…+", "", vtxt)
            segments.append(SpeechSegment(type=vtype, text=core, strength=strength))
            rest = rest[m.end():]
            break
    for ch in _re.split(r"(…{2,}|…)", rest):
        if not ch:
            continue
        if ch == "…" or _re.fullmatch(r"…{2,}", ch):
            kind = "hesitation" if ("hesit" in intent_key or intent_key == "hesitant_denial") else "thinking"
            segments.append(SpeechSegment(type="pause", kind=kind, duration_ms=320.0))
        else:
            segments.append(SpeechSegment(type="speech", text=ch))
    return segments


def crossfade_concat(files, out_path, crossfade_ms=40.0, sample_rate=24000):
    """micro crossfade 付き連結。毎接続2クリップを {crossfade_ms}ms overlap。"""
    files = [Path(f) for f in files]
    if not files:
        raise ValueError("連結する音声ファイルがありません")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_ffmpeg()
    xf = max(float(crossfade_ms) / 1000.0, 0.02)
    n = len(files)
    cmd = [ffmpeg, "-y"]
    for f in files:
        cmd += ["-i", str(f)]
    if n == 1:
        cmd += ["-ac", "1", "-ar", str(sample_rate), str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    parts = []
    acc = "0:a"
    for i in range(1, n):
        out = "x%d" % (i - 1)
        parts.append("[" + acc + "][" + str(i) + ":a]acrossfade=d=%.3f[%s]" % (xf, out))
        acc = out
    filt = ";".join(parts)
    cmd += ["-filter_complex", filt, "-map", "[" + acc + "]",
            "-ac", "1", "-ar", str(sample_rate), str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path

# ---------------------------------------------------------------- 3.5G Breath Engine
# pink-noise から脱却し、BreathEvent を独立した演技要素として扱う。
# plan_breaths は「どの phrase で、どんな呼吸か」を Voice Director が決める。
# （長文/呼吸頻度/感情/キャラ状態で呼吸位置を推定）

@dataclass
class BreathEvent:
    type: str            # "inhale" | "exhale"
    length: str = "short"  # "short" | "long"
    intensity: float = 0.5   # 0.0 .. 1.0
    emotion: str = "neutral"
    voicing: str = "unvoiced"
    phrase_index: int = -1


BREATH_TYPES = ("inhale", "exhale")
BREATH_LENGTHS = ("short", "long")


def plan_breaths(num_phrases, profile=None, state=None, emotion="neutral",
                 intent=None, seed=42):
    """Voice Director 視点の呼吸計画。毎 phrase ではなく意味ある場所に。

    breath_frequency(profile) + 状態(tension/fatigue/excitement) で呼吸間隔を決定し、
    fatigue で長めの exhale, tension で short inhale, を選ぶ。 seed 固定で再生可能。"""
    import random as _random
    rng = _random.Random(seed)
    freq = 0.0
    if profile is not None:
        freq += float(getattr(profile, "breath_frequency", 0.0) or 0.0)
    if state is not None:
        freq += 0.30 * float(state.fatigue) - 0.15 * float(state.excitement) + 0.10 * float(state.tension)
    freq = max(0.0, min(1.0, freq))
    avg_gap = 3.0 * (1.0 - freq) + 1.0   # 1..4 phrases between breaths
    breath_at = []
    pos = avg_gap
    while pos < num_phrases:
        breath_at.append(int(pos))
        pos += avg_gap + rng.uniform(-0.6, 0.6)
    events = []
    for idx in breath_at:
        if state is not None and state.fatigue >= 0.6:
            ev = BreathEvent(type="exhale", length="long",
                             intensity=round(0.6 + 0.4 * state.fatigue, 3), emotion=emotion)
        elif state is not None and state.tension >= 0.6:
            ev = BreathEvent(type="inhale", length="short",
                             intensity=round(0.4 + 0.3 * state.tension, 3), emotion=emotion)
        else:
            r = rng.random()
            ev = BreathEvent(type="exhale" if r < 0.6 else "inhale",
                             length="long" if rng.random() < 0.3 else "short",
                             intensity=round(0.4 + 0.3 * rng.random(), 3), emotion=emotion)
        ev.phrase_index = idx
        events.append(ev)
    return events


def render_breath(event, out_path, sample_rate=24000):
    """BreathEvent -> WAV（brown-noise rumble + low sine, afade in/out）。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_ffmpeg()
    amp = round(event.intensity, 3) or 0.5
    dur = 0.35 if event.length == "short" else 0.60
    fade = "in" if event.type == "inhale" else "out"
    noise = "anoisesrc=color=brown:amplitude=" + str(amp) + ":duration=" + str(dur)
    sine = "aevalsrc=" + str(amp * 0.5) + "*sin(2*PI*48*t):duration=" + str(dur)
    filt = "[0:a]afade=t=" + fade + ":st=0:d=" + str(round(dur, 3)) + "[n];[1:a][n]amix=inputs=2:duration=first"
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", noise, "-f", "lavfi", "-i", sine,
           "-filter_complex", filt, "-ar", str(sample_rate), "-ac", "1", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path



if __name__ == "__main__":
    print("ffmpeg:", _find_ffmpeg(), file=sys.stderr)
