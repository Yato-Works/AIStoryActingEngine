"""TTS Backend 抽象基盤 — Capability Manifest + Resolution Report。

設計書「AIStoryActingEngine — TTS Abstraction Design」§3, §4, §5 に基づく。

全 Backend Adapter はこの TTSBackend を継承し、
manifest() で対応機能を宣言し、synthesize() で Acting IR を音声へ変換する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from acting_ir import ActingIR


# ============================================================================
# 設計書 §3: Capability Levels
# ============================================================================

class CapabilityLevel(str, Enum):
    """Backend が各パラメータに対して持つ制御レベル。"""

    NATIVE = "native"
    """モデル固有の直接制御（数値パラメータをそのまま渡せる）。"""

    INSTRUCTION = "instruction"
    """自然言語などへの変換で制御（テキストプロンプトに変換する等）。"""

    APPROXIMATE = "approximate"
    """完全一致ではない近似制御（マッピングテーブルや量子化で近似する）。"""

    UNSUPPORTED = "unsupported"
    """制御不可（このパラメータは無視される）。"""


# ============================================================================
# 設計書 §3: Backend Manifest
# ============================================================================

# Acting IR が持つ制御可能パラメータの一覧
ACTING_IR_PARAMETERS = (
    "speaker_cloning",
    "emotion",
    "emotion_intensity",
    "speaking_rate",
    "pitch",
    "energy",
    "volume",
    "pause",
    "style",
)


class BackendManifest(BaseModel):
    """各 Backend が自身の対応能力を宣言する Manifest。

    設計書 §3: capabilities は ACTING_IR_PARAMETERS の各項目に対する
    CapabilityLevel を宣言する。
    """

    backend: str
    version: str = "0.1.0"
    capabilities: dict[str, CapabilityLevel] = Field(default_factory=dict)

    def capability_for(self, parameter: str) -> CapabilityLevel:
        """指定パラメータの CapabilityLevel を返す（未宣言は unsupported）。"""
        return self.capabilities.get(parameter, CapabilityLevel.UNSUPPORTED)


# ============================================================================
# 設計書 §5: Resolution Report
# ============================================================================

class ResolutionEntry(BaseModel):
    """個々のパラメータの解決結果。"""

    parameter: str
    requested: Any
    capability: CapabilityLevel
    resolved: Any
    warning: str | None = None


class ResolutionReport(BaseModel):
    """ActingIR → Backend 変換の解決結果全体。

    設計書 §5: Backend が要求された機能を持たない場合、黙って無視しない。
    解決結果を記録し、必要に応じて warning を出す。
    """

    backend: str
    entries: list[ResolutionEntry] = Field(default_factory=list)

    @property
    def warnings(self) -> list[ResolutionEntry]:
        """warning が設定されているエントリのみを返す。"""
        return [e for e in self.entries if e.warning is not None]

    @property
    def unsupported(self) -> list[ResolutionEntry]:
        """unsupported として解決されたエントリのみを返す。"""
        return [e for e in self.entries
                if e.capability == CapabilityLevel.UNSUPPORTED]

    def add(self, parameter: str, requested: Any, capability: CapabilityLevel,
            resolved: Any, warning: str | None = None) -> None:
        """解決結果を追加する。"""
        self.entries.append(ResolutionEntry(
            parameter=parameter, requested=requested,
            capability=capability, resolved=resolved, warning=warning,
        ))


# ============================================================================
# 設計書 §4: Backend Adapter 基底クラス
# ============================================================================

class TTSBackend(ABC):
    """全 Backend Adapter の基底クラス。

    各 Backend は以下を実装する:
    - manifest(): 自身の Capability Manifest を返す
    - synthesize(): Acting IR を音声ファイルへ変換し、Resolution Report を返す
    """

    @abstractmethod
    def manifest(self) -> BackendManifest:
        """このBackendのCapability Manifestを返す。"""
        ...

    @abstractmethod
    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        """Acting IR を音声ファイルへ変換する。

        Returns:
            ResolutionReport: 各パラメータの解決結果
        """
        ...

    @property
    def name(self) -> str:
        """Backend名（manifest().backend のショートカット）。"""
        return self.manifest().backend
