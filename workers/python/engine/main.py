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
from audio import concat_audio, export_m4b, probe_duration
from director import CastingDirector, NARRATOR, RuleBasedDirector, CharacterAwareDirector
from jobs import CANCELLED, COMPLETED, FAILED, JobCancelled, JobManager, RUNNING
from memory import MemoryEngine
from models import Character, Dossier, Segment, StoryState, VoiceProfile, VoiceState
from schema import clamp, normalize_emotion, normalize_segment_type, validate_performance_doc
from tts import get_provider
from human_voice import render_segment, seed_for
from voices import NARRATOR_VOICE, NARRATOR_VOICE_INTERNAL
from scene_context import (SceneReaction, decay_state, scene_events_from_analysis,
                           tone_for_events)

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


def _persist_characters(memory: MemoryEngine, state: StoryState,
                        new_ids: list[str], chunk_index: int) -> None:
    """解析で得たキャラクターを永続化（新規はイベント+ログ）。"""
    for cid in new_ids:
        ch = state.characters[cid]
        memory.upsert_character(ch, chunk_index)
        memory.append_event("CHARACTER_CREATED", character=cid, name=ch.name)
        print(f"     ✓ CHARACTER_CREATED: {ch.name} ({ch.gender}, {ch.role}, "
              f"話し方={ch.speech_style or '?'}, 基調={ch.emotional_baseline})")
    for ch in state.characters.values():  # 既存キャラの traits 更新も反映
        if ch.id not in new_ids:
            memory.upsert_character(ch, chunk_index)


def _persist_relationships(memory: MemoryEngine, state: StoryState,
                           chunk_index: int) -> None:
    """関係グラフの永続化（新規・既存キャラ両方。イベントは新規エッジのみ）。"""
    known_pairs = memory.relationship_pairs()
    for ch in state.characters.values():
        for dst, rel in ch.relationships.items():
            memory.upsert_relationship(ch.id, dst, rel.label, rel.type)
            if (ch.id, dst) not in known_pairs:
                known_pairs.add((ch.id, dst))
                memory.append_event("RELATIONSHIP_CREATED", src=ch.id, dst=dst,
                                    type=rel.type, label=rel.label)
                print(f"     ✓ RELATIONSHIP_CREATED: {ch.name} →{rel.type}→ {dst}")


def _cast_characters(memory: MemoryEngine, state: StoryState,
                     casting: CastingDirector, analyzer, chunk_index: int) -> None:
    """未配役キャラに External/Internal の声を割り当てて永続化する。"""
    newly_cast = casting.assign_voices(state, suggest=analyzer.suggest_voice)
    for cid in newly_cast:
        ch = state.characters[cid]
        memory.save_voice_profile(ch)
        memory.append_event("VOICE_ASSIGNED", character=cid,
                            voice=ch.voice.voice_id if ch.voice else "",
                            voice_internal=(ch.voice_internal.voice_id
                                            if ch.voice_internal else ""))
    if newly_cast:
        memory.append_event("CASTING_COMPLETED", cast=newly_cast)
        summary = ", ".join(
            f"{state.characters[c].name}"
            f"[{state.characters[c].voice.voice_id if state.characters[c].voice else '?'}/"
            f"{state.characters[c].voice_internal.voice_id if state.characters[c].voice_internal else '?'}]"
            for c in newly_cast)
        print(f"     ✓ CASTING_COMPLETED: {summary}")


