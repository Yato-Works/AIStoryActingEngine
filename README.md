# AIStoryActingEngine

AIが小説を「読み上げる」のではなく、**「演じる」**ための Story Runtime。

キャラクター理解・記憶・演技指示（Voice Direction）を中核に持ち、TTSモデルは交換可能な末端として扱います。

```
小説 → Story Analyzer → キャスティング → Voice Director → TTS → 🎧 Audio Drama
```

## 設計原則

- **AIモデルをアプリ本体にしない**：本当の資産は Character Memory / Scene State / Voice Profile / Performance Direction / Job & Event System
- **TTSは交換可能な末端**：Style-Bert-VITS2 → Qwen3-TTS → 未来のTTS、差し替えるだけ
- **Local版を無料で成立させる**：Cloudは「AIを買う」のではなく計算資源と手軽さを買う

## 技術スタック

| Layer | Technology |
|---|---|
| Desktop UI | Qt 6 / QML |
| Desktop Core | C++20/23 |
| AI Workers | Python 3.11+ |
| Local LLM | Ollama（qwen3:4b 等）/ 将来 llama.cpp |
| Story Memory | SQLite + FTS5（将来 Vector Search 追加） |
| Voice Director | LLM + Rule Engine |
| Local TTS | Style-Bert-VITS2 / Qwen3-TTS / AivisSpeech 等（プラグイン式） |
| Audio | FFmpeg |
| Cloud API | TypeScript + Fastify（Phase 7） |
| Mobile | Flutter（Phase 6） |

## 開発フェーズ

- [ ] **Phase 0** — PoC：小説 → キャラクター/物語理解 → キャスティング → 演技指示 → 音声（Python完結）
- [ ] **Phase 1** — Story Engine：Character / Scene / Relationship / Memory をSQLiteへ。物語状態を維持した演技
- [ ] **Phase 2** — Voice Director 本格化：人格・関係性・感情状態の維持
- [ ] **Phase 3** — Desktop：Qt/QML + C++ Core
- [ ] **Phase 4** — Local TTS 統合（GPU利用・VRAM管理）
- [ ] **Phase 5** — PDF / Image（OCR）
- [ ] **Phase 6** — Mobile Player（Flutter・聴くだけ）
- [ ] **Phase 7** — Cloud（Sync / Cloud TTS / Billing）

## Phase 0 の構成

```
workers/python/poc/
├── main.py      # パイプライン起動
├── schema.py    # performance.json 等の契約スキーマ
├── models.py    # データモデル
├── analyzer.py  # Story Analyzer (Ollama)
├── director.py  # Voice Director (Rule Engine)
└── tts.py       # TTS Provider アダプタ
```

実行：

```bash
cd workers/python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd poc
python main.py ..\..\samples\sample_novel.txt
```

出力は `workers/python/poc/output/` に生成されます。

## ディレクトリ

| ディレクトリ | 内容 |
|---|---|
| `workers/python/` | AIレイヤー（Python隔離地帯） |
| `desktop/` | Phase 3以降：Qt6/QML + C++ Core |
| `cloud/` | Phase 7以降：TS + Fastify |
| `mobile/` | Phase 6以降：Flutter |
| `docs/` | アーキテクチャとADR |
| `samples/` | 動作検証用サンプル小説 |
