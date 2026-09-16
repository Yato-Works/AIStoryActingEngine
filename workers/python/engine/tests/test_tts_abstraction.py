"""TTS Abstraction Layer のユニットテスト。

LLM・TTS サーバ・ネットワーク一切不要。
Acting IR、Backend Manifest、Resolution Report、Registry、後方互換を検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# engine ディレクトリを path に追加
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from acting_ir import ActingIR, performance_to_ir
from models import Performance, VoiceProfile
from tts_backend import (
    ACTING_IR_PARAMETERS, BackendManifest, CapabilityLevel,
    ResolutionReport, TTSBackend,
)
import tts_registry


# ============================================================================
# Acting IR
# ============================================================================

class TestActingIR:
    """Acting IR v1 の生成・バリデーション。"""

    def test_default_values(self):
        ir = ActingIR(speaker="voice_01", text="こんにちは")
        assert ir.version == "1"
        assert ir.emotion == "neutral"
        assert ir.emotion_intensity == 0.3
        assert ir.speaking_rate == 1.0
        assert ir.pitch == 0.0
        assert ir.energy == 0.8
        assert ir.volume == 1.0
        assert ir.pause_before == 0.0
        assert ir.pause_after == 0.0
        assert ir.voicing == "external"
        assert ir.backend_options == {}

    def test_custom_values(self):
        ir = ActingIR(
            speaker="voice_02", text="怒ってる！",
            emotion="angry", emotion_intensity=0.8,
            speaking_rate=1.3, pitch=-0.2, energy=1.2,
            volume=1.3, style="dialogue", voicing="external",
            backend_options={"sbv2": {"style": "Angry"}},
        )
        assert ir.emotion == "angry"
        assert ir.emotion_intensity == 0.8
        assert ir.backend_options["sbv2"]["style"] == "Angry"

    def test_version_is_literal_1(self):
        ir = ActingIR(speaker="x", text="t")
        assert ir.version == "1"

    def test_serialization_roundtrip(self):
        ir = ActingIR(speaker="voice_01", text="テスト", emotion="happy",
                      emotion_intensity=0.7)
        data = ir.model_dump()
        ir2 = ActingIR(**data)
        assert ir == ir2


# ============================================================================
# Performance → Acting IR 変換
# ============================================================================

class TestPerformanceToIR:
    """既存 Performance から Acting IR への変換。"""

    def test_basic_conversion(self):
        perf = Performance(
            voice="voice_01", mode="dialogue", emotion="happy",
            intensity=0.7, pace=1.1, pitch=0.05, volume=1.2,
            voicing="external", style="Joyful",
        )
        ir = performance_to_ir("嬉しいね！", perf)
        assert ir.speaker == "voice_01"
        assert ir.text == "嬉しいね！"
        assert ir.emotion == "happy"
        assert ir.emotion_intensity == 0.7
        assert ir.speaking_rate == 1.1
        assert ir.pitch == 0.05
        assert ir.volume == 1.2
        assert ir.voicing == "external"

    def test_style_fallback_to_mode(self):
        """style が空のとき mode がフォールバックされる。"""
        perf = Performance(
            voice="voice_narrator", mode="narration", emotion="neutral",
            intensity=0.3, pace=1.0, pitch=0.0, volume=1.0, style="",
        )
        ir = performance_to_ir("地の文", perf)
        assert ir.style == "narration"


# ============================================================================
# Backend Manifest & Capability
# ============================================================================

class TestBackendManifest:
    """BackendManifest の宣言・検証。"""

    def test_capability_for_declared(self):
        manifest = BackendManifest(
            backend="test",
            capabilities={
                "emotion": CapabilityLevel.NATIVE,
                "pitch": CapabilityLevel.APPROXIMATE,
            },
        )
        assert manifest.capability_for("emotion") == CapabilityLevel.NATIVE
        assert manifest.capability_for("pitch") == CapabilityLevel.APPROXIMATE

    def test_capability_for_undeclared_is_unsupported(self):
        manifest = BackendManifest(backend="test", capabilities={})
        assert manifest.capability_for("speaker_cloning") == CapabilityLevel.UNSUPPORTED

    def test_acting_ir_parameters_coverage(self):
        """ACTING_IR_PARAMETERS がすべて定義済み。"""
        assert len(ACTING_IR_PARAMETERS) > 0
        for p in ACTING_IR_PARAMETERS:
            assert isinstance(p, str)


# ============================================================================
# Resolution Report
# ============================================================================

class TestResolutionReport:
    """Resolution Report の生成・検索。"""

    def test_add_and_query(self):
        report = ResolutionReport(backend="test")
        report.add("speaking_rate", 1.2, CapabilityLevel.NATIVE, "+20%")
        report.add("emotion", "angry", CapabilityLevel.UNSUPPORTED, None,
                   warning="not supported")
        assert len(report.entries) == 2
        assert len(report.warnings) == 1
        assert report.warnings[0].parameter == "emotion"
        assert len(report.unsupported) == 1

    def test_empty_report(self):
        report = ResolutionReport(backend="empty")
        assert report.warnings == []
        assert report.unsupported == []


# ============================================================================
# TTSBackend 基底クラス
# ============================================================================

class _MockBackend(TTSBackend):
    """テスト用の最小 Backend 実装。"""

    def manifest(self) -> BackendManifest:
        return BackendManifest(
            backend="mock",
            capabilities={"speaking_rate": CapabilityLevel.NATIVE},
        )

    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"MOCK_AUDIO")
        report = ResolutionReport(backend="mock")
        report.add("speaking_rate", ir.speaking_rate,
                   CapabilityLevel.NATIVE, ir.speaking_rate)
        return report


class TestTTSBackend:
    """TTSBackend 基底クラスの動作確認。"""

    def test_name_property(self):
        backend = _MockBackend()
        assert backend.name == "mock"

    def test_synthesize(self, tmp_path):
        backend = _MockBackend()
        ir = ActingIR(speaker="voice_01", text="テスト")
        out = tmp_path / "test.wav"
        report = backend.synthesize(ir, out)
        assert out.read_bytes() == b"MOCK_AUDIO"
        assert report.backend == "mock"
        assert len(report.entries) == 1


# ============================================================================
# TTS Registry
# ============================================================================

class TestTTSRegistry:
    """tts_registry の登録・検索。"""

    def setup_method(self):
        tts_registry.clear()

    def teardown_method(self):
        tts_registry.clear()

    def test_register_and_get(self):
        tts_registry.register_backend("mock", _MockBackend)
        backend = tts_registry.get_backend("mock")
        assert isinstance(backend, _MockBackend)
        assert backend.name == "mock"

    def test_get_unregistered_raises(self):
        with pytest.raises(KeyError, match="not registered"):
            tts_registry.get_backend("nonexistent")

    def test_registered_names(self):
        tts_registry.register_backend("alpha", _MockBackend)
        tts_registry.register_backend("beta", _MockBackend)
        assert tts_registry.registered_names() == ["alpha", "beta"]

    def test_is_registered(self):
        assert not tts_registry.is_registered("mock")
        tts_registry.register_backend("mock", _MockBackend)
        assert tts_registry.is_registered("mock")

    def test_list_backends(self):
        tts_registry.register_backend("mock", _MockBackend)
        manifests = tts_registry.list_backends()
        assert "mock" in manifests
        assert manifests["mock"].backend == "mock"

    def test_overwrite_registration(self):
        """同名再登録は上書きされる。"""
        tts_registry.register_backend("mock", _MockBackend)
        tts_registry.register_backend("mock", _MockBackend)
        assert tts_registry.is_registered("mock")


# ============================================================================
# Edge Backend Adapter（パラメータ変換テスト）
# ============================================================================

class TestEdgeBackendParams:
    """Edge Backend の ActingIR → edge-tts パラメータ変換。"""

    def test_rate_str(self):
        from backends.edge_backend import _rate_str
        assert _rate_str(1.0) == "+0%"
        assert _rate_str(1.1) == "+10%"
        assert _rate_str(0.9) == "-10%"

    def test_pitch_str(self):
        from backends.edge_backend import _pitch_str
        assert _pitch_str(0.0) == "+0Hz"
        assert _pitch_str(1.0) == "+30Hz"
        assert _pitch_str(-1.0) == "-30Hz"

    def test_volume_str(self):
        from backends.edge_backend import _volume_str
        assert _volume_str(1.0) == "+0%"
        assert _volume_str(1.5) == "+25%"

    def test_manifest_capabilities(self):
        from backends.edge_backend import EdgeBackend
        backend = EdgeBackend()
        m = backend.manifest()
        assert m.capability_for("speaking_rate") == CapabilityLevel.NATIVE
        assert m.capability_for("pitch") == CapabilityLevel.NATIVE
        assert m.capability_for("emotion") == CapabilityLevel.UNSUPPORTED

    def test_synthesize_reports_unsupported_emotion(self):
        """emotion が neutral 以外のとき warning が記録される。"""
        from backends.edge_backend import EdgeBackend
        backend = EdgeBackend()
        ir = ActingIR(speaker="voice_01", text="怒り", emotion="angry",
                      emotion_intensity=0.8)
        mock_comm = MagicMock()
        mock_comm.save = MagicMock(return_value=None)
        with patch("edge_tts.Communicate", return_value=mock_comm):
            with patch("asyncio.run"):
                report = backend.synthesize(ir, Path("/tmp/test.mp3"))
        assert len(report.warnings) >= 1
        assert any("emotion" in w.parameter for w in report.warnings)


# ============================================================================
# SBV2 Backend Adapter（パラメータ変換テスト）
# ============================================================================

class TestSbv2BackendParams:
    """SBV2 Backend の ActingIR → SBV2 パラメータ変換。"""

    def test_manifest_capabilities(self):
        from backends.sbv2_backend import Sbv2Backend
        backend = Sbv2Backend()
        m = backend.manifest()
        assert m.capability_for("emotion") == CapabilityLevel.NATIVE
        assert m.capability_for("speaking_rate") == CapabilityLevel.NATIVE
        assert m.capability_for("pitch") == CapabilityLevel.APPROXIMATE

    def test_emotion_to_style_mapping(self):
        from backends.sbv2_backend import EMOTION_TO_STYLE
        assert EMOTION_TO_STYLE["happy"] == "Joyful"
        assert EMOTION_TO_STYLE["angry"] == "Angry"
        assert EMOTION_TO_STYLE["neutral"] == "Neutral"


# ============================================================================
# Aivis Backend Adapter（パラメータ変換テスト）
# ============================================================================

class TestAivisBackendParams:
    """Aivis Backend の Manifest 確認。"""

    def test_manifest_capabilities(self):
        from backends.aivis_backend import AivisBackend
        backend = AivisBackend()
        m = backend.manifest()
        assert m.capability_for("speaking_rate") == CapabilityLevel.NATIVE
        assert m.capability_for("pitch") == CapabilityLevel.NATIVE
        assert m.capability_for("emotion") == CapabilityLevel.UNSUPPORTED


# ============================================================================
# backends パッケージの自動登録
# ============================================================================

class TestBackendsAutoRegistration:
    """backends/__init__.py が import 時に全 Backend を自動登録する。"""

    def setup_method(self):
        tts_registry.clear()

    def teardown_method(self):
        import importlib
        import backends
        importlib.reload(backends)

    def test_auto_registration(self):
        import importlib
        import backends
        importlib.reload(backends)
        assert tts_registry.is_registered("edge")
        assert tts_registry.is_registered("sbv2")
        assert tts_registry.is_registered("aivis")


# ============================================================================
# VoiceProfile.backend_profiles
# ============================================================================

class TestVoiceProfileBackendProfiles:
    """VoiceProfile の Backend 別設定保持。"""

    def test_default_empty(self):
        vp = VoiceProfile(voice_id="test_01")
        assert vp.backend_profiles == {}

    def test_set_backend_profiles(self):
        vp = VoiceProfile(
            voice_id="test_01",
            backend_profiles={
                "sbv2": {"model_name": "jvnv-M1-jp", "style": "Neutral"},
                "indextts": {"reference_audio": "kevin_sample.wav"},
            },
        )
        assert vp.backend_profiles["sbv2"]["model_name"] == "jvnv-M1-jp"
        assert vp.backend_profiles["indextts"]["reference_audio"] == "kevin_sample.wav"

    def test_roundtrip(self):
        vp = VoiceProfile(
            voice_id="test_02",
            backend_profiles={"edge": {"voice": "ja-JP-KeitaNeural"}},
        )
        data = vp.model_dump()
        vp2 = VoiceProfile(**data)
        assert vp2.backend_profiles == vp.backend_profiles


# ============================================================================
# 後方互換: 旧 get_provider() テスト
# ============================================================================

class TestLegacyGetProvider:
    """旧 ITTSProvider + get_provider() が引き続き動作すること。"""

    def test_get_provider_edge(self):
        from tts import get_provider
        provider = get_provider("edge")
        assert provider.name == "edge"

    def test_get_provider_sbv2(self):
        from tts import get_provider
        provider = get_provider("sbv2")
        assert provider.name == "sbv2"

    def test_get_provider_aivis(self):
        from tts import get_provider
        provider = get_provider("aivis")
        assert provider.name == "aivis"

    def test_get_provider_default_is_edge(self):
        from tts import get_provider
        provider = get_provider("unknown")
        assert provider.name == "edge"