def _direct_segments(memory: MemoryEngine, state: StoryState,
                     director: CharacterAwareDirector, rule_director: RuleBasedDirector,
                     segments: list[Segment], chunk_index: int) -> None:
    """セグメントごとに演出 → 保存 → 感情記憶 → イベント → 進捗表示。"""
    prev_speaker: str | None = None  # 直前の発話者を聞き手候補に使う
    for seg in segments:
        if seg.speaker == NARRATOR:
            dossier = Dossier(character=Character(id=NARRATOR, name="ナレーター"))
            directed = director.direct(seg, dossier)
        else:
            listener_id = (prev_speaker
                           if (prev_speaker and prev_speaker != seg.speaker
                               and seg.type == "dialogue") else None)
            dossier = memory.get_dossier(seg.speaker, listener_id, chunk_index, state)
            if dossier is None:
                directed = rule_director.direct(seg, state)
            else:
                directed = director.direct(seg, dossier)
        prev_speaker = seg.speaker
        memory.save_segment(directed)
        if seg.speaker != NARRATOR:
            memory.update_emotional_state(
                seg.speaker, directed.performance.emotion,
                directed.performance.intensity, chunk_index)
            memory.add_memory(
                chunk_index, seg.speaker, "emotion", directed.performance.emotion,
                directed.performance.intensity,
                f"{state.characters[seg.speaker].name}: "
                f"{directed.performance.emotion}({directed.performance.intensity:.1f})「{seg.text[:40]}」")
        memory.add_memory(chunk_index, None, "text", directed.performance.emotion,
                          directed.performance.intensity, seg.text)
        memory.append_event("SEGMENT_DIRECTED", segment=seg.id, speaker=seg.speaker,
                            emotion=directed.performance.emotion,
                            voicing=directed.performance.voicing,
                            relationship=directed.performance.relationship,
                            carryover=directed.performance.carryover,
                            baseline=directed.performance.baseline)
        marks = ""
        if directed.performance.carryover:
            marks += " 🌫余韻"
        if directed.performance.baseline:
            marks += " 🎨基調"
        if directed.performance.voicing == "internal":
            marks += " 🧠内面声"
        if directed.performance.relationship:
            marks += f" 💞{directed.performance.relationship}"
        if marks:
            print(f"    {marks} {seg.speaker}: {seg.emotion}→{directed.performance.emotion}"
                  f"({directed.performance.intensity:.2f}, voice={directed.performance.voice})")


def _apply_scene_events(memory: MemoryEngine, state: StoryState,
                        events: list, chunk_index: int) -> None:
    """SceneEvent -> VoiceState デルタ適用 + 永続化（3.5Q Scene Context Integration）。

    因果は「出来事 → 状態変化 → 以降の演技」。LLM に演技を直接させるのではなく、
    「誰の状態がどれだけ変わったか」だけを受け取り、既存の Prosody/Breath 機構に委ねる。

    - targets のキャラはフル効果
    - それ以外は「まず 1 チャンク分の State Decay → 減衰付きの周囲の空気を上乗せ」。
      こうすると別キャラのイベントチャンクでも、前チャンクまでの状態が自然に回帰する
    - 変化は voice_states テーブルに永続化 + VOICE_STATE_CHANGED イベントとして記録
    """
    tone = tone_for_events(events)
    for ev in events:
        memory.add_scene_event(ev.chunk_index or chunk_index, ev.category,
                               ev.description, ev.intensity, ev.targets, tone)
    targeted = {cid for ev in events for cid in ev.targets}
    changed: list[str] = []
    for cid, _ch in state.characters.items():
        cur = memory.get_voice_state(cid) or VoiceState()
        base = cur if cid in targeted else decay_state(cur)
        new = base
        for ev in events:
            new = SceneReaction(ev).for_character(cid, base=new)
        if new != cur:
            memory.save_voice_state(cid, new, chunk_index)
            state.characters[cid].voice_state = new
            changed.append(cid)
    if events:
        summary = ", ".join(
            f"{ev.category}({ev.intensity:.2f}→{','.join(ev.targets) or '-'})"
            for ev in events)
        print(f"     ✓ SCENE_EVENT [{tone}]: {summary}")
    if changed:
        print(f"     〜 VoiceState 更新: {', '.join(changed)}")


