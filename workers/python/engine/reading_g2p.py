"""OpenJTalk G2P — 決定論的な全文かな変換（ADR-0006 §4 の主役）。

LLM の読み仮名変換は小規模モデルでは信頼できない（大げさ→おおげすさ 等の
実機事故のため、ADR-0006 の主体を決定論的 G2P に切り替える）。

- pyopenjtalk で通常の日本語読みを高精度に得る（大げさ→おおげさ 等）
- 固有名詞は ReadingDictionary が事前に置換する（辞書が最強）
- pyopenjtalk が無い環境ではフォールバックとして辞書適用のみ
"""

from __future__ import annotations

import re


def openjtalk_available() -> bool:
    try:
        import pyopenjtalk  # noqa: F401
        pyopenjtalk.g2p("テスト", kana=True)
        return True
    except Exception:
        return False


def g2p_kana(text: str) -> str:
    """日本語テキストを全文かなに変換する（OpenJTalk の読みを使用）。

    句読点・記号は保持する。pyopenjtalk が無い場合は原文を返す
    （呼び出し側の漢字残留チェックが検出できる）。
    """
    try:
        import pyopenjtalk
    except ImportError:
        return text

    # 記号・改行はそのまま残し、読みが必要な連続区間だけ変換する
    out: list[str] = []
    # 変換対象: 漢字・かな・長音・中黒等の語中文字。記号類は区切り。
    for chunk in re.split(r"([、。，．,\.！？!?\n「」『』（）…――・])", text):
        if not chunk:
            continue
        if re.fullmatch(r"[、。，．,\.！？!?\n「」『』（）…――・]", chunk):
            out.append(chunk)
            continue
        if re.fullmatch(r"[a-zA-Z0-9]+", chunk):
            out.append(chunk)  # 英数字はそのまま（TTS 側で読ませる）
            continue
        try:
            reading = pyopenjtalk.g2p(chunk, kana=True)
        except Exception:
            # 失敗時は原文を残す（呼び出し側の漢字残留チェックが検出する）
            reading = chunk
        out.append(reading)
    return "".join(out)
