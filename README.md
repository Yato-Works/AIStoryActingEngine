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

- [x] **Phase 0** — PoC：小説 → キャラクター/物語理解 → キャスティング → 演技指示 → 音声（Python完結）
- [x] **Phase 1** — Story Engine：Character / Scene / Relationship / Memory をSQLiteへ。物語状態を維持した演技
- [ ] **Phase 2** — Voice Director 本格化：人格・関係性・感情状態の維持
- [ ] **Phase 3** — Desktop：Qt/QML + C++ Core
- [ ] **Phase 4** — Local TTS 統合（GPU利用・VRAM管理）
- [ ] **Phase 5** — PDF / Image（OCR）
- [ ] **Phase 6** — Mobile Player（Flutter・聴くだけ）
- [ ] **Phase 7** — Cloud（Sync / Cloud TTS / Billing）

## Phase 1 の構成（Story Engine）

```
workers/python/engine/
├── main.py      # パイプライン起動（CLI）
├── schema.py    # performance.json 等の契約スキーマ
├── models.py    # データモデル（Pydantic）
├── memory.py    # Memory Engine（SQLite + Event Log + FTS5 + 感情の余韻）
├── analyzer.py  # Story Analyzer (Ollama)
├── director.py  # Casting + Voice Director (Rule Engine)
├── tts.py       # TTS Provider アダプタ（edge-tts / AivisSpeech）
└── audio.py     # ffmpeg 連結
```

Phase 0 からの進化:

- **SQLite Memory Engine**: characters / relationships / scenes / segments / events / memories を永続化。DBが唯一の情報源（Single Source of Truth）
- **Event Log**: `CHARACTER_CREATED` / `VOICE_ASSIGNED` / `SEGMENT_DIRECTED` / `AUDIO_GENERATED` / `EXPORT_COMPLETED` などを記録
- **Resume**: 中断後に `--resume` でDBの進捗から再開（解析済みチャンク・音声済みセグメントをスキップ）
- **感情の余韻（carryover）**: 直前チャンクの強い感情を時間減衰（`×0.55^チャンク差`）させ、次のチャンクの弱い感情に滲ませる
- **FTS5 全文検索**: 日本語対応（文字分割 + フレーズ検索）。`--search 鈴の音` で記憶を検索

実行：

```bash
cd workers/python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd engine
python main.py ..\..\samples\sample_novel_long.txt            # 全パイプライン（解析→演出→TTS→連結）
python main.py <novel> --resume                               # 中断からの再開
python main.py <novel> --no-tts                               # 解析と演出のみ
python main.py --search 怒鳴                                  # FTS5 検索デモ
python main.py --stats                                        # Event Log 表示
```

出力は `workers/python/engine/output/<book>/`（performance.json / characters.json / story_state.json / audiobook.wav）、
DBは `workers/python/engine/data/story.db` に生成されます。

## ディレクトリ

| ディレクトリ | 内容 |
|---|---|
| `workers/python/` | AIレイヤー（Python隔離地帯） |
| `desktop/` | Phase 3以降：Qt6/QML + C++ Core |
| `cloud/` | Phase 7以降：TS + Fastify |
| `mobile/` | Phase 6以降：Flutter |
| `docs/` | アーキテクチャとADR |
| `samples/` | 動作検証用サンプル小説 |
