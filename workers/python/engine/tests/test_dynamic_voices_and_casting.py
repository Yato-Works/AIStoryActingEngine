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

    # 杉田智和風カスタムボイスを登録
    sugita_voice = VoiceProfile(
        voice_id="voice_sugita_custom",
        label="杉田智和風_渋みモノローグ",
        gender="male",
        age="adult",
        base_pitch=-0.15,
        base_pace=0.90,
        sbv2_model_name="jvnv-M1-jp",
        sbv2_style="Neutral",
        source="user",
        tags=["杉田智和風", "前世の男", "低音", "渋い"],
        description="無職転生の前世の男にぴったりの低音ボイス",
    )
    mem.register_voice_profile(sugita_voice)

    # 取得
    fetched = mem.get_voice_profile("voice_sugita_custom")
    assert fetched is not None
    assert fetched.label == "杉田智和風_渋みモノローグ"
    assert "杉田智和風" in fetched.tags

    # 一覧
    user_voices = mem.list_voice_profiles(source="user")
    assert any(v.voice_id == "voice_sugita_custom" for v in user_voices)

    # ビルトインは削除不可
    assert not mem.delete_voice_profile("voice_01")
    # ユーザーボイスは削除可能
    assert mem.delete_voice_profile("voice_sugita_custom")
    assert mem.get_voice_profile("voice_sugita_custom") is None


def test_series_and_book_association(tmp_db):
    mem, db_file = tmp_db
    series = Series(
        id="series_mushoku",
        title="無職転生",
        description="異世界転生シリーズ",
        castings={
            "前世の男": {"voice_id": "voice_06", "voice_internal_id": "voice_06i"},
            "ルーデウス": {"voice_id": "voice_05", "voice_internal_id": "voice_06i"},
        },
    )
    mem.upsert_series(series)

    fetched = mem.get_series("series_mushoku")
    assert fetched is not None
    assert fetched.title == "無職転生"
    assert fetched.castings["前世の男"]["voice_id"] == "voice_06"

    # 書籍にシリーズを紐付け
    mem.set_book_series("book_test", "series_mushoku")
    assert mem.get_book_series_id("book_test") == "series_mushoku"


def test_casting_priorities(tmp_db):
    mem, db_file = tmp_db

    # シリーズを設定
    series = Series(
        id="series_mushoku",
        title="無職転生",
        castings={
            "ルーデウス": {"voice_id": "voice_05", "voice_internal_id": "voice_06i"},
        },
    )
    mem.upsert_series(series)
    mem.set_book_series("book_test", "series_mushoku")

    # 手動指定: ロキシーは voice_03 (落ち着いた女性) にロック
    mem.set_character_casting(CharacterCasting(
        character_id="roxy",
        character_name="ロキシー",
        voice_id="voice_03",
        voice_internal_id="voice_03i",
        is_locked=True,
    ))

    # ストーリー状態（キャラ3人）
    # 1. ルーデウス（シリーズ設定あり）
    # 2. ロキシー（手動指定あり）
    # 3. オルステッド（手動もシリーズもなし → スマートマッチング）
    state = StoryState()
    state.characters["rudeus"] = Character(
        id="rudeus", name="ルーデウス", gender="male", age="child", role="protagonist")
    state.characters["roxy"] = Character(
        id="roxy", name="ロキシー", gender="female", age="young", role="mentor")
    state.characters["orsted"] = Character(
        id="orsted", name="オルステッド", gender="male", age="adult", role="rival",
        personality=["渋い", "圧倒的強者"])

    casting = CastingDirector()
    assigned = casting.assign_voices(state, memory=mem)

    assert len(assigned) == 3

    # ルーデウスはシリーズ設定の voice_05 (少年ボイス) が適用されていること
    assert state.characters["rudeus"].voice.voice_id == "voice_05"

    # ロキシーは手動指定の voice_03 が適用されていること
    assert state.characters["roxy"].voice.voice_id == "voice_03"

    # オルステッドは成人男性向けボイスが選ばれていること
    assert state.characters["orsted"].voice.gender == "male"
    assert state.characters["orsted"].voice.voice_id in ("voice_04", "voice_06", "voice_01")


def test_worker_rpc_methods(tmp_db):
    mem, db_file = tmp_db
    worker = EngineWorker(db_file)

    # 1. list_voice_profiles
    res = worker.dispatch("list_voice_profiles", {})
    assert "profiles" in res
    assert len(res["profiles"]) >= 7

    # 2. save_voice_profile
    new_profile = {
        "voice_id": "voice_uchiyama_custom",
        "label": "内山夕実風_ショタ",
        "gender": "male",
        "age": "child",
        "base_pitch": 0.15,
        "base_pace": 1.05,
        "sbv2_model_name": "jvnv-F1-jp",
        "sbv2_style": "Neutral",
        "tags": ["内山夕実風", "ショタ", "少年主人公"],
        "description": "少年ルーデウス用カスタムボイス",
    }
    save_res = worker.dispatch("save_voice_profile", {"profile": new_profile})
    assert save_res["ok"] is True
    assert save_res["voice_id"] == "voice_uchiyama_custom"

    # 3. get_castings & assign_casting
    # テスト用のキャラをDBに追加
    ch = Character(id="rudeus", name="ルーデウス", gender="male", age="child")
    mem.upsert_character(ch, 0)

    cast_res = worker.dispatch("get_castings", {"book_id": "book_test"})
    assert "castings" in cast_res
    assert len(cast_res["castings"]) >= 1

    assign_res = worker.dispatch("assign_casting", {
        "book_id": "book_test",
        "character_id": "rudeus",
        "voice_id": "voice_uchiyama_custom",
        "is_locked": True,
    })
    assert assign_res["ok"] is True
    assert assign_res["voice_id"] == "voice_uchiyama_custom"

    # 4. list_series & upsert_series
    series_data = {
        "id": "series_test_01",
        "title": "テストシリーズ",
        "description": "テストシリーズ説明",
        "castings": {"rudeus": {"voice_id": "voice_uchiyama_custom"}},
    }
    s_res = worker.dispatch("upsert_series", {"series": series_data})
    assert s_res["ok"] is True

    s_list = worker.dispatch("list_series", {})
    assert any(s["id"] == "series_test_01" for s in s_list["series"])
