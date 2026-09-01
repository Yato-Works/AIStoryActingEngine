"""IStoryAnalyzer の Ollama 実装（qwen3 等のローカルLLM）。"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Protocol

import httpx

from models import Character, StoryState

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "gender": {"type": "string", "enum": ["male", "female", "unknown"]},
                    "age": {"type": "string", "enum": ["child", "young", "adult", "elder"]},
                    "role": {"type": "string"},
                    "traits": {"type": "array", "items": {"type": "string"}},
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "label": {"type": "string"},
                            },
                            "required": ["target", "label"],
                        },
                    },
                },
                "required": ["id", "name"],
            },
        },
        "scene": {"type": "object"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                    "emotion": {"type": "string"},
                    "intensity": {"type": "number"},
                },
                "required": ["type", "text"],
            },
        },
    },
    "required": ["segments"],
}


class IStoryAnalyzer(Protocol):
    """小説テキストと物語状態 → 構造化された演技台本。"""

    def analyze(self, chunk: str, state_summary: str, chunk_index: int) -> dict: ...


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM 応答に JSON が含まれていません")
    return json.loads(match.group(0))


class OllamaStoryAnalyzer:
    def __init__(self, model: str = "qwen3:4b",
                 host: str = "http://localhost:11434", timeout: float = 600.0) -> None:
        self.model = model
        self.base_url = host.rstrip("/")
        self.timeout = timeout

    def _prompt(self, chunk: str, state_summary: str, chunk_index: int) -> str:
        return f"""あなたは演劇の演出家です。小説の断片を、音声ドラマ用の台本に変換してください。

## これまでに判明している物語の状態（記憶）
{state_summary}

## 今回のテキスト（チャンク {chunk_index + 1}）
{chunk}

## 指示
1. 新しく登場した人物を characters に列挙（id はローマ字の識別子。既出の人物は id を変えずに再利用）。
   relationships には target(相手のid) と label(「告白の相手」「喧嘩した相手」等) を書く。
2. テキストを segments に分解。種類は narration(地の文) / dialogue(台詞) / inner_monologue(心の声)。
   dialogue と inner_monologue は speaker に話者の id を必ず入れる。
   地の文は narrator。話者が不明な台詞は無理に決めず speaker を null にする。
3. 各セグメントに emotion(neutral/calm/happy/sad/angry/fearful/anxious/surprised/sarcastic/tender)
   と intensity(0.0〜1.0) を付ける。
4. 記憶にある「直近の感情」も考慮して、感情の流れを自然にしてください。
5. 心の声は text から「（」「）」を取り除いてください。
6. JSONのみを返却。"""

    def analyze(self, chunk: str, state_summary: str, chunk_index: int) -> dict:
        payload = {
            "model": self.model,
            "prompt": self._prompt(chunk, state_summary, chunk_index),
            "stream": False,
            "format": ANALYSIS_SCHEMA,
            "think": False,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        resp = _post_with_retry(
            f"{self.base_url}/api/generate", payload, self.timeout)
        data = resp["response"] if isinstance(resp, dict) else str(resp)
        return _extract_json(data)


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


def normalize_id(raw: object) -> str:
    """任意の文字列をローマ字 id 風に正規化（簡易版）。"""
    if not isinstance(raw, str) or not raw.strip():
        return "unknown"
    s = unicodedata.normalize("NFKC", raw.strip()).lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s).strip("_")
    return s or "unknown"


def merge_state(state: StoryState, analysis: dict) -> list[str]:
    """解析結果を StoryState へマージし、新規キャラの id リストを返す。"""
    new_ids: list[str] = []
    for raw in analysis.get("characters") or []:
        cid = normalize_id(raw.get("id") or raw.get("name"))
        name = str(raw.get("name") or cid)
        if cid in state.characters:
            ch = state.characters[cid]
            for t in raw.get("traits") or []:
                if t not in ch.traits:
                    ch.traits.append(t)
            continue
        gender = raw.get("gender")
        age = raw.get("age")
        ch = Character(
            id=cid,
            name=name,
            gender=gender if gender in ("male", "female", "unknown") else "unknown",
            age=age if age in ("child", "young", "adult", "elder") else "adult",
            role=str(raw.get("role") or ""),
            traits=[str(t) for t in (raw.get("traits") or [])],
        )
        for rel in raw.get("relationships") or []:
            target = normalize_id(rel.get("target"))
            label = str(rel.get("label") or "")
            if target:
                ch.relationships[target] = label
        state.characters[cid] = ch
        new_ids.append(cid)
    return new_ids