def analyze_book(novel_path: Path, memory: MemoryEngine, resume: bool = False,
                 model: str = "qwen3:4b", should_stop=None) -> None:
    """チャンク解析 → 配役 → 演出まで（Job System の analyze Step の本体）。

    should_stop() が True を返すと JobCancelled を raise する（協調的キャンセル）。
    """
    text = novel_path.read_text(encoding="utf-8")
    analyzer = OllamaStoryAnalyzer(model=model)
    director = CharacterAwareDirector()
    rule_director = RuleBasedDirector()  # narrator 等のフォールバック用
    casting = CastingDirector()

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
        if should_stop is not None and should_stop():
            raise JobCancelled("analyze をキャンセル")
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

        _persist_characters(memory, state, new_ids, gi)

        _persist_relationships(memory, state, gi)

        _cast_characters(memory, state, casting, analyzer, gi)

        start_no = memory.count_segments()
        segments = build_segments(analysis, state, chapter, gi, start_no)
        _direct_segments(memory, state, director, rule_director, segments, gi)

        # ---- Scene Context (3.5Q): 出来事 → VoiceState デルタ → 以降の演技へ ----
        events = scene_events_from_analysis(analysis,
                                            known_ids=set(state.characters),
                                            chunk_index=gi)
        _apply_scene_events(memory, state, events, gi)

        memory.mark_chunk_analyzed(gi, chapter)
        memory.append_event("ANALYZE_COMPLETED", chunk_index=gi, chapter=chapter,
                            segments=len(segments))
        counts: dict[str, int] = {}
        for seg in segments:
            counts[seg.type] = counts.get(seg.type, 0) + 1
        arc = " → ".join(s.emotion for s in segments[-6:])
        print(f"     ✓ {len(segments)} セグメント {counts}  感情アーク末尾: {arc}")


def run(novel_path: Path, provider_name: str = "edge", resume: bool = False,
        no_tts: bool = False, model: str = "qwen3:4b") -> MemoryEngine:
    """従来モードのエントリポイント（解析のみ実行し MemoryEngine を返す）。"""
    memory = MemoryEngine(DB_PATH, _slugify(novel_path.name), title=novel_path.stem)
    analyze_book(novel_path, memory, resume=resume, model=model)
    return memory


def _hve_profile_table(memory: MemoryEngine) -> dict[str, tuple[VoiceProfile, VoiceState]]:
    """HVE（3.5M）用の voice_id → (VoiceProfile, VoiceState) テーブルを組む（Phase 3.5P）。

    キャスティング結果（characters.voice / voice_internal）とナレーター固定声を
    1 つの辞書に集約する。VoiceState は 3.5Q で永続化された Scene Context 由来の
    状態を優先し、無ければデフォルトで演じる。
    """
    table: dict[str, tuple[VoiceProfile, VoiceState]] = {}
    state = memory.load_state()
    for ch in state.characters.values():
        st = memory.get_voice_state(ch.id) or ch.voice_state or VoiceState()
        if ch.voice is not None:
            table[ch.voice.voice_id] = (ch.voice, st)
        if ch.voice_internal is not None:
            table[ch.voice_internal.voice_id] = (ch.voice_internal, st)
    table.setdefault(NARRATOR_VOICE.voice_id, (NARRATOR_VOICE, VoiceState()))
    table.setdefault(NARRATOR_VOICE_INTERNAL.voice_id,
                     (NARRATOR_VOICE_INTERNAL, VoiceState()))
    return table


def synthesize_all(memory: MemoryEngine, provider_name: str = "edge",
                   resume: bool = False, report=None, should_stop=None,
                   hve: bool = False) -> int:
    """未合成セグメントを TTS（Job System の tts Step の本体）。

    hve=True で Human Voice Engine（3.5M）経由: Performance + VoiceProfile/State +
    Breath Engine で「演じてから」合成する（出力は常に .wav）。
    report(progress, checkpoint) で 1 セグメントごとに進捗を通知する。
    should_stop() が True を返すと JobCancelled（協調的キャンセル）。
    戻り値は新規合成したセグメント数。done-set（segments.audio_path）が
    真実源なので、途中で死んでも次回は続きから再開される。
    """
    out_dir = OUT_DIR / memory.book_id
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    provider = get_provider(provider_name)
    use_hve = hve
    _hve_profiles = _hve_profile_table(memory) if use_hve else {}

    segments = memory.load_segments()
    done_audio = memory.audio_done() if resume else set()
    todo = [s for s in segments if s.id not in done_audio and s.performance]
    ext = ".wav" if use_hve else getattr(provider, "ext", ".mp3")
    tone_cache: dict[int, str] = {}  # chunk_index -> scene tone (3.5Q)
    for i, seg in enumerate(todo, 1):
        if should_stop is not None and should_stop():
            raise JobCancelled("tts をキャンセル")
        clip = audio_dir / f"{seg.id}{ext}"
        if use_hve:
            tone = tone_cache.get(seg.chunk_index)
            if tone is None:
                tone = memory.scene_tone(seg.chunk_index)
                tone_cache[seg.chunk_index] = tone
            _prof, _st = _hve_profiles.get(
                seg.performance.voice,
                (VoiceProfile(voice_id=seg.performance.voice), VoiceState()))
            render_segment(seg, _prof, _st, provider, clip, seed=seed_for(seg.id),
                           tone=tone)
        else:
            provider.synthesize(seg.text, seg.performance, clip)  # type: ignore[arg-type]
        memory.set_audio(seg.id, str(clip))
        memory.append_event("AUDIO_GENERATED", segment=seg.id, hve=use_hve)
        if report:
            report(i, {"segment": seg.id})
    print(f"  🎙 TTS({provider.name}{' + HVE' if use_hve else ''}): "
          f"{len(todo)} セグメント新規合成（DB記録済み {len(done_audio)}）")
    return len(todo)


