# ADR 0005: TTS Abstraction Layer (Acting IR & Backend Adapter)

- Status: Accepted
- Date: 2026-09-13

## Context

TTS 技術の進化は極めて速く、新しいモデル（IndexTTS2.5、Qwen3-TTS、CosyVoice 等）が次々と登場している。
従来の `ITTSProvider` は `Performance` をそのまま TTS 実装へ渡していたため、以下の問題が生じつつあった：

1. **Core と TTS の結合**: モデル固有のパラメータ（SBV2 の `style` や `sdp_ratio` 等）が `Performance` に漏れ出していた。
2. **機能格差の不透明さ**: ある TTS は感情制御に対応しているが別のは未対応（例: Edge TTS）など、能力差がモデル間で大きく、Core 側でそれを追跡・ハンドリングできていなかった。
3. **キャラ声質の不整合**: 作品途中で TTS を切り替えるとキャラの声質が崩れるリスクがあった。

## Decision

### 1. 設計原則
**"Common semantics in Core, model-specific power in Adapter."**

- Engine Core は「演技の意味（Acting Semantics）」だけを扱う。
- TTS モデル固有の機能・パラメータは Backend Adapter 側で処理する。
- 未来の全 TTS に完全対応することではなく、**新しい TTS が登場しても Core を壊さず Backend を追加できること**を目標とする。

### 2. Acting IR v1
Engine Core の出力として TTS-agnostic な中間表現 `ActingIR` を導入する。
- 共通演技語彙: `speaker`, `text`, `emotion`, `emotion_intensity`, `speaking_rate`, `pitch`, `energy`, `volume`, `pause_before`, `pause_after`, `style`, `voicing`
- モデル固有パラメータは直接持たず、必要時のみ `backend_options` で拡張。

### 3. Capability Manifest
各 Backend Adapter は自身の制御能力を `BackendManifest` として宣言する。
- `native`: モデル固有の直接制御
- `instruction`: 自然言語への変換で制御
- `approximate`: 近似制御（マッピングテーブルや量子化）
- `unsupported`: 制御不可

### 4. Resolution Report
Acting IR から Backend パラメータへの変換時、Backend が未対応のパラメータを黙って無視せず、`ResolutionReport` に記録して警告・フォールバックを追跡可能にする。

### 5. Backend Registry
`tts_registry` により Backend を登録・検索可能にし、新しいモデルは Adapter ファイルを追加して登録するだけで Engine Core に手を加えずに利用可能にする。

### 6. Voice Consistency
`VoiceProfile` に `backend_profiles: dict[str, dict]` を追加。
キャラクターごとに各 Backend でのモデル・スタイル設定を保持し、作品再生中は原則として 1 キャラ 1 Backend を固定して声質の連続性を守る。

## Update 2026-09-16: Voice Reference Quality — 声質だけでなく「喋り方」もクローンされる

実機検証（prosody 実験）で、ゼロショット音声クローニングはリファレンスの
**話し方（速度・間の取り方）まで忠実に真似る**ことが判明した。
VoiceDesign で作った短い一文（約 5 秒・ゆっくり目）のリファレンスを使うと、
その「ためらいがちな喋り方」ごとクローンされ、生成音声が単語ごとに
止まって聞こえる（実測: 発話内沈黙 1.56s → 適正リファレンスで 0.42s）。

不変条件:

- 声リファレンスは**複数文を自然な速さで滑らかに読んだ長めの音声**から作る
  （`_VOICE_REF_TEXT` / `_VOICE_REF_CAPTION_SUFFIX`）。
- リファレンスの長さが基準（10 秒）未満なら自動で作り直す
  （`IRODORI_REGEN_VOICES=1` で強制再生成も可）。
- Irodori v4.1 公式の推奨（30 秒以上の参照音声）とも整合する。

## Consequences

- **安定性**: Engine Core は遅く・安定して進化し、Backend Adapter は速く・最新モデルに追従できる。
- **後方互換**: 既存の `ITTSProvider` / `get_provider()` は完全に動作し続け、既存テストやワークフローを壊さない。
- **拡張性**: IndexTTS2.5 等の最新モデルを試す際も、`backends/indextts_backend.py` を 1 枚作成して登録するだけで即座に検証可能。
