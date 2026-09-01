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
- [x] **Phase 2** — Voice Director 本格化：人格・関係性・感情状態の維持（Character Intelligence + External/Internal デュアルボイス + Style-Bert-VITS2 対応）
- [ ] **Phase 3** — Desktop：Qt/QML + C++ Core
- [ ] **Phase 4** — Local TTS 統合（GPU利用・VRAM管理）
- [ ] **Phase 5** — PDF / Image（OCR）
- [ ] **Phase 6** — Mobile Player（Flutter・聴くだけ）
- [ ] **Phase 7** — Cloud（Sync / Cloud TTS / Billing）

## Phase 2 の構成（Character Intelligence / Voice Director）

Phase 1 からの進化（詳細は `docs/adr/0002-character-intelligence-and-dual-voice.md`）:

- **Character Profile 拡張**: personality / speech_style / emotional_baseline / emotional_range を解析プロンプトで必須抽出（スキーマ強制）
- **型付き有向関係グラフ**: `loves / friend / rival / despises / ...` の語彙で relationships を保存。対称関係は自動生成、片方向（loves等）は上書きされない
- **Dossier**: Memory Engine が `get_dossier(character, listener, chunk)` で Director への入力を 1 オブジェクトに集約
- **CharacterAwareDirector**: 同じ台詞でも、好きな相手（loves → 柔らかく）と敵（enemy → 張り上げる）で演じ分け。中立台詞には感情の基調（根暗・明るい等）が滲む
- **External/Internal デュアルボイス**: 心の声は別の低い声（voice_XXi）+ 低く静か遅く
- **LLM キャスティング**: キャラ像から External/Internal の 2 声を LLM が提案。不備なら性別/年齢ルールへフォールバック
- **Style-Bert-VITS2 対応**: `--provider sbv2`（ローカルサーバ HTTP クライアント。セットアップは `docs/sbv2-setup.md`）
- **新イベント**: `RELATIONSHIP_CREATED` / `CASTING_COMPLETED`

単体テスト（LLM・TTS 不要）:

```bash
cd workers/python
pip install -r requirements.txt -r requirements-dev.txt
pytest                 # repo ルートの pytest.ini が tests/ を解決（18 tests）
# または従来のスクリプト実行も可能:
python engine/tests/test_phase2.py   # 全 39 項目
```

### Job System（Phase 2.5 / ADR-0003）

`--job` フラグで、パイプライン全体が再開可能な Job（`analyze → tts → export`）として
実行される。進捗・checkpoint・成果物は SQLite（`jobs` / `job_steps` / `job_artifacts`）
に記録され、状態遷移は既存 Event Log に `JOB_*` / `STEP_*` として流れる
（Event Log が Single Source of Truth の原則は維持）。

```bash
python main.py <novel> --job                 # Job System 経由で実行
python main.py <novel> --job --resume        # クラッシュ・中断からの再開
```

TTS Step は 1 セグメントごとに進捗と checkpoint を記録するため、途中で死んでも
DB の done-set から続きを実行できる。詳細は `docs/adr/0003-job-system.md`。

### JSON-RPC Worker（常駐プロセス / ADR-0004）

Desktop（Phase 3）から呼ぶための常駐エンジン。stdio 上の改行区切り JSON-RPC 2.0。

```bash
# 常駐起動（until EOF）
python worker.py

# 1 回テスト（パイプで複数リクエスト）
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | python worker.py
```

主なメソッド: `initialize` / `ping` / `list_books` / `get_events` / `search` /
`start_job`（非同期実行, 即 job_id 返却）/ `get_job`（進捗ポーリング）/
`cancel_job`（協調的キャンセル）。詳細は `docs/adr/0004-json-rpc-worker.md`。


## Phase 1 の構成（Story Engine）

```
workers/python/engine/
├── main.py      # パイプライン起動（CLI）
├── schema.py    # performance.json 等の契約スキーマ
├── models.py    # データモデル（Pydantic）
├── memory.py    # Memory Engine（SQLite + Event Log + FTS5 + 感情の余韻）
├── analyzer.py  # Story Analyzer (Ollama)
├── voices.py    # Voice Profile プール（Casting / TTS 共有レジストリ）
├── director.py  # Casting + Voice Director (Rule Engine)
├── tts.py       # TTS Provider アダプタ（edge-tts / SBV2 / AivisSpeech）
└── audio.py     # ffmpeg 連結
```

Phase 0 からの進化:

- **SQLite Memory Engine**: characters / relationships / scenes / segments / events / memories を永続化。DBが唯一の情報源（Single Source of Truth）
- **Event Log**: `CHARACTER_CREATED` / `VOICE_ASSIGNED` / `SEGMENT_DIRECTED` / `AUDIO_GENERATED` / `EXPORT_COMPLETED` などを記録
- **Resume**: 中断後に `--resume` でDBの進捗から再開（解析済みチャンク・音声済みセグメントをスキップ）
- **感情の余韻（carryover）**: 直前チャンクの強い感情を時間減衰（`×0.55^チャンク差`）させ、次のチャンクの弱い感情に滲ませる
- **FTS5 全文検索**: 日本語対応（文字分割 + フレーズ検索）。`--search 鈴の音` で記憶を検索

実行（デフォルト: edge-tts）:

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

Style-Bert-VITS2（ローカル高品質TTS）で走らせる場合:

```bash
# 事前に docs/sbv2-setup.md に従って別 venv の SBV2 サーバを起動しておく
python main.py ..\..\samples\sample_novel_long.txt --provider sbv2
```

出力は `workers/python/engine/output/<book>/`（performance.json / characters.json / story_state.json / audiobook.wav / **audiobook.m4b（章チャプター埋め込み）**）、
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
