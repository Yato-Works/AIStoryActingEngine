# アーキテクチャ

> Single Source of Truth。変更時はこのドキュメントと ADR を更新すること。

## 全体構成

```
                         ┌────────────────────┐
                         │    📱 Mobile App   │
                         │   iOS / Android    │
                         └─────────┬──────────┘
                                   │
                              Sync / API
                                   │
┌──────────────────────────────────┼──────────────────────────────────┐
│                                  ↓                                  │
│                         ☁️ Cloud Backend                            │
│                                                                      │
│  Auth ── API ── Job Queue ── Cloud AI ── Cloud TTS ── Storage      │
│                                  │                                   │
└──────────────────────────────────┼──────────────────────────────────┘
                                   │
                              Local / Cloud
                                   │
┌──────────────────────────────────┼──────────────────────────────────┐
│                         🖥️ Desktop App                              │
│                                                                      │
│   Qt/QML UI                                                          │
│       │                                                              │
│   C++ Runtime                                                        │
│       │                                                              │
│   ┌───┼────────┬──────────┬──────────┬──────────┐                  │
│   ↓   ↓        ↓          ↓          ↓          ↓                  │
│  OCR Story   Memory    Director    TTS       Audio                │
│       │      Engine                Engine     Engine               │
│       └────────────── SQLite ────────────────┘                     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## 最重要原則

**AIモデルをアプリ本体にしない。**

TTSは交換可能な末端。本当の資産は：

- Character Memory
- Scene State
- Voice Profile
- Performance Direction
- Job / Event System

モデル世代交代（SBV2 → Qwen3-TTS → Qwen4-TTS → …）はプラグイン差し替えで吸収する。

## レイヤー

### Desktop Core（C++20/23）

担当：ファイルI/O、SQLite、Job Queue、非同期処理、Audio pipeline、FFmpeg、
TTS process管理、GPU backend、Plugin system、IPC、Network、大量データ処理。

境界は `QML → C++ API → Runtime`。

### AI Layer（Python）

PythonをCoreにしない。Python Workerとして隔離：

```
C++ → Python Worker → Transformers / TTS / OCR → Result JSON → C++
```

PyTorch / Transformers / ONNX Runtime / llama.cpp bindings / TTS / OCR / embedding はすべてこの中に閉じる。

Phase 2.5 で常駐 Worker 化（ADR-0004）: `worker.py` が stdio 上の JSON-RPC 2.0 で
`start_job` / `get_job` / `cancel_job` を提供。ジョブ実行はバックグラウンドスレッド、
状態は Job System（jobs/job_steps）が DB に記録し、C++ がポーリングする。

### LLM Abstraction

```
IStoryAnalyzer
       │
 ┌─────┼──────────┐
 ↓     ↓          ↓
Gemini  Ollama    Local LLM
```

```cpp
class IStoryAnalyzer {
public:
    virtual StoryAnalysis analyze(
        const DocumentChunk& chunk,
        const StoryContext& context
    ) = 0;
};
```

Local LLMは最初Ollama（HTTP API）。将来的に llama.cpp 完全組み込み（GGUF）も選択肢。

### OCR

- EPUB/TXT → OCR不要
- PDF text layer → Parser
- PDF 画像 / スキャン → OCR（PaddleOCR / Tesseract検証）+ Vision LLM 補正

### Memory Engine

SQLiteから始める。Qdrant等は最初から入れない。

- `characters` / `relationships` / `scenes` / `events` / `memories` / `segments` / `voice_profiles`
- SQLite FTS5 で全文検索
- Vector Search は必要になってから追加（sqlite-vec 等）

### Voice Director（本アプリ最大のコア）

```
Input → Speaker Detection → Character Memory → Scene State
      → Emotion Analysis → Performance Planning → Voice Selection
```

Phase 2 以降の Director への入力は **Dossier 1 つ**（Memory Engine が集約）:

```
Dossier = 人物(personality/speech_style/感情基調/起伏)
        + 聞き手との型付き有向関係(loves/friend/rival/...)
        + 感情の余韻(前チャンク ×0.55^chunk_gap)
        + 直近の感情記憶 + 場面
