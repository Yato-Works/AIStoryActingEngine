"""Audio Engine — セグメント音声の連結。

Phase 0 では FFmpeg の concat demuxer を使う（edge-tts は mp3 出力のため）。
FFmpeg が無い場合はスキップして警告を出す（セグメント単体は聴ける）。
将来の M4B 化（チャプター・cover・metadata 埋め込み）もここに実装する。
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

_FFMPEG_CACHE: str = ""


def _winget_ffmpeg() -> str:
    """winget (Gyan.FFmpeg) の既定インストール先から ffmpeg.exe を探す。"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return ""
    hits = glob.glob(
        os.path.join(base, "Microsoft", "WinGet", "Packages",
                     "Gyan.FFmpeg*", "ffmpeg-*", "bin", "ffmpeg.exe")
    )
    return hits[0] if hits else ""


def ffmpeg_path() -> str | None:
    """ffmpeg 実行ファイルのパスを返す（無ければ None）。結果はキャッシュ。"""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE
    if _FFMPEG_CACHE == "" and shutil.which("ffmpeg"):
        _FFMPEG_CACHE = shutil.which("ffmpeg") or ""
        return _FFMPEG_CACHE or None
    _FFMPEG_CACHE = _winget_ffmpeg()
    return _FFMPEG_CACHE or None


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


def concat_audio(files: list[Path], out_path: Path, work_dir: Path | None = None) -> Path | None:
    """音声ファイル列を連結して 1 つの WAV を作る。

    成功時は out_path を返す。FFmpeg が無い・失敗した場合は None を返す。
    """
    if not files:
        return None
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        print("⚠ ffmpeg が見つかりません。連結をスキップします（`winget install ffmpeg` で導入できます）")
        return None

    list_path = (work_dir or out_path.parent) / "concat_list.txt"
    lines = [f"file '{str(f.resolve()).replace(chr(39), chr(39) * 2)}'" for f in files]
    list_path.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠ 連結に失敗しました: {result.stderr[-500:]}")
        return None
    return out_path


def export_m4b(wav_path: Path, out_path: Path, title: str = "AIStoryActingEngine") -> Path | None:
    """（将来用）WAV からチャプター付き M4B を作る。Phase 0 では未使用。"""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        return None
    cmd = [
        ffmpeg, "-y", "-i", str(wav_path),
        "-c:a", "aac", "-b:a", "64k",
        "-metadata", f"title={title}",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return out_path

