"""Irodori Backend Adapter のユニットテスト。

TTS サーバ・ネットワーク不要。httpx はモックで検証する。
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

from acting_ir import ActingIR
from reading import ReadingDictionary
from tts_backend import CapabilityLevel
from backends.irodori_backend import (
    EMOTION_EMOJI,
    IrodoriBackend,
    build_caption,
)


# ============================================================================
# Manifest
# ============================================================================


class TestIrodoriManifest:
    def test_capabilities(self):
        m = IrodoriBackend().manifest()
        assert m.backend == "irodori"
        assert m.capability_for("speaker_cloning") == CapabilityLevel.NATIVE
        assert m.capability_for("speaking_rate") == CapabilityLevel.NATIVE
        assert m.capability_for("emotion") == CapabilityLevel.INSTRUCTION
        assert m.capability_for("text_reading") == CapabilityLevel.INSTRUCTION
        assert m.capability_for("pitch") == CapabilityLevel.UNSUPPORTED
        assert m.capability_for("volume") == CapabilityLevel.UNSUPPORTED

    def test_registered_in_registry(self):
        import backends
        import tts_registry
        assert tts_registry.is_registered("irodori")


# ============================================================================
# build_caption（emotion → caption の instruction 変換）
# ============================================================================


class TestBuildCaption:
    def test_neutral(self):
        ir = ActingIR(speaker="v", text="t")
        assert "中立的" in build_caption(ir)

    def test_low_intensity_hedged(self):
        ir = ActingIR(speaker="v", text="t", emotion="sad",
                      emotion_intensity=0.1)
        assert "わずかに" in build_caption(ir)

    def test_high_intensity_emphasized(self):
        ir = ActingIR(speaker="v", text="t", emotion="angry",
                      emotion_intensity=0.9)
        cap = build_caption(ir)
        assert "強く" in cap
        assert "怒り" in cap

    def test_internal_voice(self):
        ir = ActingIR(speaker="v", text="t", voicing="internal")
        assert "内面" in build_caption(ir)

    def test_narrator(self):
        ir = ActingIR(speaker="v", text="t", voicing="narrator")
        assert "語り手" in build_caption(ir)

# ============================================================================
# resolve_text（読み台本の消費、ADR-0006 §5）
# ============================================================================


class TestResolveText:
    def test_text_reading_takes_priority(self):
        ir = ActingIR(speaker="v", text="千早と申します。",
                      backend_options={"irodori": {
                          "text_reading": "ちはやともうします。"}})
        text, source = IrodoriBackend().resolve_text(ir)
        assert (text, source) == ("ちはやともうします。", "reading-script")

    def test_dictionary_applied_when_no_script(self):
        ir = ActingIR(speaker="v", text="千早が貼付を剥がす",
                      backend_options={"irodori": {
                          "dictionary": ReadingDictionary(
                              {"千早": "ちはや", "貼付": "はりつけ"})}})
        text, source = IrodoriBackend().resolve_text(ir)
        assert text == "ちはやがはりつけを剥がす"
        assert source == "dictionary"

    def test_raw_fallback_without_any(self):
        ir = ActingIR(speaker="v", text="千早と申します。")
        text, source = IrodoriBackend().resolve_text(ir)
        assert (text, source) == ("千早と申します。", "raw")


# ============================================================================
# synthesize（httpx モック）
# ============================================================================


def _mock_httpx_post():
    """httpx.post を捕捉する (patcher, captured) を返す。"""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        resp = MagicMock()
        resp.content = b"RIFF....WAV"
        resp.raise_for_status = lambda: None
        return resp

    patcher = patch("httpx.post", side_effect=fake_post)
    return patcher, captured


class TestIrodoriSynthesize:
    def test_request_body_with_reading_script(self, tmp_path):
        backend = IrodoriBackend(host="http://127.0.0.1:8088")
        ir = ActingIR(
            speaker="voice_01", text="千早と申します。",
            emotion="sad", emotion_intensity=0.8,
            speaking_rate=1.1,
            backend_options={"irodori": {
                "text_reading": "ちはやともうします。",
                "voice": "narrator_woman",
            }})
        patcher, captured = _mock_httpx_post()
        with patcher:
            report = backend.synthesize(
                ir, tmp_path / "seg_001.wav")

        body = captured["json"]
        assert captured["url"] == "http://127.0.0.1:8088/v1/audio/speech"
        assert body["model"] == "irodori-tts"
        assert body["input"] == "ちはやともうします。"  # 読み台本が優先
        assert body["voice"] == "narrator_woman"
        assert body["speed"] == 1.1
        assert "caption" in body["irodori"] and body["irodori"]["caption"]
        # 感情の解決が caption に変換されている
        entry = next(e for e in report.entries if e.parameter == "emotion")
        assert entry.capability == CapabilityLevel.INSTRUCTION
        # 未対応パラメータは warning 付きで報告（黙って無視しない）
        assert report.warnings

    def test_emoji_injection(self, tmp_path):
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="やった！",
                      emotion="happy",
                      backend_options={"irodori": {"emoji": True}})
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["json"]["input"] == f"やった！{EMOTION_EMOJI['happy']}"

    def test_raw_text_warns_about_kanji_risk(self, tmp_path):
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="千早と申します。")
        patcher, captured = _mock_httpx_post()
        with patcher:
            report = backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["json"]["input"] == "千早と申します。"
        entry = next(e for e in report.entries
                     if e.parameter == "text_reading")
        assert entry.warning and "漢字" in entry.warning

    def test_bearer_token_header(self, tmp_path):
        backend = IrodoriBackend(api_key="secret")
        ir = ActingIR(speaker="v", text="t")
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_server_options_passthrough(self, tmp_path):
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="t",
                      backend_options={"irodori": {
                          "server": {"num_steps": 20, "seed": 42}}})
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["json"]["irodori"]["num_steps"] == 20
        assert captured["json"]["irodori"]["seed"] == 42

    def test_audio_written(self, tmp_path):
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="t")
        out = tmp_path / "out" / "seg.wav"
        patcher, _ = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, out)
        assert out.read_bytes() == b"RIFF....WAV"

    def test_chunking_disabled_via_env(self, tmp_path, monkeypatch):
        # サーバー側の分割合成（無音なし結合による「かくかく」対策）:
        # IRODORI_CHUNKING=0 で chunking_enabled=False を送る
        monkeypatch.setenv("IRODORI_CHUNKING", "0")
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="t")
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["json"]["irodori"]["chunking_enabled"] is False

    def test_chunking_option_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRODORI_CHUNKING", "1")
        backend = IrodoriBackend()
        ir = ActingIR(speaker="v", text="t",
                      backend_options={"irodori": {
                          "server": {"chunking_enabled": False}}})
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        # 明示オプションが環境変数より強い
        assert captured["json"]["irodori"]["chunking_enabled"] is False

    def test_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("IRODORI_TIMEOUT", "900")
        assert IrodoriBackend().timeout == 900.0
        assert IrodoriBackend(timeout=30.0).timeout == 30.0

    def test_timeout_sent_to_httpx(self, tmp_path):
        backend = IrodoriBackend(timeout=777.0)
        ir = ActingIR(speaker="v", text="t")
        patcher, captured = _mock_httpx_post()
        with patcher:
            backend.synthesize(ir, tmp_path / "x.wav")
        assert captured["timeout"] == 777.0


