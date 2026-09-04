from __future__ import annotations

from typing import TYPE_CHECKING
from models import VoiceProfile

if TYPE_CHECKING:
    from memory import MemoryEngine

NARRATOR = "narrator"

# ボイスプール（External 用ビルトイン枠 + ナレーター固定）
#
# 注意: tags 中の「杉田智和風」「内山夕実風」「小原好美風」等の実在声優風ラベルは、
# 開発者が声のイメージを掴むための内部メモです。本番のブック表示・外部出力・
# レコメンド検索には含めず、UI にもそのまま出さないでください
# （声クローンの作成・利用と誤認されるリスクを避けるため。公開時は
#  「低音・渋い」「少年・元気」等の属性タグに寄せる方針）。
VOICE_POOL = [
    VoiceProfile(
        voice_id="voice_01", label="若い男性", gender="male", age="young",
        base_pitch=0.05, base_pace=1.05, tts_voice="ja-JP-KeitaNeural",
        sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral",
        source="builtin", tags=["青年", "男性", "明るい"],
        description="爽やかな若い男性の声"),
    VoiceProfile(
        voice_id="voice_02", label="若い女性", gender="female", age="young",
        base_pitch=0.12, base_pace=1.0, tts_voice="ja-JP-NanamiNeural",
        sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral",
        source="builtin", tags=["少女", "女性", "可愛い"],
        description="親しみやすい若い女性の声"),
    VoiceProfile(
        voice_id="voice_03", label="落ち着いた女性", gender="female", age="adult",
        base_pitch=-0.02, base_pace=0.95, tts_voice="ja-JP-NanamiNeural",
        sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral",
        source="builtin", tags=["女性", "落ち着き", "知性", "大人の女性"],
        description="知性のある落ち着いた女性の声（師匠・お姉さん系）"),
    VoiceProfile(
        voice_id="voice_04", label="渋い男性", gender="male", age="elder",
        base_pitch=-0.10, base_pace=0.90, tts_voice="ja-JP-KeitaNeural",
        sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral",
        source="builtin", tags=["中年", "男性", "渋い", "老人"],
        description="威厳と落ち着きのある渋い男性の声"),
    VoiceProfile(
        voice_id="voice_05", label="少年ボイス", gender="male", age="child",
        base_pitch=0.18, base_pace=1.08, tts_voice="ja-JP-NanamiNeural",
        sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral",
        source="builtin", tags=["少年", "ショタ", "子供", "内山夕実風", "主人公"],
        description="勇敢さと幼さが同居する少年主人公向けボイス"),
    VoiceProfile(
        voice_id="voice_06", label="重厚・低音男性", gender="male", age="adult",
        base_pitch=-0.15, base_pace=0.88, base_energy=0.9,
        tts_voice="ja-JP-KeitaNeural",
        sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral",
        source="builtin", tags=["低音", "重厚", "杉田智和風", "前世の男", "モノローグ"],
        description="深い響きと落ち着きを持つ低音ボイス（心の声や歴戦の男に最適）"),
    VoiceProfile(
        voice_id="voice_07", label="冷静・淡々少女", gender="female", age="young",
        base_pitch=0.04, base_pace=0.92,
        tts_voice="ja-JP-NanamiNeural",
        sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral",
        source="builtin", tags=["少女", "クーデレ", "小原好美風", "魔術師", "淡々"],
        description="感情を抑えた淡々とした知的な少女ボイス"),
]

NARRATOR_VOICE = VoiceProfile(
    voice_id="voice_narrator", label="ナレーター", gender="male", age="adult",
    base_pitch=0.0, base_pace=0.92, tts_voice="ja-JP-KeitaNeural",
    sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral",
    source="builtin", tags=["ナレーション", "語り手"],
    description="客観的で聞き取りやすい標準ナレーション用ボイス")

# Internal（内面の声）は External より低く・遅い
_INTERNAL_PITCH_OFFSET = -0.10
_INTERNAL_PACE_SCALE = 0.88


def _internal_of(profile: VoiceProfile) -> VoiceProfile:
    """External VoiceProfile から Internal 版を生成する。"""
    data = profile.model_dump()
    data["voice_id"] = profile.voice_id + "i"
    data["label"] = f"内面（{profile.label}）"
    data["base_pitch"] = round(profile.base_pitch + _INTERNAL_PITCH_OFFSET, 3)
    data["base_pace"] = round(profile.base_pace * _INTERNAL_PACE_SCALE, 3)
    data["tags"] = list(set(profile.tags + ["内面", "心の声"]))
    return VoiceProfile(**data)


# Internal 用プール（voice_01i〜07i）
INTERNAL_POOL = [_internal_of(p) for p in VOICE_POOL]
NARRATOR_VOICE_INTERNAL = _internal_of(NARRATOR_VOICE)

# voice_id からプロファイルへの組み込み辞書
_BUILTIN_MAP: dict[str, VoiceProfile] = {
    p.voice_id: p for p in [*VOICE_POOL, *INTERNAL_POOL, NARRATOR_VOICE, NARRATOR_VOICE_INTERNAL]
}


def sync_builtin_voices(memory: MemoryEngine) -> None:
    """組み込みボイスをDBの voice_registry に同期する。"""
    for profile in _BUILTIN_MAP.values():
        memory.register_voice_profile(profile)


def resolve_voice_profile(voice_id: str, memory: MemoryEngine | None = None) -> VoiceProfile:
    """voice_id から VoiceProfile を解決する（DB -> ビルトインの順で検索）。"""
    if memory is not None:
        p = memory.get_voice_profile(voice_id)
        if p is not None:
            return p
    if voice_id in _BUILTIN_MAP:
        return _BUILTIN_MAP[voice_id]
    # voice_id が末尾 "i"（内面）で親ボイスがある場合、動的に生成
    if voice_id.endswith("i"):
        parent_id = voice_id[:-1]
        parent = resolve_voice_profile(parent_id, memory)
        return _internal_of(parent)
    return NARRATOR_VOICE


def all_profiles(memory: MemoryEngine | None = None) -> list[VoiceProfile]:
    """全 VoiceProfile を返す（DB指定時はDB内のユーザーカスタムボイスも含める）。"""
    if memory is not None:
        db_profiles = memory.list_voice_profiles()
        if db_profiles:
            # 内面ボイスも追加
            res = list(db_profiles)
            existing_ids = {p.voice_id for p in res}
            for p in db_profiles:
                if not p.voice_id.endswith("i"):
                    internal_p = _internal_of(p)
                    if internal_p.voice_id not in existing_ids:
                        res.append(internal_p)
            return res
    return [*VOICE_POOL, *INTERNAL_POOL, NARRATOR_VOICE, NARRATOR_VOICE_INTERNAL]

