"""Script Writer — 読み仮名付き台本を書く AI 台本家。

ADR-0006 に基づく。「声は天才だが漢字が読めない演者さん（Irodori-TTS）」の
ために、文脈を読解して全文かなの台本を書く LLM レイヤー。

- Story Analyzer と同じ Ollama パターン（schema 強制 + JSON 抽出）。
- LLM の出力は ReadingDictionary で正規化される（辞書が最強、ADR-0006 §3）。
- 失敗時は DictionaryScriptWriter（辞書適用のみのフォールバック）へ。
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, Field

from reading import (
    ReadingDictionary, ReadingScript, ReadingScriptSegment,
)

# ============================================================================
# LLM 出力スキーマ（Ollama format 強制用）
# ============================================================================

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text_reading": {"type": "string"},
                },
                "required": ["id", "text_reading"],
            },
        },
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "surface": {"type": "string"},
                    "reading": {"type": "string"},
                },
                "required": ["surface", "reading"],
            },
        },
    },
    "required": ["segments"],
}


class ScriptWriterResult(BaseModel):
    """Script Writer の実行結果。"""

    script: ReadingScript
    new_readings: dict[str, str] = Field(default_factory=dict)
    """LLM が新たに提案した読み（辞書へ登録する前の素の提案）。"""
    uncovered: dict[str, list[str]] = Field(default_factory=dict)
    """かな版に漢字が残っているセグメント {segment_id: [漢字, ...]}。"""


class IScriptWriter(Protocol):
    """セグメント群（原文）→ 読み仮名付き台本。"""

    name: str

    def write_script(
        self,
        segments: list[dict],
        dictionary: ReadingDictionary,
        character_glossary: dict[str, str] | None = None,
        chunk_index: int = 0,
    ) -> ScriptWriterResult: ...


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM 応答に JSON が含まれていません")
    return json.loads(match.group(0))


def _prepare_segments(segments: list[dict],
                      dictionary: ReadingDictionary) -> list[dict]:
    """セグメントの text に辞書を先に適用する（ADR-0006 §3）。

    辞書に登録済みの表記は LLM に渡る時点で既にかな化されているため、
    「辞書が LLM より強い」ことが構造的に保証される。
    原文は `_text_original` に退避し、ReadingScript にはそちらを保存する。
    """
    prepared: list[dict] = []
    for seg in segments:
        seg = dict(seg)
        seg["_text_original"] = str(seg.get("text", ""))
        seg["text"] = dictionary.apply(str(seg.get("text", "")))
        prepared.append(seg)
    return prepared


def _build_result(
    segments: list[dict],
    raw: dict,
    dictionary: ReadingDictionary,
    chunk_index: int,
) -> ScriptWriterResult:
    """LLM（またはフォールバック）の生出力を ScriptWriterResult に仕上げる。

    共通後処理（決定論的）:
    1. LLM 提案の readings を取り込み
    2. 辞書（既存 + 提案）を text_reading に適用して正規化
    3. 漢字残留チェック

    segments は既に辞書適用済みであること（_prepare_segments 経由）。
    """
    new_readings = {
        str(e.get("surface", "")).strip(): str(e.get("reading", "")).strip()
        for e in (raw.get("readings") or [])
        if isinstance(e, dict)
        and str(e.get("surface", "")).strip()
        and str(e.get("reading", "")).strip()
    }

    # LLM 提案を含めた辞書で text_reading を正規化（辞書が最強）
    norm = ReadingDictionary(dictionary.entries())
    norm.update_many(new_readings)

    by_id = {
        str(s.get("id")): str(s.get("text_reading", "")).strip()
        for s in (raw.get("segments") or [])
        if isinstance(s, dict) and s.get("id")
    }

    script_segments: list[ReadingScriptSegment] = []
    for seg in segments:
        sid = str(seg.get("id", ""))
        script_segments.append(ReadingScriptSegment(
            id=sid,
            speaker=str(seg.get("speaker", "")),
            text=str(seg.get("_text_original", seg.get("text", ""))),
            # LLM が id を欠落・誤記した場合のフォールバックは辞書適用のみ
            text_reading=norm.apply(by_id.get(sid, "")) or norm.apply(
                str(seg.get("text", ""))),
        ))

    script = ReadingScript(chunk_index=chunk_index, segments=script_segments)
    script.apply_dictionary(dictionary)  # 既存辞書で最終上書き
    return ScriptWriterResult(
        script=script, new_readings=new_readings,
        uncovered=script.uncovered_kanji(),
    )

# ============================================================================
# Ollama 実装
# ============================================================================


class OllamaScriptWriter:
    """Ollama（qwen3 等）で動く AI 台本家。"""

    name = "ollama"

    def __init__(self, model: str = "qwen3:4b",
                 host: str = "http://localhost:11434",
                 timeout: float = 600.0) -> None:
        self.model = model
        self.base_url = host.rstrip("/")
        self.timeout = timeout

    def _prompt(self, segments: list[dict], dictionary: ReadingDictionary,
                character_glossary: dict[str, str] | None,
                chunk_index: int) -> str:
        known = json.dumps(dictionary.entries(), ensure_ascii=False,
                           indent=2) if len(dictionary) else "（なし）"
        glossary = json.dumps(character_glossary or {}, ensure_ascii=False,
                              indent=2)
        payload = json.dumps(
            [{"id": s.get("id", ""), "speaker": s.get("speaker", ""),
              "text": s.get("text", "")} for s in segments],
            ensure_ascii=False, indent=2)
        return f"""あなたは音声ドラマの台本家です。小説のセグメント群を、
