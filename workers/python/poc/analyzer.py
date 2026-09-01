"""Story Analyzer — Ollama 経由でローカル LLM に物語を解析させる。

IStoryAnalyzer 相当。将来 Gemini / llama.cpp などに差し替えるときは
同じ analyze() 契約を持つクラスを実装する。
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import httpx

SYSTEM_PROMPT = """/no_think
あなたは小説を音声ドラマ化するための Story Analyzer です。
与えられた小説テキストを、音声合成に適した発話単位（セグメント）に分解し、
登場人物・関係性・場面・感情を抽出します。
必ず JSON オブジェクトのみを返してください。説明文は一切書かないでください。
"""

USER_PROMPT_TEMPLATE = """## これまでの物語の状態（記憶）
{state_summary}

## 解析するテキスト（チャンク {chunk_index}）
```
{chunk_text}
```

## 指示
1. テキストを音声ドラマ用のセグメントに分解してください。
   - 地の文 → type "narration", speaker "narrator"
   - 台詞（「」で囲まれた発言）→ type "dialogue", speaker は発話者の id
   - 心の中の声・独白（（）で囲まれた思考など）→ type "inner_monologue", speaker は思考者の id
   - text は原文を一切書き換えず、そのままコピーしてください
   - 台詞には話者名の接頭辞（例: 「美咲「…」」）を付けず、話者は speaker で示してください
   - 感情は neutral / calm / happy / sad / angry / fearful / anxious / surprised / sarcastic / tender から選び、
     強さを intensity (0.0〜1.0) で示してください
2. このチャンクに登場するキャラクターを抽出してください
   - id は半角英数字の短い識別子（例: kenta, misaki）
   - gender は male / female / unknown
3. 場面・時間帯・雰囲気を更新してください

## 出力 JSON 形式
{{
  "segments": [
    {{"type": "narration|dialogue|inner_monologue", "speaker": "narrator または キャラid", "text": "原文そのまま", "emotion": "...", "intensity": 0.3}}
  ],
  "characters": [
    {{"id": "ascii_id", "name": "名前", "gender": "male|female|unknown", "role": "main|side", "traits": ["性格 traits"]}}
  ],
  "relationships": {{"キャラid": {{"キャラid": "関係の説明"}}}},
  "scene": "場面の説明",
  "time_of_day": "夕暮れ など",
  "mood": "全体の雰囲気"
}}"""


class AnalysisError(Exception):
    """LLM 応答の解析に失敗した。"""


def _slugify(name: str, fallback: str) -> str:
    """名前から ascii id を生成する（生成できなければ fallback）。"""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_part = re.sub(r"[^a-zA-Z0-9]", "", normalized).lower()
    return ascii_part or fallback


class OllamaStoryAnalyzer:
    """Ollama HTTP API を使う Story Analyzer。"""

    def __init__(
        self,
        model: str = "qwen3:4b",
        host: str = "http://localhost:11434",
        temperature: float = 0.3,
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.total_prompt_chars = 0

    def analyze(self, chunk_text: str, state_summary: str, chunk_index: int) -> dict[str, Any]:
        """チャンク1つを解析し、生の JSON dict を返す。

        返却キー: segments / characters / relationships / scene / time_of_day / mood
        """
        user_prompt = USER_PROMPT_TEMPLATE.format(
            state_summary=state_summary or "（なし）",
            chunk_index=chunk_index + 1,
            chunk_text=chunk_text,
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = self._chat(user_prompt, strict=attempt == 1)
                return self._validate(raw)
            except (AnalysisError, httpx.HTTPError) as exc:
                last_error = exc
        raise AnalysisError(f"チャンク {chunk_index + 1} の解析に失敗: {last_error}")

    # ------------------------------------------------------------------
    def _chat(self, user_prompt: str, strict: bool) -> dict[str, Any]:
        if strict:
            user_prompt += (
                "\n\n※ 前回の応答は不正でした。"
                "テキストの内容を書き換えず、指定の JSON 形式で正確に返してください。"
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "think": False,  # thinking トークンが num_predict を消費して content が空になるのを防ぐ
            "keep_alive": "5m",
            "options": {"temperature": self.temperature, "num_ctx": 8192, "num_predict": 4096},
        }
        resp = httpx.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return self._extract_json(content)

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        text = content.strip()
        # コードフェンス除去
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 最初の { から最後の } までを試す
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise AnalysisError(f"JSON が見つかりません: {content[:200]!r}")
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise AnalysisError(f"JSON パース失敗: {exc}") from exc
        if not isinstance(data, dict):
            raise AnalysisError("応答が JSON オブジェクトではありません")
        return data

    def _validate(self, data: dict[str, Any]) -> dict[str, Any]:
        segments = data.get("segments")
        if not isinstance(segments, list) or not segments:
            raise AnalysisError("segments が空です")
        cleaned = [s for s in segments if isinstance(s, dict) and str(s.get("text", "")).strip()]
        if not cleaned:
            raise AnalysisError("有効な text を持つ segment がありません")
        data["segments"] = cleaned
        data.setdefault("characters", [])
        data.setdefault("relationships", {})
        data.setdefault("scene", "")
        data.setdefault("time_of_day", "")
        data.setdefault("mood", "")
        return data
