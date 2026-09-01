# ADR 0001: Core に AI モデルを持たない

- Status: Accepted
- Date: 2026-09-01

## Context

AI技術は世代交代が激しい（Style-Bert-VITS2 → Qwen3-TTS → その先）。
TTSモデルやLLMをランタイムの中心に置くと、モデル交代のたびにCoreを改修することになる。

## Decision

- Core（将来のC++ Runtime）にAIモデルを含めない
- AI機能は Python Worker に隔離し、C++とは JSON 契約（IPC）でのみ通信する
- TTS / LLM / OCR はすべてプラグイン的インターフェース（ITTSProvider, IStoryAnalyzer, IOCRProvider）越しに利用する
- 本当の資産は Character Memory / Scene State / Voice Profile / Performance Direction / Job & Event System とし、ここに実装投資をする

## Consequences

- モデル世代交代はプラグイン差し替えで吸収できる
- C++側はJSON契約の安定性を維持する責任を持つ（`performance.json` スキーマが中核契約）
- Python側の依存（PyTorch等）がCoreのビルド・配布を汚染しない
