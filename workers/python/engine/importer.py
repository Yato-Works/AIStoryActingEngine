"""書籍・原稿インポーター（テキスト・PDF・画像OCR/Vision対応）。

ユーザーが持っている本を：
1. テキストファイル (.txt, .md)
2. PDF ファイル (.pdf)
3. 撮影した画像 (.png, .jpg, .jpeg, .webp)
から抽出し、AIStoryActingEngine が解析可能な標準テキストに変換する。
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Sequence

import httpx


def read_text_file(path: Path) -> str:
    """文字コード（UTF-8, CP932/Shift_JIS, UTF-16）に対応してテキストを読み込む。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc-jp", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def extract_pdf_text(path: Path) -> str:
    """PDF ファイルから各ページのテキストを抽出する。"""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("pypdf がインストールされていません: pip install pypdf") from e

    reader = PdfReader(str(path))
    pages_text: list[str] = []
    for idx, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        if t.strip():
            pages_text.append(f"<!-- page {idx + 1} -->\n" + t.strip())

    if not pages_text:
        # テキストレイヤーが無いスキャンPDFの場合
        raise ValueError(
            f"PDF '{path.name}' にテキストレイヤーがありません。画像OCRでの読み込みが必要です。"
        )

    return "\n\n".join(pages_text)


def extract_image_text(
    image_path: Path,
    ollama_host: str = "http://localhost:11434",
    vision_model: str = "qwen2.5-vl:7b",
    timeout: float = 120.0,
) -> str:
    """撮影した本の画像から Vision LLM を使用して本文テキストを抽出する。"""
    image_bytes = image_path.read_bytes()
    b64_img = base64.b64encode(image_bytes).decode("utf-8")

    prompt = (
        "あなたは高精度な書籍OCR・テキスト抽出アシスタントです。\n"
        "提供された画像（小説・書籍のページ写真）から、日本語の本文テキストのみを忠実に文字起こししてください。\n"
        "ページ番号や柱（上部の章題）、ゴミ、写真内の影・歪みは無視し、小説の本文・台詞をそのまま正確に出力してください。\n"
        "余計な解説や前置き、コードブロックは一切含めず、抽出されたテキスト本文のみを返答してください。"
    )

    payload = {
        "model": vision_model,
        "prompt": prompt,
        "images": [b64_img],
        "stream": False,
        "options": {"temperature": 0.1},
    }

    base_url = ollama_host.rstrip("/")
    try:
        resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("response", "")).strip()
    except Exception as exc:
        raise RuntimeError(
            f"画像 '{image_path.name}' の Vision LLM テキスト抽出に失敗しました ({vision_model}): {exc}"
        ) from exc


def clean_story_text(text: str) -> str:
    """OCRやPDF抽出後のテキストを整形する（不自然な改行の修正、ルビ処理）。"""
    # 青空文庫形式のルビ 《...》 や ｜ の正規化
    text = re.sub(r"《.*?》", "", text)
    text = re.sub(r"［＃.*?］", "", text)
    text = text.replace("｜", "")

    lines = [line.rstrip() for line in text.splitlines()]
    cleaned_lines: list[str] = []
    for line in lines:
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def import_book_document(
    sources: Sequence[Path | str],
    title: str | None = None,
    out_dir: Path | None = None,
    ollama_host: str = "http://localhost:11434",
    vision_model: str = "qwen2.5-vl:7b",
) -> Path:
    """テキスト、PDF、画像群を受け取り、1つの小説テキストファイルにまとめて出力する。"""
    source_paths = [Path(p) for p in sources]
    if not source_paths:
        raise ValueError("取り込むファイルが指定されていません。")

    chunks_text: list[str] = []
    book_title = title or source_paths[0].stem

    for path in source_paths:
        if not path.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {path}")

        suffix = path.suffix.lower()
        if suffix in (".txt", ".md"):
            chunks_text.append(read_text_file(path))
        elif suffix == ".pdf":
            chunks_text.append(extract_pdf_text(path))
        elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            chunks_text.append(
                extract_image_text(
                    path,
                    ollama_host=ollama_host,
                    vision_model=vision_model,
                )
            )
        else:
            raise ValueError(f"未対応のファイル形式です: {path.suffix}")

    merged = clean_story_text("\n\n".join(chunks_text))

    target_dir = out_dir or Path(__file__).parent / "data" / "imported"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / f"{book_title}.txt"
    out_file.write_text(merged, encoding="utf-8")
    return out_file
