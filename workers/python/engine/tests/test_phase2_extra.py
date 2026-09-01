"""Phase 2 単体テスト（後半）。test_phase2.py から run_rest() で呼ばれる。"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from analyzer import merge_state
from director import (CastingDirector, CharacterAwareDirector, INTERNAL_POOL,
                      VOICE_POOL)
from memory import MemoryEngine
from models import Character, Dossier, Segment, StoryState

from _common import check
from test_phase2 import make_state


def test_internal_voice() -> None:
    print("[4] External / Internal のデュアルボイス")
    director = CharacterAwareDirector()
    state = make_state()

    spoken = Segment(id="seg_002", type="dialogue", speaker="haruto",
                     text="平気だよ。", emotion="calm", intensity=0.4)
    inner = Segment(id="seg_003", type="inner_monologue", speaker="haruto",
                    text="本当は平気じゃない。", emotion="anxious", intensity=0.6)

    d_spoken = Dossier(character=state.characters["haruto"])
    d_inner = Dossier(character=state.characters["haruto"])

    p_spoken = director.direct(spoken, d_spoken).performance
    p_inner = director.direct(inner, d_inner).performance
    check("台詞は external 声", p_spoken.voice == "voice_01" and p_spoken.voicing == "external")
    check("心の声は internal 声", p_inner.voice == "voice_01i" and p_inner.voicing == "internal")
    check("internal は external より静か", p_inner.volume < p_spoken.volume)
    check("narrator は narrator voicing",
          director.direct(
              Segment(id="seg_004", type="narration", speaker="narrator", text="教室に夕日が差す。"),
              Dossier(character=Character(id="narrator", name="ナレーター")),
          ).performance.voicing == "narrator")


def test_baseline_and_carryover() -> None:
    print("[5] 感情の基調 + 余韻")
    director = CharacterAwareDirector()
    state = make_state()

    neutral = Segment(id="seg_005", type="dialogue", speaker="haruto",
                      text="うん。", emotion="neutral", intensity=0.2)
    p = director.direct(neutral, Dossier(character=state.characters["haruto"])).performance
    check("neutral が anxious 基調に滲む",
          p.emotion == "anxious" and p.baseline and p.intensity > 0.2,
          f"emotion={p.emotion} baseline={p.baseline} intensity={p.intensity}")

    # 余韻は基調より優先される
    carry = Dossier(character=state.characters["haruto"],
                    carryover=("angry", 0.9))
    p2 = director.direct(neutral, carry).performance
    check("余韻(angry)は基調に勝つ", p2.emotion == "angry" and p2.carryover and not p2.baseline)

    # 基調が neutral なキャラは neutral のまま
    plain = Character(id="kenji", name="賢人", voice=VOICE_POOL[0],
                      voice_internal=INTERNAL_POOL[0])
    p3 = director.direct(neutral, Dossier(character=plain)).performance
    check("基調なしは neutral 維持", p3.emotion == "neutral" and not p3.baseline)


def test_casting_llm_and_fallback() -> None:
    print("[6] LLM キャスティング + ルールフォールバック")
    state = StoryState()
    state.characters["saki"] = Character(
        id="saki", name="紗希", gender="female", age="elder", role="side",
        personality=["dignified"], speech_style="formal")

    def good_suggest(profile):
        return {
            "external": {"voice_id": "voice_03", "pitch": -0.05, "pace": 0.9},
            "internal": {"voice_id": "voice_04i", "pitch": -0.2, "pace": 0.85},
        }

    def bad_suggest(profile):
        return {"external": {"voice_id": "voice_99"}}

    casting = CastingDirector()
    casting.assign_voices(state, suggest=good_suggest)
    check("LLM 提案の external を採用", state.characters["saki"].voice.voice_id == "voice_03")
    check("LLM 提案の internal を採用",
          state.characters["saki"].voice_internal.voice_id == "voice_04i")
    check("pitch 微調整が反映", state.characters["saki"].voice.base_pitch == -0.05)

    state2 = StoryState()
    state2.characters["ken"] = Character(id="ken", name="賢人", gender="male", age="young")
    casting.assign_voices(state2, suggest=bad_suggest)
    check("不正提案はルールへフォールバック",
          state2.characters["ken"].voice.voice_id == "voice_01")
    check("internal も割当済み", state2.characters["ken"].voice_internal is not None)

    state3 = StoryState()
    state3.characters["mio"] = Character(id="mio", name="澪", gender="female", age="young")
    casting.assign_voices(state3)  # LLM なし
    check("LLM なしでもルール配役", state3.characters["mio"].voice.gender == "female")


def test_merge_state_phase2() -> None:
    print("[7] merge_state の Phase 2 拡張")
    state = StoryState()
    analysis = {
        "characters": [
            {"id": "yuki", "name": "由紀", "gender": "female", "age": "young",
             "role": "main", "traits": ["冷静"], "personality": ["calm", "blunt"],
             "speech_style": "rough", "emotional_baseline": "calm",
             "emotional_range": 0.3,
             "relationships": [{"target": "taro", "type": "hate", "label": "因縁"}]},
        ],
    }
    merge_state(state, analysis)
    ch = state.characters["yuki"]
    check("personality 取り込み", ch.personality == ["calm", "blunt"])
    check("speech_style 正規化", ch.speech_style == "rough")
    check("emotional_baseline 取り込み", ch.emotional_baseline == "calm")
    check("emotional_range 取り込み", ch.emotional_range == 0.3)
    check("関係を型付きで取り込み", ch.relationships["taro"].type == "despises")


def test_migrate_from_phase1_db() -> None:
    print("[8] Phase 1 DB からのマイグレーション")
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "old.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
        CREATE TABLE characters(book_id TEXT, id TEXT, name TEXT, gender TEXT,
          age TEXT, role TEXT, traits TEXT, voice_json TEXT, first_chunk INTEGER,
          last_emotion TEXT, last_intensity REAL, last_chunk INTEGER,
          PRIMARY KEY(book_id, id));
        CREATE TABLE relationships(book_id TEXT, src_id TEXT, dst_id TEXT, label TEXT,
          PRIMARY KEY(book_id, src_id, dst_id));
        INSERT INTO characters VALUES('b','old','旧','male','adult','main','[]',NULL,0,NULL,NULL,NULL);
        """)
        conn.commit()
        conn.close()
        mem = MemoryEngine(db, "b")
        try:
            cols = {r["name"] for r in mem.conn.execute("PRAGMA table_info(characters)")}
            check("characters に新列が追加", {"personality", "speech_style", "baseline",
                                              "erange", "voice_internal_json"} <= cols)
            relcols = {r["name"] for r in mem.conn.execute("PRAGMA table_info(relationships)")}
            check("relationships に type 列が追加", "type" in relcols)
            state = mem.load_state()
            check("旧データが読める", state.characters["old"].name == "旧")
        finally:
            mem.close()


def run_rest() -> None:
    test_internal_voice()
    test_baseline_and_carryover()
    test_casting_llm_and_fallback()
    test_merge_state_phase2()
    test_migrate_from_phase1_db()
