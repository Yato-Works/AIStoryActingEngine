"""AIStoryActingEngine — Phase 1: Story Engine (SQLite 記憶 + resume + FTS5)

使い方:
  python main.py ../../samples/sample_novel_long.txt            # 全パイプライン
  python main.py <novel> --resume                               # 中断からの再開
  python main.py <novel> --no-tts --provider edge               # TTS スキップ
  python main.py --search 怒り                                  # FTS5 検索デモ
  python main.py --stats                                        # Event Log 表示
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from analyzer import OllamaStoryAnalyzer, merge_state, normalize_id
from audio import concat_audio, probe_duration
from director import CastingDirector, NARRATOR, RuleBasedDirector
from memory import MemoryEngine
from models import Character, Segment, StoryState
from schema import clamp, normalize_emotion, normalize_segment_type, validate_performance_doc
from tts import get_provider

OUT_DIR = Path(__file__).parent / "output"
DB_PATH = Path(__file__).parent / "data" / "story.db"
CHUNK_TARGET = 850


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def split_chapters(text: str) -> list[tuple[int, str]]:
    """「第N章」見出しで章に分割する（見出しなら 1 章扱い）。"""
    heading = re.compile(r"^\s*(第[0-9０-９一二三四五六七八九十百]+章.*|#+.*)$")
    chapters: list[tuple[int, str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if heading.match(line):
            if current:
                chapters.append((len(chapters) + 1, "\n".join(current).strip()))
            current = [line]
        else:
            current.append(line)
    if current and "\n".join(current).strip():
        chapters.append((len(chapters) + 1, "\n".join(current).strip()))
    return chapters or [(1, text.strip())]


def chunk_text(text: str, target: int = CHUNK_TARGET) -> list[str]:
    """段落境界で target 文字前後のチャンクに分割。"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
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


def _slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem.lower()).strip("_")
    return s or "book"


def run(novel_path: Path, provider_name: str = "edge", resume: bool = False,
        no_tts: bool = False, model: str = "qwen3:4b") -> MemoryEngine:
    text = novel_path.read_text(encoding="utf-8")
    book_id = _slugify(novel_path.name)
    out_dir = OUT_DIR / book_id
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    memory = MemoryEngine(DB_PATH, book_id, title=novel_path.stem)
    analyzer = OllamaStoryAnalyzer(model=model)
    director = RuleBasedDirector()
    casting = CastingDirector()
    provider = get_provider(provider_name)

    memory.append_event("BOOK_IMPORTED", source=str(novel_path), chars=len(text))

    # ---- チャンク分割（章ごと → グローバル連番） ----
    chapters = split_chapters(text)
    chunks: list[dict] = []
    for chapter_no, chapter_text in chapters:
        for local_idx, chunk in enumerate(chunk_text(chapter_text)):
            chunks.append({"chapter": chapter_no, "index": len(chunks), "text": chunk})
    done_chunks = memory.analyzed_chunks() if resume else set()
    print(f"📖 {novel_path.name}: {len(chunks)} チャンク / {len(chapters)} 章 (resume={resume})")

    # ---- 解析 → 配役 → 演出 ----
    state: StoryState = memory.load_state()
    for item in chunks:
        gi, chapter = item["index"], item["chapter"]
        if gi in done_chunks:
            print(f"  ⏭ チャンク {gi + 1}（{chapter}章）は解析済み — スキップ")
            continue
        print(f"  🔍 解析中: チャンク {gi + 1}（{chapter}章, {len(item['text'])}文字）")
        analysis = analyzer.analyze(item["text"], state.summary(), gi)

        new_ids = merge_state(state, analysis)
        sc = analysis.get("scene") if isinstance(analysis.get("scene"), dict) else {}
        state.scene = str(sc.get("description") or state.scene)
        state.time_of_day = str(sc.get("time_of_day") or state.time_of_day)
        state.mood = str(sc.get("mood") or state.mood)
        memory.add_scene(chapter, gi, state.scene, state.time_of_day, state.mood)

        for cid in new_ids:
            ch = state.characters[cid]
            memory.upsert_character(ch, gi)
            memory.append_event("CHARACTER_CREATED", character=cid, name=ch.name)
            print(f"     ✓ CHARACTER_CREATED: {ch.name} ({ch.gender}, {ch.role})")
        for ch in state.characters.values():  # 既存キャラの traits 更新も反映
            if ch.id not in new_ids:
                memory.upsert_character(ch, gi)
        for ch in state.characters.values():
            for dst, label in ch.relationships.items():
                memory.upsert_relationship(ch.id, dst, label)

        for cid in casting.assign_voices(state):
            memory.save_voice_profile(state.characters[cid])
            memory.append_event("VOICE_ASSIGNED", character=cid,
                                voice=state.characters[cid].voice.voice_id)

        start_no = memory.count_segments()
        segments = build_segments(analysis, state, chapter, gi, start_no)
        for seg in segments:
            carry = memory.get_carryover(seg.speaker, gi)
            directed = director.direct(seg, state, carryover=carry)
            memory.save_segment(directed)
            if seg.speaker != NARRATOR:
                memory.update_emotional_state(
                    seg.speaker, directed.performance.emotion,
                    directed.performance.intensity, gi)
                memory.add_memory(
                    gi, seg.speaker, "emotion", directed.performance.emotion,
                    directed.performance.intensity,
                    f"{state.characters[seg.speaker].name}: "
                    f"{directed.performance.emotion}({directed.performance.intensity:.1f})「{seg.text[:40]}」")
            memory.add_memory(gi, None, "text", directed.performance.emotion,
                              directed.performance.intensity, seg.text)
            memory.append_event("SEGMENT_DIRECTED", segment=seg.id, speaker=seg.speaker,
                                emotion=directed.performance.emotion,
                                carryover=directed.performance.carryover)
            mark = " 🌫余韻適用" if directed.performance.carryover else ""
            if mark:
                print(f"     🌫 {seg.speaker}: {seg.emotion}→{directed.performance.emotion}"
                      f"({directed.performance.intensity:.2f}) {mark}")

        memory.mark_chunk_analyzed(gi, chapter)
        memory.append_event("ANALYZE_COMPLETED", chunk_index=gi, chapter=chapter,
                            segments=len(segments))
        counts: dict[str, int] = {}
        for seg in segments:
            counts[seg.type] = counts.get(seg.type, 0) + 1
        arc = " → ".join(s.emotion for s in segments[-6:])
        print(f"     ✓ {len(segments)} セグメント {counts}  感情アーク末尾: {arc}")

    return memory


