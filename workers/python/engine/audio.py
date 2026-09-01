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


def concat_audio(files: list[Path], out_path: Path, gap_ms: int = 250) -> Path:
    """wav/mp3 のリストを gap_ms の間隔で連結して 1 本の wav にする。"""
    if not files:
        raise ValueError("連結する音声ファイルがありません")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    list_file = out_path.with_suffix(".txt")
    # 無音ギャップは出力先ディレクトリに隠しファイルとして置く（CWD を汚さない）
    gap = out_path.parent / f".gap_{gap_ms}.wav"
    # 無音ファイルを生成（必要な場合のみ）
    ffmpeg = _find_ffmpeg()
    if gap_ms > 0 and not gap.exists():
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono", "-t", f"{gap_ms / 1000:.3f}",
             str(gap)],
            check=True, capture_output=True,
        )

    with list_file.open("w", encoding="utf-8") as f:
        for i, p in enumerate(files):
            if gap_ms > 0 and i > 0:
                f.write(f"file '{gap.resolve()}'\n")
            f.write(f"file '{p.resolve()}'\n")

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # copy で失敗したら再エンコードでフォールバック
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


if __name__ == "__main__":
    print("ffmpeg:", _find_ffmpeg(), file=sys.stderr)
