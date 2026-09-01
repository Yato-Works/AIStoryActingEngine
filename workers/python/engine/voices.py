"""Voice Profile のプール定義（Casting と TTS の共有レジストリ）。

External（外向き）4 枠 + Internal（内面）4 枠 + ナレーター 2 種。
director.py（配役・演出）と tts.py（SBV2 プロバイダ）の両方が参照するため、
循環依存を避けるために独立モジュールに切り出している。

sbv2_model_name: model_assets 内のモデルディレクトリ名
  男性=jvnv-M1-jp / 女性=jvnv-F1-jp（initialize.py が DL する標準モデル）
"""

from __future__ import annotations

from models import VoiceProfile

NARRATOR = "narrator"

# ボイスプール（External 用 4 枠 + ナレーター固定）
VOICE_POOL = [
    VoiceProfile(voice_id="voice_01", label="若い男性", gender="male", age="young",
                 base_pitch=0.05, base_pace=1.05, tts_voice="ja-JP-KeitaNeural",
                 sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral"),
    VoiceProfile(voice_id="voice_02", label="若い女性", gender="female", age="young",
                 base_pitch=0.12, base_pace=1.0, tts_voice="ja-JP-NanamiNeural",
                 sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral"),
    VoiceProfile(voice_id="voice_03", label="落ち着いた女性", gender="female", age="adult",
                 base_pitch=-0.02, base_pace=0.95, tts_voice="ja-JP-NanamiNeural",
                 sbv2_model_name="jvnv-F1-jp", sbv2_style="Neutral"),
    VoiceProfile(voice_id="voice_04", label="渋い男性", gender="male", age="elder",
                 base_pitch=-0.10, base_pace=0.90, tts_voice="ja-JP-KeitaNeural",
                 sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral"),
]

NARRATOR_VOICE = VoiceProfile(
    voice_id="voice_narrator", label="ナレーター", gender="male", age="adult",
    base_pitch=0.0, base_pace=0.92, tts_voice="ja-JP-KeitaNeural",
    sbv2_model_name="jvnv-M1-jp", sbv2_style="Neutral")

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
    return VoiceProfile(**data)


# Internal 用プール（voice_01i〜04i）
INTERNAL_POOL = [_internal_of(p) for p in VOICE_POOL]
NARRATOR_VOICE_INTERNAL = _internal_of(NARRATOR_VOICE)


def all_profiles() -> list[VoiceProfile]:
    """全 VoiceProfile をフラットに返す（TTS プロバイダの voice_id 解決用）。"""
    return [*VOICE_POOL, *INTERNAL_POOL, NARRATOR_VOICE, NARRATOR_VOICE_INTERNAL]
