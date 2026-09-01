# ADR-0004: JSON-RPC Worker（常駐化・Phase 3 Desktop 制御入口）

## 状態

採用（Phase 2.5）

## 背景

Phase 2.5 までに Job System（ADR-0003）ができ、パイプラインは再開可能になった。
残るは「どう呼ぶか」。Qt/C++（Phase 3）から呼ぶとき、プロセス毎起動の
CLI（`main.py <novel>`）では遅すぎるし、ポートを開く HTTP は
ファイアウォール・オフジェクト競合の管理が要る。

## 決定

**stdio 上の改行区切り JSON-RPC 2.0（LSP 方式）** を採用する。

```
C++ (Qt) ──spawn──▶ pythonw worker.py
                stdin  : 1 リクエスト 1 行の JSON
                stdout : 1 レスポンス 1 行の JSON（プロトコル専用）
                stderr : パイプラインのログ退避先
```

- ポート競合なし・プロセス管理が自然（親死なら子も終了）。
- 常駐なので 2 回目以降のリクエストが軽い（モデルロード等もキャッシュ可能）。
- ジョブ実行中のログ（`print`）は `redirect_stdout(sys.stderr)` で
  **stdout を汚染しない**。これで改行区切りプロトコルが壊れない。

### メソッド v1

| メソッド | params | 説明 |
|---|---|---|
| `initialize` | - | 能力・プロトコルバージョン・DB パス |
| `ping` | - | 生存確認 |
| `list_books` | - | 登録済み書籍 |
| `get_events` | `limit`, `type?` | Event Log の直近 N 件（SSOT へのアクセス） |
| `search` | `query`, `limit?` | FTS5 記憶検索 |
| `start_job` | `novel`, `provider?`, `resume?`, `no_tts?`, `model?` | pipeline Job を非同期開始 → 直ちに `job_id` 返却 |
| `get_job` | `job_id` | Job / Step / checkpoint / 成果物（ポーリング用） |
| `cancel_job` | `job_id` | 協調的キャンセル要求 |

非同期実行はバックグラウンドスレッド。状態は常に DB（Job System）が真実源で、
`get_job` で進捗を読む。`cancel_job` は `should_stop()` フラグを立て、
Analyze/TTS Step が次のチャンク/セグメント境界で `JobCancelled` を raise →
Job は `CANCELLED` 遷移する（破壊的 kill ではなく協調的）。

## 結果

- Python Worker は `python worker.py`（別プロセス常駐）で動かせる。
- Phase 3 の C++ Runtime は subprocess 起動 → `initialize` → `start_job` →
  `get_job` ポーリング、の流れで UI とデータを同期できる。
- エラーは JSON-RPC error コードで返る（`-32700` parse, `-32601` method,
  `-32602` params, `-32603` internal）。