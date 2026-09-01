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


if __name__ == "__main__":
    print("ffmpeg:", _find_ffmpeg(), file=sys.stderr)