```

出力は `performance.json`（中核データ構造、Phase 2 契約 v2）：

```json
{
  "speaker": "character_01",
  "voice": "voice_07",
  "mode": "internal",
  "emotion": "sarcastic",
  "intensity": 0.42,
  "pace": 0.91,
  "pitch": -0.08,
  "voicing": "internal",
  "style": "Neutral",
  "carryover": false,
  "baseline": false,
  "relationship": "loves"
}
```

### External / Internal デュアルボイス

キャラクターは外向きの声（`voice`）と内面の声（`voice_internal`、低く・遅い）を 1 組で持つ。
`inner_monologue` は Internal 声で発話され、関係タイプと話し方（speech_style）で
dialogue が相手ごとに演じ分けられる。詳細は ADR-0002。

### Voice Profile と Performance の分離

- **Voice Profile**（キャラ固有・不変）：base voice / gender / age / pitch / timbre / tts_voice / sbv2_model_name / sbv2_style
- **Performance**（セグメント毎・可変）：emotion / intensity / pace / pitch_delta / volume / voicing / style

これにより「同じキャラでも怒る・泣く・小声・心の声・叫ぶ」を表現でき、
将来的な「普段は女性声2、心情では男性声3」のような高度なキャスティングに繋がる。

### TTS Layer（プラグイン式）

```
ITTSProvider
      │
 ┌────┼───────────────┐
 ↓    ↓               ↓
SBV2  Qwen3-TTS    Cloud TTS
```

Local: Style-Bert-VITS2 / Qwen3-TTS / AivisSpeech
Cloud: ElevenLabs / Other

### Audio Engine

FFmpeg で `segment_001.wav...` → M4B（チャプター・cover・metadata埋め込み）。
Phase 2.5 でチャプター対応済み: `scenes` テーブルの章ごとの先頭シーン説明を
チャプタータイトルに変換し、ffmetadata 経由で `audiobook.m4b`（AAC 96kbps）に埋め込む。

### Job System

```
IMPORT_BOOK → OCR → ANALYZE → CAST → DIRECT → TTS → MIX → EXPORT
```

状態：`Pending / Running / Completed / Failed / Cancelled`

Phase 2.5 で Python Worker 側に実装済み（ADR-0003）: `--job` で pipeline Job
（analyze → tts → export）が走り、進捗 / checkpoint / 成果物は
`jobs` / `job_steps` / `job_artifacts` テーブルに記録される。状態遷移は
Event Log に `JOB_*` / `STEP_*` として流れ、**Event Log が SSOT の原則は維持**。
Phase 3 の C++ Runtime はこのテーブルを監視するだけで UI 進捗表示と再開制御が可能。

### Event Log

`BOOK_IMPORTED / CHARACTER_CREATED / RELATIONSHIP_CREATED / VOICE_ASSIGNED /
CASTING_COMPLETED / SEGMENT_DIRECTED / AUDIO_GENERATED`
を Single Source of Truth にし、PC再起動からでもジョブ再開を可能にする。

### Cloud Backend

- API: TypeScript + Fastify
- DB: PostgreSQL（users / books / projects / characters / memories / jobs / subscriptions）
- Object Storage: S3 / R2 / B2（音声はDBに入れない）
- Queue: Redis + BullMQ
- Auth: OAuth/OIDC
- Payments: Stripe 等

思想：**Local版を無料で成立させる。Cloudは「AIを買う」のではなく計算資源と手軽さを買う。**

### Mobile / Sync

- Flutter（iOS/Android）再生・同期・ライブラリUI
- 同期対象：Metadata / Characters / Memory / Book State / Playback Position（音声は必要なものだけDL）

## 開発フェーズ

| Phase | 内容 |
|---|---|
| 0 | PoC（Python）：TXT → LLM → Character → Emotion → Casting → Direction → TTS → WAV |
| 1 | Story Engine：Character / Scene / Relationship / Memory をSQLiteへ |
| 2 | Voice Director 本格化（Character Intelligence + デュアルボイス + SBV2） ✅ |
| 3 | Desktop（Qt/QML + C++） |
| 4 | Local TTS 統合（GPU / VRAM管理） |
| 5 | PDF / Image（OCR） |
| 6 | Mobile Player |
| 7 | Cloud |

### Phase 0 完成条件

- 複数キャラクター認識
- 話者割り当て
- ナレーション分離
- 内面描写（inner_monologue）分離
- 感情推定
- キャラクターごとの Voice Profile 割り当て
- セグメントごとの音声生成
- 連結して聴ける（audiobook.wav）

### Phase 0 の制約

- RTX 3050 8GB：LLM → メモリ解放 → TTS の完全逐次処理
- PoCで重要なのは速度ではなく「キャラクターと演技が自然に繋がるか」
