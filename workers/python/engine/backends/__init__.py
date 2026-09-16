"""TTS Backend Adapters パッケージ。

import 時に全ビルトイン Backend を tts_registry に自動登録する。
"""

from __future__ import annotations

import tts_registry

from backends.edge_backend import EdgeBackend
from backends.sbv2_backend import Sbv2Backend
from backends.aivis_backend import AivisBackend

# --- 自動登録 ---
tts_registry.register_backend("edge", EdgeBackend)
tts_registry.register_backend("sbv2", Sbv2Backend)
tts_registry.register_backend("aivis", AivisBackend)