def produce(memory: MemoryEngine, provider_name: str = "edge", resume: bool = False,
            no_tts: bool = False) -> None:
    """契約 JSON エクスポート → TTS → 連結（DB が唯一の情報源）。"""
    out_dir = OUT_DIR / memory.book_id
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    provider = get_provider(provider_name)

    exported = export_contracts(memory, out_dir)
    print(f"  ✓ performance.json / characters.json / story_state.json 保存（{exported} セグメント, 検証OK）")

    segments = memory.load_segments()
    done_audio = memory.audio_done() if resume else set()
    if not no_tts:
        todo = [s for s in segments if s.id not in done_audio and s.performance]
        for seg in todo:
            mp3 = audio_dir / f"{seg.id}.mp3"
            provider.synthesize(seg.text, seg.performance, mp3)  # type: ignore[arg-type]
            memory.set_audio(seg.id, str(mp3))
            memory.append_event("AUDIO_GENERATED", segment=seg.id)
        print(f"  🎙 TTS: {len(todo)} セグメント新規合成（DB記録済み {len(done_audio)}）")

    parts = memory.audio_paths()
    if parts:
        wav = out_dir / "audiobook.wav"
        concat_audio([Path(p) for _, p in parts], wav)
        duration = probe_duration(wav)
        memory.append_event("EXPORT_COMPLETED", output=str(wav), duration=duration)
        print(f"  🎧 {wav}（{duration:.1f} 秒）" if duration else f"  🎧 {wav}")


