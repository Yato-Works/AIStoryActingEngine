"""Dynamic Voice Registry, Casting Override, and Series Inheritance のテスト。"""

import json
from pathlib import Path
import tempfile
import pytest

from models import Character, CharacterCasting, Series, StoryState, VoiceProfile
from memory import MemoryEngine
from voices import sync_builtin_voices, resolve_voice_profile, all_profiles
from director import CastingDirector
from worker import EngineWorker


@pytest.fixture
def tmp_db(tmp_path):
    db_file = tmp_path / "test_story.db"
    mem = MemoryEngine(db_file, "book_test", title="テスト本")
    sync_builtin_voices(mem)
    yield mem, db_file
    mem.close()


def test_voice_registry_crud(tmp_db):
    mem, db_file = tmp_db
    # 初期ビルトインボイスの確認
    builtins = mem.list_voice_profiles(source="builtin")
    assert len(builtins) >= 7

    # Test_Voice1 カスタムボイスを登録
    custom_voice = VoiceProfile(
        voice_id="voice_test1_custom",
        label="Test_Voice1_渋みモノローグ",
        gender="male",
        age="adult",
        base_pitch=-0.15,
        base_pace=0.90,
        sbv2_model_name="jvnv-M1-jp",
        sbv2_style="Neutral",
        source="user",
        tags=["Test_Voice1", "モノローグ", "低音", "渋い"],
        description="渋みと落ち着きのある低音ボイス",
    )
    mem.register_voice_profile(custom_voice)

    # 取得
    fetched = mem.get_voice_profile("voice_test1_custom")
    assert fetched is not None
    assert fetched.label == "Test_Voice1_渋みモノローグ"
    assert "Test_Voice1" in fetched.tags

    # 一覧
    user_voices = mem.list_voice_profiles(source="user")
    assert any(v.voice_id == "voice_test1_custom" for v in user_voices)

    # ビルトインは削除不可
    assert not mem.delete_voice_profile("voice_01")
    # ユーザーボイスは削除可能
    assert mem.delete_voice_profile("voice_test1_custom")
    assert mem.get_voice_profile("voice_test1_custom") is None


def test_series_and_book_association(tmp_db):
    mem, db_file = tmp_db
    series = Series(
        id="series_arcadia",
        title="星詠みのアルカディア",
        description="王道ファンタジーシリーズ",
        castings={
            "語り手": {"voice_id": "voice_06", "voice_internal_id": "voice_06i"},
            "アレク": {"voice_id": "voice_05", "voice_internal_id": "voice_06i"},
        },
    )
    mem.upsert_series(series)

    fetched = mem.get_series("series_arcadia")
    assert fetched is not None
    assert fetched.title == "星詠みのアルカディア"
    assert fetched.castings["語り手"]["voice_id"] == "voice_06"

    # 書籍にシリーズを紐付け
    mem.set_book_series("book_test", "series_arcadia")
    assert mem.get_book_series_id("book_test") == "series_arcadia"


def test_casting_priorities(tmp_db):
    mem, db_file = tmp_db

    # シリーズを設定
    series = Series(
        id="series_arcadia",
        title="星詠みのアルカディア",
        castings={
            "アレク": {"voice_id": "voice_05", "voice_internal_id": "voice_06i"},
        },
    )
    mem.upsert_series(series)
    mem.set_book_series("book_test", "series_arcadia")

    # 手動指定: エレナは voice_03 (落ち着いた女性) にロック
    mem.set_character_casting(CharacterCasting(
        character_id="elena",
        character_name="エレナ",
        voice_id="voice_03",
        voice_internal_id="voice_03i",
        is_locked=True,
    ))

    # ストーリー状態（キャラ3人）
    # 1. アレク（シリーズ設定あり）
    # 2. エレナ（手動指定あり）
    # 3. ゴードン（手動もシリーズもなし → スマートマッチング）
    state = StoryState()
    state.characters["alec"] = Character(
        id="alec", name="アレク", gender="male", age="child", role="protagonist")
    state.characters["elena"] = Character(
        id="elena", name="エレナ", gender="female", age="young", role="mentor")
    state.characters["gordon"] = Character(
        id="gordon", name="ゴードン", gender="male", age="adult", role="rival",
        personality=["渋い", "圧倒的強者"])

    casting = CastingDirector()
    assigned = casting.assign_voices(state, memory=mem)

    assert len(assigned) == 3

    # アレクはシリーズ設定の voice_05 (少年ボイス) が適用されていること
    assert state.characters["alec"].voice.voice_id == "voice_05"

    # エレナは手動指定の voice_03 が適用されていること
    assert state.characters["elena"].voice.voice_id == "voice_03"

    # ゴードンは成人男性向けボイスが選ばれていること
    assert state.characters["gordon"].voice.gender == "male"
    assert state.characters["gordon"].voice.voice_id in ("voice_04", "voice_06", "voice_01")