def export_audio(memory: MemoryEngine) -> list[tuple[str, str]]:
    """wav 連結 + チャプター付き M4B 生成（Job System の export Step の本体）。

    戻り値は生成した成果物の (kind, path) リスト。
    """
    out_dir = OUT_DIR / memory.book_id
    artifacts: list[tuple[str, str]] = []
    parts = memory.audio_paths()
    if not parts:
        return artifacts

    wav = out_dir / "audiobook.wav"
    concat_audio([Path(p) for _, p in parts], wav)
    duration = probe_duration(wav)
    memory.append_event("EXPORT_COMPLETED", output=str(wav), duration=duration)
    print(f"  🎧 {wav}（{duration:.1f} 秒）" if duration else f"  🎧 {wav}")
    artifacts.append(("wav", str(wav)))

    # ---- M4B（チャプター付きオーディオブック）----
    try:
        segs = memory.audio_segments()
        titles = memory.chapter_titles()
        m4b = export_m4b(
            [(sid, ch, Path(p)) for sid, ch, p in segs],
            out_dir / "audiobook.m4b",
            chapter_titles={k: f"第{k}章 {v[:40]}" for k, v in titles.items()},
            title=memory.book_title(),
        )
        duration = probe_duration(m4b)
        memory.append_event("EXPORT_COMPLETED", output=str(m4b),
                            duration=duration, format="m4b",
                            chapters=len(titles) or 1)
        print(f"  📕 {m4b}（チャプター {len(titles) or 1} つ"
              + (f", {duration:.1f} 秒" if duration else "") + "）")
        artifacts.append(("m4b", str(m4b)))
    except Exception as exc:  # M4B は付加成果物。失敗しても wav は残す
        print(f"  ⚠ M4B 生成をスキップ: {exc}")
    return artifacts


def produce(memory: MemoryEngine, provider_name: str = "edge", resume: bool = False,
            no_tts: bool = False, hve: bool = False) -> None:
    """契約 JSON エクスポート → TTS → 連結（DB が唯一の情報源）。"""
    out_dir = OUT_DIR / memory.book_id
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = export_contracts(memory, out_dir)
    print(f"  ✓ performance.json / characters.json / story_state.json 保存（{exported} セグメント, 検証OK）")

    if not no_tts:
        synthesize_all(memory, provider_name, resume=resume, hve=hve)
    export_audio(memory)