def export_contracts(memory: MemoryEngine, out_dir: Path) -> int:
    segments = memory.load_segments()
    state = memory.load_state()
    perf_doc = {
        "book_id": memory.book_id,
        "segments": [
            {"id": s.id, "type": s.type, "speaker": s.speaker, "text": s.text,
             "emotion": s.emotion, "intensity": s.intensity,
             "chapter": s.chapter, "chunk_index": s.chunk_index,
             "performance": s.performance.model_dump() if s.performance else None}
            for s in segments
        ],
    }
    errors = validate_performance_doc(perf_doc)
    if errors:
        raise SystemExit("performance.json 検証エラー: " + "; ".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "performance.json").write_text(
        json.dumps(perf_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    chars_doc = [
        {"id": c.id, "name": c.name, "gender": c.gender, "role": c.role,
         "traits": c.traits, "relationships": c.relationships,
         "voice": c.voice.model_dump() if c.voice else None,
         "last_emotion": c.last_emotion, "last_intensity": c.last_intensity}
        for c in state.characters.values()]
    (out_dir / "characters.json").write_text(
        json.dumps({"characters": chars_doc}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "story_state.json").write_text(
        json.dumps({"scene": state.scene, "time_of_day": state.time_of_day,
                    "mood": state.mood, "characters": list(state.characters)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return len(segments)


def show_stats(memory: MemoryEngine) -> None:
    print(f"📚 book: {memory.book_id}")
    for t in ("BOOK_IMPORTED", "CHARACTER_CREATED", "VOICE_ASSIGNED",
              "ANALYZE_COMPLETED", "SEGMENT_DIRECTED", "AUDIO_GENERATED",
              "EXPORT_COMPLETED"):
        n = memory.count_events(t)
        if n:
            print(f"  {t}: {n}")
    print(f"  events 総数: {memory.count_events()}")
    print("\n直近のイベント:")
    for row in memory.events_tail(10):
        print(f"  [{row['ts']}] {row['type']} {row['payload']}")


def main() -> None:
    _setup_stdio()
    ap = argparse.ArgumentParser(description="AIStoryActingEngine Phase 1")
    ap.add_argument("novel", nargs="?", type=Path, help="小説テキストファイル")
    ap.add_argument("--provider", default="edge", choices=["edge", "aivis"])
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--resume", action="store_true", help="DB の進捗から再開")
    ap.add_argument("--search", metavar="QUERY", help="FTS5 全文検索デモ")
    ap.add_argument("--stats", action="store_true", help="Event Log 統計を表示")
    args = ap.parse_args()

    if args.search:
        from memory import _fts_query

        rows = MemoryEngine(DB_PATH, "demo").conn.execute(
            """SELECT book_id, chunk_index, character_id, kind,
                      snippet(memories_fts, 0, '<<', '>>', '…', 8) AS hit
               FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT 10""",
            (_fts_query(args.search),)).fetchall()
        print(f"🔎 FTS5 検索: '{args.search}' → {len(rows)} 件")
        for r in rows:
            print(f"  [{r['book_id']} ch{r['chunk_index']} {r['kind']}] {r['hit']}")
        return

    if not args.novel:
        ap.error("小説ファイルを指定するか --search / --stats を使ってください")
    memory = run(args.novel, provider_name=args.provider, resume=args.resume,
                 no_tts=args.no_tts, model=args.model)
    produce(memory, provider_name=args.provider, resume=args.resume, no_tts=args.no_tts)
    show_stats(memory)


def resolve_speaker(raw: object, state: StoryState) -> str:
    """LLM の speaker 出力を正規化（名前でも id でも受ける）。"""
    if raw is None:
        return NARRATOR
    s = str(raw).strip()
    if not s or s == "narrator":
        return NARRATOR
    cid = normalize_id(s)
    if cid in state.characters:
        return cid
    for ch in state.characters.values():
        if ch.name == s or ch.id == s:
            return ch.id
    return NARRATOR


def build_segments(analysis: dict, state: StoryState, chapter: int,
                   chunk_index: int, start_no: int) -> list[Segment]:
    segments: list[Segment] = []
    for i, raw in enumerate(analysis.get("segments") or []):
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        segment_type = normalize_segment_type(raw.get("type"))
        speaker = resolve_speaker(raw.get("speaker"), state)
        if speaker == NARRATOR and segment_type in ("dialogue", "inner_monologue"):
            segment_type = "narration"  # 話者不明の台詞は地の文扱いにフォールバック
        segments.append(Segment(
            id=f"seg_{start_no + i:03d}",
            type=segment_type,  # type: ignore[arg-type]
            speaker=speaker,
            text=text,
            emotion=normalize_emotion(raw.get("emotion")),
            intensity=clamp(raw.get("intensity", 0.3), 0.0, 1.0),
            chapter=chapter,
            chunk_index=chunk_index,
        ))
    return segments


if __name__ == "__main__":
    main()
