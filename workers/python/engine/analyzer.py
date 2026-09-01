"""IStoryAnalyzer の Ollama 実装（qwen3 等のローカルLLM）。"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Protocol

import httpx

from models import Character, Relationship, StoryState

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
                    "personality": {"type": "array", "items": {"type": "string"}},
                    "speech_style": {"type": "string"},
                    "emotional_baseline": {"type": "string"},
                    "emotional_range": {"type": "number"},
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "type": {"type": "string"},
                                "label": {"type": "string"},
                            },
                            "required": ["target", "type"],
                        },
                    },
                },
                "required": ["id", "name", "gender", "age", "role",
                             "personality", "speech_style",
                             "emotional_baseline", "emotional_range",
                             "relationships"],
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
   **全員に必ず** gender(male/female/unknown)、age(child/young/adult/elder)、role(main/side など) を書く。
   性別が文から推測できる場合は必ず推測して書く（「彼」→male、「彼女」→female など）。
2. 各人物に personality（性格タグ: 例 ["calm","awkward"]）、speech_style（話し方: polite/casual/rough/formal/cheerful/quiet のどれか）、
   emotional_baseline（普段の感情の基調: neutral/calm/sad/angry/anxious/tender のどれか）、
   emotional_range（感情の起伏の激しさ 0.0〜1.0）を必ず書く。
3. relationships には target(相手のid)、type（loves/friend/best_friend/family/rival/respects/trusts/despises/owes/colleague/acquaintance/enemy のどれか）、
   label（「告白の相手」等の自由文）を書く。一方通行の関係は向きを正しく（AがBを好きなら A→B が loves）。
   複数の人物が登場する場合、台詞や行動から恋愛関係（「好き＝loves」）・友情（friend）・憧れ（respects）・
   対立（enemy/rival）などを読み取って relationships を配列として必ず記入すること。
      関係がわかりませんものの場合でも type 'other' （空ラベル）の要素を 1 つ入れよ。
   例: [{{\"target\": \"mikasa\", \"type\": \"loves\", \"label\": \"ずっと想いを寄せていた相手\"}}]
4. テキストを segments に分解。種類は narration(地の文) / dialogue(台詞) / inner_monologue(心の声)。
   dialogue と inner_monologue は speaker に話者の id を必ず入れる。
   地の文は narrator。話者が不明な台詞は無理に決めず speaker を null にする。
5. 各セグメントに emotion(neutral/calm/happy/sad/angry/fearful/anxious/surprised/sarcastic/tender)
   と intensity(0.0〜1.0) を付ける。
6. 記憶にある「直近の感情」も考慮して、感情の流れを自然にしてください。
7. 心の声は text から「（」「）」を取り除いてください。
8. JSONのみを返却。"""

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

    def suggest_voice(self, profile: dict) -> dict:
        """キャラ像から External / Internal の声を提案させる（LLM キャスティング）。

        失敗時は例外を投げるので、呼び出し側でルールベースへフォールバックする。
        """
        payload = {
            "model": self.model,
            "prompt": _casting_prompt(profile),
            "stream": False,
            "format": CASTING_SCHEMA,
            "think": False,
            "options": {"temperature": 0.2},
        }
        resp = _post_with_retry(f"{self.base_url}/api/generate", payload, 180.0)
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
    """解析結果を StoryState へマージし、新規キャラの id リストを返す。

    relationships は新規・既存を問わず採用する（関係性は後から判明することもある）。
    """
    import schema as contracts

    new_ids: list[str] = []
    for raw in analysis.get("characters") or []:
        cid = normalize_id(raw.get("id") or raw.get("name"))
        name = str(raw.get("name") or cid)
        gender = raw.get("gender")
        age = raw.get("age")
        baseline = contracts.normalize_emotion(
            raw.get("emotional_baseline"), default="neutral")
        if cid in state.characters:
            ch = state.characters[cid]
            for t in raw.get("traits") or []:
                if t not in ch.traits:
                    ch.traits.append(t)
            for t in raw.get("personality") or []:
                if t not in ch.personality:
                    ch.personality.append(str(t))
            if gender in ("male", "female") and ch.gender == "unknown":
                ch.gender = gender  # type: ignore[assignment]
            if not ch.speech_style:
                ch.speech_style = contracts.normalize_speech_style(raw.get("speech_style"))
        else:
            ch = Character(
                id=cid,
                name=name,
                gender=gender if gender in ("male", "female", "unknown") else "unknown",
                age=age if age in ("child", "young", "adult", "elder") else "adult",
                role=str(raw.get("role") or ""),
                traits=[str(t) for t in (raw.get("traits") or [])],
                personality=[str(t) for t in (raw.get("personality") or [])],
                speech_style=contracts.normalize_speech_style(raw.get("speech_style")),
                emotional_baseline=baseline,
                emotional_range=contracts.clamp(raw.get("emotional_range", 0.5), 0.0, 1.0),
            )
            state.characters[cid] = ch
            new_ids.append(cid)
        # relationships は新規・既存両方に適用（後から判明する関係もある）
        for rel in raw.get("relationships") or []:
            target = normalize_id(rel.get("target"))
            if not target or target == cid:
                continue
            ch.relationships[target] = Relationship(
                type=contracts.normalize_relationship(rel.get("type")),
                label=str(rel.get("label") or ""),
            )
    return new_ids


CASTING_SCHEMA = {
    "type": "object",
    "properties": {
        "external": {
            "type": "object",
            "properties": {
                "voice_id": {"type": "string"},
                "pitch": {"type": "number"},
                "pace": {"type": "number"},
            },
            "required": ["voice_id"],
        },
        "internal": {
            "type": "object",
            "properties": {
                "voice_id": {"type": "string"},
                "pitch": {"type": "number"},
                "pace": {"type": "number"},
            },
            "required": ["voice_id"],
        },
    },
    "required": ["external", "internal"],
}


def _casting_prompt(profile: dict) -> str:
    return f"""あなたは音声ドラマのキャスティングディレクターです。
次のキャラクターの声を 2 つ選んでください。external は他者に聞こえる「外向きの声」、
internal は独り言・心の声用の「内面の声」（external より低く静かな傾向）。

## キャラクター
{json.dumps(profile, ensure_ascii=False)}

## 選べる声の候補（voice_id: 説明）
voice_01: 若い男性の声（pitch 0.05 / pace 1.05 標準）
voice_02: 若い女性の声（pitch 0.12 / pace 1.0 標準）
voice_03: 落ち着いた女性の声（pitch -0.02 / pace 0.95 標準）
voice_04: 渋い中年男性の声（pitch -0.10 / pace 0.90 標準）

## 指示
- 性別・年齢・性格・話し方に最も合う voice_id を external / internal それぞれ 1 つ選ぶ。
- pitch(-1.0..1.0) と pace(0.5..1.5) で微調整する（性格が明るいなら pitch/pace を上げる等）。
  internal は external より pitch -0.05..-0.15 程度低く、pace 0.85..0.95 程度に遅くするのが目安。
- external と internal は同じ voice_id でも構わないが、内面が外見と違うキャラは変えてもよい。
- JSONのみを返却。"""
