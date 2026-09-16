"""TTS Backend Registry — Backend の登録・検索・ファクトリ。

設計書「AIStoryActingEngine — TTS Abstraction Design」§9 に基づく。

新しい TTS が登場したとき、Backend Adapter を書いて register するだけで
Engine Core を変更せずに利用可能になる。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tts_backend import BackendManifest, TTSBackend

logger = logging.getLogger("tts_registry")

# Backend ファクトリの登録簿
_FACTORIES: dict[str, Callable[..., TTSBackend]] = {}


def register_backend(name: str, factory: Callable[..., TTSBackend]) -> None:
    """Backend ファクトリを名前で登録する。

    同じ名前で再登録すると上書きする（テスト・ホットリロード用途）。
    """
    _FACTORIES[name] = factory
    logger.debug("Registered TTS backend: %s", name)


def get_backend(name: str, **kwargs: Any) -> TTSBackend:
    """名前から Backend インスタンスを生成して返す。

    Raises:
        KeyError: 未登録の Backend 名を指定した場合
    """
    if name not in _FACTORIES:
        available = ", ".join(sorted(_FACTORIES.keys())) or "(none)"
        raise KeyError(
            f"TTS backend '{name}' is not registered. "
            f"Available backends: {available}"
        )
    return _FACTORIES[name](**kwargs)


def list_backends() -> dict[str, BackendManifest]:
    """登録済み全 Backend の Manifest を返す。"""
    result: dict[str, BackendManifest] = {}
    for name, factory in _FACTORIES.items():
        try:
            backend = factory()
            result[name] = backend.manifest()
        except Exception:
            logger.warning("Failed to instantiate backend '%s' for manifest", name)
    return result


def registered_names() -> list[str]:
    """登録済みの Backend 名一覧を返す。"""
    return sorted(_FACTORIES.keys())


def is_registered(name: str) -> bool:
    """指定名の Backend が登録済みかどうか。"""
    return name in _FACTORIES


def clear() -> None:
    """全登録を解除する（テスト用）。"""
    _FACTORIES.clear()
