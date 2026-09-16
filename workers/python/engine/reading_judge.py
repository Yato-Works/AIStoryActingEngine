"""Reading Judge — 読み台本の審査（ADR-0006、Performance Judge 思想の読み版）。

「音が綺麗か」ではなく「**読みとして正しいか**」を審査する。

- ContextReadingJudge（決定論・network 不要）:
    1. 漢字残留 — 全文かな化の原則違反（ADR-0006 §2）
    2. 長さドリフト — かな化は通常もとより長くなるため、
       元テキストより大幅に短い場合は省略・要約の疑い
- OllamaReadingJudge（LLM・オプション）:
    3. 意味保持 — 台本家 AI の変換が原文の意味を保っているか

審査結果は KEEP / 要確認 のみ。自動修正はしない（黙って直さない）。
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from reading import kanji_residue

# ============================================================================
# 審査結果
# ============================================================================

IssueKind = Literal["kanji_residue", "length_drift", "meaning_drift"]


class ReadingIssue(BaseModel):
    """読み台本の 1 件の問題。"""

    segment_id: str
    kind: IssueKind
    detail: str


class ReadingJudgeReport(BaseModel):
    """1 チャンク分の審査結果。"""

    issues: list[ReadingIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, segment_id: str, kind: IssueKind, detail: str) -> None:
        self.issues.append(
            ReadingIssue(segment_id=segment_id, kind=kind, detail=detail))


# ============================================================================
# 決定論審査（常に実行）
# ============================================================================

# かな化でテキストがこの倍率を下回ったら省略の疑い（かな化は通常 1.2〜2.0 倍化する）
MAX_COMPRESSION_RATIO = 0.9


def judge_reading_segment(text: str, text_reading: str, segment_id: str,
                          max_compression: float = MAX_COMPRESSION_RATIO
                          ) -> list[ReadingIssue]:
    """1 セグメントの読み台本を決定論的に審査する。"""
    issues: list[ReadingIssue] = []

    residue = kanji_residue(text_reading)
    if residue:
        issues.append(ReadingIssue(
            segment_id=segment_id, kind="kanji_residue",
            detail=f"漢字が残存: {''.join(residue)}"))

    base_len = len(re.sub(r"\s", "", text))
    read_len = len(re.sub(r"\s", "", text_reading))
    ratio = read_len / max(1, base_len)
    if ratio < max_compression:
        issues.append(ReadingIssue(
            segment_id=segment_id, kind="length_drift",
            detail=f"読みが原文の {ratio:.2f} 倍しかない（省略・要約の疑い）"))
    return issues


def judge_reading_chunk(segments: list[tuple[str, str, str]],
                        max_compression: float = MAX_COMPRESSION_RATIO
                        ) -> ReadingJudgeReport:
    """チャンク単位の審査。segments: [(segment_id, text, text_reading)]。"""
    report = ReadingJudgeReport()
    for seg_id, text, text_reading in segments:
        for issue in judge_reading_segment(text, text_reading, seg_id,
                                           max_compression):
            report.issues.append(issue)
    return report


class ContextReadingJudge:
    """決定論審査のファサード（llm_judge.ContextJudge の読み版の位置づけ）。"""

    name = "context-reading-judge"

    def judge(self, segments: list[tuple[str, str, str]]
              ) -> ReadingJudgeReport:
        return judge_reading_chunk(segments)


# ============================================================================
# LLM 審査（オプション: 意味保持）
# ============================================================================

_READING_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok"],
}


class OllamaReadingJudge:
    """LLM で「意味が保存されているか」を審査する（オプション）。

    音質や自然さは審査しない。かな化により失われた情報量だけを見る。
    """

    name = "ollama-reading-judge"

    def __init__(self, model: str = "qwen3:4b",
                 host: str = "http://localhost:11434",
                 timeout: float = 300.0) -> None:
        self.model = model
        self.base_url = host.rstrip("/")
        self.timeout = timeout

    def check_meaning(self, text: str, text_reading: str,
                      segment_id: str) -> list[ReadingIssue]:
        payload = {
            "model": self.model,
            "prompt": f"""次の原文と、読み台本（全文かな）を比較してください。

## 原文
{text}

## 読み台本
{text_reading}

## 判定
1. 読み台本は原文の**意味をすべて保っているか**（言い換えによる意味変質も検出）。
2. 重要な情報が省略されていないか。
3. 読み方として明らかに不自然な箇所がないか。
問題があれば issues に具体的に列挙。問題なければ ok=true。
JSONのみを返却。""",
            "stream": False,
            "format": _READING_JUDGE_SCHEMA,
            "think": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
        }
        try:
            import httpx as _hx
            r = _hx.post(f"{self.base_url}/api/generate", json=payload,
                         timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # 審査失敗は黙って無視せず報告する
            return [ReadingIssue(
                segment_id=segment_id, kind="meaning_drift",
                detail=f"読み審査（LLM）に失敗: {exc}")]
        raw = data["response"] if isinstance(data, dict) else str(data)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return []
        verdict = json.loads(match.group(0))
        if verdict.get("ok"):
            return []
        return [ReadingIssue(
            segment_id=segment_id, kind="meaning_drift",
            detail=str(issue)) for issue in (verdict.get("issues") or [])]
