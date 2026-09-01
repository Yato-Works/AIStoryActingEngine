"""AIStoryActingEngine — Phase 0 PoC

小説テキスト → Story Analyzer → キャスティング → Voice Director → TTS → 音声

使い方:
    python main.py [novel.txt] [--provider edge|aivis] [--no-tts] [--max-chunks N]

出力（output/）:
    performance.json / characters.json / story_state.json
    audio/seg_XXX.mp3 / audiobook.wav
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from analyzer import AnalysisError, OllamaStoryAnalyzer
from audio import concat_audio
from director import CastingDirector, RuleBasedDirector, resolve_tts_voice
from models import Character, DirectedSegment, Segment, StoryState
from schema import (
    clamp,
    normalize_emotion,
    normalize_segment_type,
    validate_performance_doc,
)
from tts import create_provider

NARRATOR_ID = "narrator"
CHUNK_TARGET = 900

REPO_ROOT = Path(__file__).resolve().parents[3]


def _setup_stdio() -> None:
    """Windows の cp932 コンソールでも絵文字/日本語を安全に出力できるようにする。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_setup_stdio()



# ---------------------------------------------------------------- 前処理


def chunk_text(text: str, target: int = CHUNK_TARGET) -> list[str]:
    """空行区切りの段落をまとめてチャンク化する。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) > target:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def _slugify(name: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_part = re.sub(r"[^a-zA-Z0-9]", "", normalized).lower()
    return ascii_part or fallback


def resolve_speaker(raw_speaker: object, state: StoryState, fallback_index: int) -> str:
    """LLM が返した speaker を既知キャラクター id に解決する。"""
    if not isinstance(raw_speaker, str) or not raw_speaker.strip():
        return f"unknown_{fallback_index}"
    key = raw_speaker.strip()
    if key in state.characters:
        return key
    # 名前一致 → 部分一致
    for cid, ch in state.characters.items():
        if ch.name == key or ch.name in key or key in ch.name:
            return cid
    # 未知の話者は即席キャラクターとして登録（後でキャスティングされる）
    cid = _slugify(key, f"unknown_{fallback_index}")
    if cid in state.characters:
        return cid
    state.characters[cid] = Character(id=cid, name=key)
    return cid


def build_segments(raw_segments: list[dict], state: StoryState, start_no: int) -> list[Segment]:
    segments: list[Segment] = []
    for raw in raw_segments:
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        stype = normalize_segment_type(raw.get("type"))
        speaker = NARRATOR_ID if stype == "narration" else resolve_speaker(
            raw.get("speaker"), state, start_no + len(segments)
        )
        segments.append(Segment(
            id=f"seg_{start_no + len(segments):03d}",
            type=stype,
            speaker=speaker,
            text=text,
            emotion=normalize_emotion(raw.get("emotion")),
            intensity=clamp(raw.get("intensity", 0.3), 0.0, 1.0),
        ))
    return segments


def merge_state(state: StoryState, analysis: dict) -> list[str]:
    """解析結果を物語状態へマージする。新規キャラ名のリストを返す。"""
    new_names: list[str] = []
    for raw in analysis.get("characters", []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        cid = str(raw.get("id", "")).strip() or _slugify(name, f"char_{len(state.characters)}")
        if cid in state.characters:
            existing = state.characters[cid]
            for trait in raw.get("traits", []):
                if trait not in existing.traits:
                    existing.traits.append(str(trait))
            continue
        state.characters[cid] = Character(
            id=cid,
            name=name,
            gender=raw.get("gender", "unknown") if raw.get("gender") in ("male", "female") else "unknown",
            age=raw.get("age") if raw.get("age") in ("child", "young", "adult", "elder") else "adult",
            role=str(raw.get("role", "")),
            traits=[str(t) for t in raw.get("traits", []) if t],
        )
        new_names.append(name)
    # 関係性
    for src, rels in analysis.get("relationships", {}).items():
        if not isinstance(rels, dict):
            continue
        src_id = src if src in state.characters else next(
            (c.id for c in state.characters.values() if c.name == src), None)
        if src_id is None:
            continue
        for dst, label in rels.items():
            dst_id = dst if dst in state.characters else next(
                (c.id for c in state.characters.values() if c.name == dst), None)
            if dst_id:
                state.characters[src_id].relationships[dst_id] = str(label)
    # 場面・時間帯・雰囲気
    if analysis.get("scene"):
        state.scene = str(analysis["scene"])
    if analysis.get("time_of_day"):
        state.time_of_day = str(analysis["time_of_day"])
    if analysis.get("mood"):
        state.mood = str(analysis["mood"])
    return new_names

    return new_names


# ---------------------------------------------------------------- パイプライン


def run(novel_path: Path, out_dir: Path, provider_name: str, max_chunks: int | None, no_tts: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = out_dir / "audio"

    text = novel_path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    if max_chunks:
        chunks = chunks[:max_chunks]
    print(f"📖 {novel_path.name} — {len(chunks)} チャンク / {len(text)} 文字")

    # 1. Story Analyzer（逐次処理: LLM → 状態更新 → キャスティング）
    analyzer = OllamaStoryAnalyzer()
    state = StoryState()
    casting = CastingDirector()
    segments: list[Segment] = []

    for i, chunk in enumerate(chunks):
        print(f"\n🔍 [{i + 1}/{len(chunks)}] 解析中... (model: {analyzer.model})")
        try:
            analysis = analyzer.analyze(chunk, state.summary(), i)
        except Exception as exc:  # noqa: BLE001 — PoC は継続を優先
            print(f"✗ 解析失敗、このチャンクをスキップ: {exc}")
            continue
        new_names = merge_state(state, analysis)
        for name in new_names:
            print(f"  ✓ CHARACTER_CREATED: {name}")
        segments.extend(build_segments(analysis["segments"], state, len(segments) + 1))
        assigned = casting.assign_voices(state)
        for name in assigned:
            print(f"  ✓ VOICE_ASSIGNED: {name}")

    if not segments:
        print("✗ セグメントが 1 つも生成されませんでした")
        return 1
    print(f"\n✓ ANALYZE 完了: {len(segments)} セグメント / {len(state.characters)} キャラクター")

    # 2. Voice Director（ルールベースの演技指示）
    director = RuleBasedDirector()
    directed: list[DirectedSegment] = [director.direct(s, state) for s in segments]
    print("✓ DIRECT 完了")

    # 3. 契約 JSON の保存
    (out_dir / "characters.json").write_text(
        json.dumps({"characters": [c.model_dump() for c in state.characters.values()]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "story_state.json").write_text(
        state.model_dump_json(indent=2), encoding="utf-8")
    performance_doc = {
        "novel": novel_path.name,
        "provider": provider_name,
        "segments": [d.model_dump() for d in directed],
    }
    errors = validate_performance_doc(performance_doc)
    (out_dir / "performance.json").write_text(
        json.dumps(performance_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        for e in errors:
            print(f"⚠ performance.json 検証: {e}")
    else:
        print("✓ performance.json / characters.json / story_state.json 保存（契約検証OK）")

    if no_tts:
        print("\n--no-tts のため音声生成をスキップしました")
        return 0

    # 4. TTS（セグメント単位）
    provider = create_provider(provider_name)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_files: list[Path] = []
    print(f"\n🎙 TTS 生成開始（provider: {provider.name}）")
    for d in directed:
        assert d.performance is not None
        out_file = audio_dir / f"{d.id}.mp3"
        try:
            profile = resolve_tts_voice(d.performance.voice, state)
            provider.synthesize(d.text, profile, d.performance, out_file)
            audio_files.append(out_file)
            print(f"  ✓ {d.id} [{d.speaker}/{d.performance.emotion}] {d.text[:24]}...")
        except Exception as exc:  # noqa: BLE001 — 1セグメント失敗で全体を止めない
            print(f"  ✗ {d.id} 合成失敗: {exc}")

    # 5. 連結
    if audio_files:
        print(f"\n🎧 連結中... ({len(audio_files)} セグメント)")
        book = concat_audio(audio_files, out_dir / "audiobook.wav", work_dir=audio_dir)
        if book:
            print(f"✓ EXPORT 完了: {book}")
    print(f"\n🎯 完了: 成功 {len(audio_files)}/{len(directed)} セグメント → {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AIStoryActingEngine Phase 0 PoC")
    parser.add_argument("novel", nargs="?", type=Path,
                        default=REPO_ROOT / "samples" / "sample_novel.txt",
                        help="小説テキストファイル（UTF-8）")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "output")
    parser.add_argument("--provider", choices=["edge", "aivis"], default="edge")
    parser.add_argument("--max-chunks", type=int, default=None)
    parser.add_argument("--no-tts", action="store_true", help="解析と演出指示のみ（音声なし）")
    args = parser.parse_args()
    if not args.novel.exists():
        print(f"✗ 小説ファイルが見つかりません: {args.novel}")
        return 1
    return run(args.novel, args.out, args.provider, args.max_chunks, args.no_tts)


if __name__ == "__main__":
    sys.exit(main())