def run_pipeline_job(novel_path: Path, provider_name: str = "edge",
                     resume: bool = False, no_tts: bool = False,
                     model: str = "qwen3:4b", hve: bool = False,
                     should_stop=None) -> MemoryEngine:
    """小説処理を pipeline Job（analyze → tts → export）として実行する（ADR-0003）。

    中断・クラッシュ時は `--job --resume` で DB の done-set から再開する。
    should_stop() が True を返すと CANCELLED 遷移して終了する。
    """
    memory = MemoryEngine(DB_PATH, _slugify(novel_path.name), title=novel_path.stem)
    memory.append_event("BOOK_IMPORTED", source=str(novel_path),
                        chars=len(novel_path.read_text(encoding="utf-8")))
    jm = JobManager(memory)
    job_id, resumed = jm.resume_or_create(
        "pipeline", {"provider": provider_name, "model": model,
                     "novel": str(novel_path), "no_tts": no_tts, "hve": hve})
    if resumed:
        recovered = jm.recover_running_steps(job_id)
        print(f"♻ Job {job_id} を再開"
              + (f"（未完了 Step {recovered} 件をやり直し）" if recovered else ""))
    jm.transition(job_id, RUNNING)
    print(f"🧭 Job {job_id}: analyze → tts → export")

    def check() -> None:
        if should_stop is not None and should_stop():
            raise JobCancelled("キャンセル要求")

    try:
        check()
        jm.run_step(job_id, 1, "analyze",
                    lambda report: analyze_book(novel_path, memory,
                                                resume=resume, model=model,
                                                should_stop=should_stop))
        check()
        if no_tts:
            jm.ensure_step(job_id, 2, "tts")
            jm.finish_step(job_id, 2, skip=True)
            print("  ⏭ step 2(tts) は no-tts 指定のためスキップ")
        else:
            jm.run_step(job_id, 2, "tts",
                        lambda report: synthesize_all(memory, provider_name,
                                                      resume=resume, report=report,
                                                      should_stop=should_stop,
                                                      hve=hve),
                        progress_total=memory.count_segments())
        check()
        jm.run_step(job_id, 3, "export",
                    lambda report: (export_contracts(memory, OUT_DIR / memory.book_id),
                                    export_audio(memory))[1])
        jm.transition(job_id, COMPLETED)
        print(f"✅ Job {job_id} 完了")
    except JobCancelled:
        jm.transition(job_id, CANCELLED)
        print(f"🛑 Job {job_id} キャンセル")
        return memory
    except Exception as exc:
        jm.transition(job_id, FAILED, error=str(exc))
        print(f"❌ Job {job_id} 失敗: {exc}")
        raise
    return memory


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
        {"id": c.id, "name": c.name, "gender": c.gender, "age": c.age,
         "role": c.role, "traits": c.traits,
         "personality": c.personality, "speech_style": c.speech_style,
         "emotional_baseline": c.emotional_baseline,
         "emotional_range": c.emotional_range,
         "relationships": {k: v.model_dump() for k, v in c.relationships.items()},
         "voice": c.voice.model_dump() if c.voice else None,
         "voice_internal": (c.voice_internal.model_dump()
                            if c.voice_internal else None),
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
    ap = argparse.ArgumentParser(description="AIStoryActingEngine Phase 2")
    ap.add_argument("novel", nargs="?", type=Path, help="小説テキストファイル")
    ap.add_argument("--provider", default="edge", choices=["edge", "aivis", "sbv2"],
                    help="sbv2 は Style-Bert-VITS2 サーバ (localhost:5000) 必須")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--resume", action="store_true", help="DB の進捗から再開")
    ap.add_argument("--job", action="store_true",
                    help="Job System 経由で実行（analyze→tts→export を再開可能な Job に）")
    ap.add_argument("--hve", action="store_true",
                    help="Human Voice Engine（3.5M）で演技合成：prosody curve + breath で演じる")
    ap.add_argument("--search", metavar="QUERY", help="FTS5 全文検索デモ")
    ap.add_argument("--stats", action="store_true", help="Event Log 統計を表示")
    args = ap.parse_args()

    if args.search:
        from memory import _fts_query  # noqa: F401  (後方互換のために残す)

        rows = MemoryEngine(DB_PATH, "demo").search(args.search, with_book=True)
        print(f"🔎 FTS5 検索: '{args.search}' → {len(rows)} 件")
        for r in rows:
            print(f"  [{r['book_id']} ch{r['chunk_index']} {r['kind']}] {r['hit']}")
        return

    if not args.novel:
        ap.error("小説ファイルを指定するか --search / --stats を使ってください")
    if args.job:
        memory = run_pipeline_job(args.novel, provider_name=args.provider,
                                  resume=args.resume, no_tts=args.no_tts,
                                  model=args.model, hve=args.hve)
    else:
        memory = run(args.novel, provider_name=args.provider, resume=args.resume,
                     no_tts=args.no_tts, model=args.model)
        produce(memory, provider_name=args.provider, resume=args.resume,
                no_tts=args.no_tts, hve=args.hve)
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
