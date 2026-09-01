"""Phase 2: Character Intelligence / Voice Director の単体テスト。

実行: python tests/test_phase2.py（LLM・TTS 不使用の純ロジック検証）
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import schema as contracts
from analyzer import merge_state
from _common import check, passed
from director import (CastingDirector, CharacterAwareDirector, INTERNAL_POOL,
                      NARRATOR, VOICE_POOL)
from memory import MemoryEngine
from models import Character, Dossier, Relationship, Segment, StoryState


def make_state() -> StoryState:
    state = StoryState(scene="夕暮れの教室", mood="穏やか")
    state.characters["haruto"] = Character(
        id="haruto", name="春人", gender="male", age="young", role="main",
        personality=["shy", "kind"], speech_style="polite",
        emotional_baseline="anxious", emotional_range=0.7,
        voice=VOICE_POOL[0], voice_internal=INTERNAL_POOL[0])
    state.characters["aoi"] = Character(
        id="aoi", name="葵", gender="female", age="young", role="main",
        personality=["cheerful"], speech_style="casual",
        voice=VOICE_POOL[1], voice_internal=INTERNAL_POOL[1])
    state.characters["haruto"].relationships["aoi"] = Relationship(
        type="loves", label="想いを寄せる相手")
    return state


def test_relationship_vocabulary() -> None:
    print("[1] 関係語彙の正規化")
    check("hate→despises", contracts.normalize_relationship("hate") == "despises")
    check("classmate→colleague", contracts.normalize_relationship("classmate") == "colleague")
    check("不明語は other", contracts.normalize_relationship("skipped") == "other")
    check("loves はそのまま", contracts.normalize_relationship("loves") == "loves")


def test_typed_graph_and_dossier() -> None:
    print("[2] 有向グラフ + Dossier（Memory Engine）")
    with tempfile.TemporaryDirectory() as td:
        mem = MemoryEngine(Path(td) / "t.db", "test_book")
        try:
            state = make_state()
            for cid in ("haruto", "aoi"):
                mem.upsert_character(state.characters[cid], 0)
            mem.upsert_relationship("haruto", "aoi", "想いを寄せる相手", "loves")
            mem.upsert_relationship("aoi", "haruto", "同級生", "friend")

            rel = mem.get_relationship("haruto", "aoi")
            check("haruto→aoi は loves", rel is not None and rel.type == "loves")
            rel_rev = mem.get_relationship("aoi", "haruto")
            check("逆向きは上書きされない(直接エッジ優先)",
                  rel_rev is not None and rel_rev.type == "friend")

            # 非対称の逆向きフォールバック
            mem.upsert_relationship("haruto", "kenji", "先輩", "respects")
            rel_fb = mem.get_relationship("kenji", "haruto")
            check("respects の逆は other", rel_fb is not None and rel_fb.type == "other")

            # 対称関係の自動生成
            mem.upsert_relationship("aoi", "kenji", "仲良し", "friend")
            rel_sym = mem.get_relationship("kenji", "aoi")
            check("friend は対称で自動生成", rel_sym is not None and rel_sym.type == "friend")

            d = mem.get_dossier("haruto", "aoi", 3, state)
            check("Dossier が組める", d is not None)
            assert d is not None
            check("関係が載る", d.relationship is not None and d.relationship.type == "loves")
            check("聞き手が載る", d.listener is not None and d.listener.id == "aoi")
            check("感情基調が載る", d.character.emotional_baseline == "anxious")

            # resume 復元
            state2 = mem.load_state()
            check("load_state で personality 復元",
                  state2.characters["haruto"].personality == ["shy", "kind"])
            check("load_state で relationship 型付き復元",
                  state2.characters["haruto"].relationships["aoi"].type == "loves")
            check("load_state で internal voice 復元",
                  state2.characters["haruto"].voice_internal is not None and
                  state2.characters["haruto"].voice_internal.voice_id == "voice_01i")
        finally:
            mem.close()


def test_relationship_dependent_acting() -> None:
    print("[3] 関係依存の演じ分け（同じ台詞・別の聞き手）")
    director = CharacterAwareDirector()
    state = make_state()
    seg = Segment(id="seg_001", type="dialogue", speaker="haruto",
                  text="大丈夫だよ。", emotion="calm", intensity=0.3)

    loves = Dossier(character=state.characters["haruto"],
                    listener=state.characters["aoi"],
                    relationship=Relationship(type="loves"))
    enemy = Dossier(character=state.characters["haruto"],
                    listener=Character(id="kenji", name="賢人"),
                    relationship=Relationship(type="enemy"))

    p_love = director.direct(seg, loves).performance
    p_hate = director.direct(seg, enemy).performance
    check("loves は柔らかい(pitch 高)",
          p_love.pitch > p_hate.pitch,
          f"love={p_love.pitch} vs hate={p_hate.pitch}")
    check("enemy は張り上げる(volume 大)",
          p_hate.volume > p_love.volume,
          f"love={p_love.volume} vs hate={p_hate.volume}")
    check("performance に関係が記録される",
          p_love.relationship == "loves" and p_hate.relationship == "enemy")


if __name__ == "__main__":
    from test_phase2_extra import run_rest  # noqa: F401

    test_relationship_vocabulary()
    test_typed_graph_and_dossier()
    test_relationship_dependent_acting()
    run_rest()
    print(f"\n全 {passed()} 項目 OK ✅")