「声は非常に優秀だが漢字が読めない演者さん」のために読み台本に起こしてください。

## 台本の規則
1. 各セグメントの text を**すべてかな（ひらがな・カタカナ）だけの文章**に変換した
   text_reading を書く。漢字・ローマ字は残しません（数字・記号・絵文字はそのまま）。
2. 読み方は**文脈**から判断してください（「今日」が「きょう」か「こんにち」か等）。
3. 人名・固有名詞の読みが確定したら readings に {{"surface", "reading"}} で申告してください。
4. すでに辞書に登録済みの表記は、辞書の読みを**絶対に**変更しないでください。
   （入力テキストのうち、辞書の読みで既にかな化されている部分はそのまま使ってください。）
5. text の意味・語順・ニュアンスを変えないでください（言い換え・省略・要約は禁止）。
6. 感嘆符・疑問符・句読点は保持してください。
7. JSONのみを返却。

## 既存の読み辞書（絶対に守る）
{known}

## キャラクター名鑑（人名の読み判断に使う）
{glossary}

## 今回のセグメント（チャンク {chunk_index + 1}）
{payload}
"""

    def write_script(
        self,
        segments: list[dict],
        dictionary: ReadingDictionary,
        character_glossary: dict[str, str] | None = None,
        chunk_index: int = 0,
    ) -> ScriptWriterResult:
        prepared = _prepare_segments(segments, dictionary)
        payload = {
            "model": self.model,
            "prompt": self._prompt(
                prepared, dictionary, character_glossary, chunk_index),
            "stream": False,
            "format": SCRIPT_SCHEMA,
            "think": False,
            "options": {"temperature": 0.2, "num_ctx": 8192},
        }
        resp = _post_with_retry(
            f"{self.base_url}/api/generate", payload, self.timeout)
        data = resp["response"] if isinstance(resp, dict) else str(resp)
        raw = _extract_json(data)
        return _build_result(prepared, raw, dictionary, chunk_index)


def _post_with_retry(url: str, payload: dict, timeout: float,
                     retries: int = 2) -> dict:
    import httpx as _hx
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = _hx.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (_hx.HTTPError, ValueError) as exc:  # type: ignore[attr-defined]
            last_err = exc
    raise RuntimeError(f"Ollama へのリクエストが失敗しました: {last_err}")


# ============================================================================
# フォールバック: 辞書適用のみ（LLM 不要・オフライン）
# ============================================================================


class DictionaryScriptWriter:
    """LLM を使わないフォールバック。

    辞書に登録済みの表記だけ置換する。全文かな化はできず、
    漢字残留は uncovered に素直に報告される（呼び出し側で判断する）。
    """

    name = "dictionary"

    def write_script(
        self,
        segments: list[dict],
        dictionary: ReadingDictionary,
        character_glossary: dict[str, str] | None = None,
        chunk_index: int = 0,
    ) -> ScriptWriterResult:
        prepared = _prepare_segments(segments, dictionary)
        raw = {"segments": [
            {"id": s.get("id", ""), "text_reading": s.get("text", "")}
            for s in prepared
        ]}
        return _build_result(prepared, raw, dictionary, chunk_index)