def test_worker_rpc_methods(tmp_db):
    mem, db_file = tmp_db
    worker = EngineWorker(db_file)

    # 1. list_voice_profiles
    res = worker.dispatch("list_voice_profiles", {})
    assert "profiles" in res
    assert len(res["profiles"]) >= 7

    # 2. save_voice_profile
    new_profile = {
        "voice_id": "voice_test2_custom",
        "label": "Test_Voice2_少年主人公",
        "gender": "male",
        "age": "child",
        "base_pitch": 0.15,
        "base_pace": 1.05,
        "sbv2_model_name": "jvnv-F1-jp",
        "sbv2_style": "Neutral",
        "tags": ["Test_Voice2", "少年", "少年主人公"],
        "description": "少年主人公向けカスタムボイス",
    }
    save_res = worker.dispatch("save_voice_profile", {"profile": new_profile})
    assert save_res["ok"] is True
    assert save_res["voice_id"] == "voice_test2_custom"

    # 3. get_castings & assign_casting
    # テスト用のキャラをDBに追加
    ch = Character(id="alec", name="アレク", gender="male", age="child")
    mem.upsert_character(ch, 0)

    cast_res = worker.dispatch("get_castings", {"book_id": "book_test"})
    assert "castings" in cast_res
    assert len(cast_res["castings"]) >= 1

    assign_res = worker.dispatch("assign_casting", {
        "book_id": "book_test",
        "character_id": "alec",
        "voice_id": "voice_test2_custom",
        "is_locked": True,
    })
    assert assign_res["ok"] is True
    assert assign_res["voice_id"] == "voice_test2_custom"

    # 4. list_series & upsert_series
    series_data = {
        "id": "series_test_01",
        "title": "テストシリーズ",
        "description": "テストシリーズ説明",
        "castings": {"alec": {"voice_id": "voice_test2_custom"}},
    }
    s_res = worker.dispatch("upsert_series", {"series": series_data})
    assert s_res["ok"] is True

    s_list = worker.dispatch("list_series", {})
    assert any(s["id"] == "series_test_01" for s in s_list["series"])


def test_llm_casting_with_assert(tmp_db):
    """suggest（LLMキャスティング提案）が正しく採用され、不正提案・提案なしでフォールバックすることを assert で検証。

    test_phase2_extra.py の同名テスト（check() ベース）は失敗を握りつぶすため、
    例外で失敗する assert ベースの回帰テストとして追加する。
    """
    mem, db_file = tmp_db

    def good_suggest(profile):
        return {
            "external": {"voice_id": "voice_03", "pitch": -0.05, "pace": 0.9},
            "internal": {"voice_id": "voice_04i", "pitch": -0.2, "pace": 0.85},
        }

    state = StoryState()
    state.characters["saki"] = Character(
        id="saki", name="紗希", gender="female", age="elder", role="side")
    assigned = CastingDirector().assign_voices(state, suggest=good_suggest, memory=mem)
    assert "saki" in assigned
    assert state.characters["saki"].voice.voice_id == "voice_03"
    assert state.characters["saki"].voice.base_pitch == pytest.approx(-0.05)
    assert state.characters["saki"].voice_internal.voice_id == "voice_04i"
    assert state.characters["saki"].voice_internal.base_pitch == pytest.approx(-0.2)

    # 不正な提案（存在しない voice_id）は自動マッチングへフォールバック
    def bad_suggest(profile):
        return {"external": {"voice_id": "voice_99"}}

    state2 = StoryState()
    state2.characters["ken"] = Character(
        id="ken", name="賢人", gender="male", age="young")
    CastingDirector().assign_voices(state2, suggest=bad_suggest)
    assert state2.characters["ken"].voice.voice_id == "voice_01"
    assert state2.characters["ken"].voice_internal is not None

    # suggest なし（実運用のメイン経路）でもルール/タグマッチで割り当てられる
    state3 = StoryState()
    state3.characters["mio"] = Character(
        id="mio", name="澪", gender="female", age="young")
    CastingDirector().assign_voices(state3)
    assert state3.characters["mio"].voice.gender == "female"
    assert state3.characters["mio"].voice_internal is not None
