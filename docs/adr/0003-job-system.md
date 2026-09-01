# ADR-0003: Job System（再開可能な実行基盤）

## 状態

採用（Phase 2.5）

## 背景

Phase 2 までのパイプラインは「一発実行 + `--resume`」だった。Desktop 化（Phase 3）に向け、
C++ Runtime が「今どの Job のどの Step を実行しているか」を DB から把握し、
Worker が死んでも続きから再開できる実行基盤が必要。

## 決定

**Event Log が Single Source of Truth という原則は変えない。** Job System は
新しいログを作らず、既存 `events` テーブルに `JOB_*` / `STEP_*` イベントを流す。
`jobs` / `job_steps` / `job_artifacts` は「現在状態のクエリ用ビュー + checkpoint」
であり、履歴の真実源は events のままである。

### スキーマ v1

```sql
jobs(id PK, book_id, type, status, payload, error, created_at, updated_at)
job_steps(job_id+seq PK, name, status, progress, progress_total,
          checkpoint, error, started_at, finished_at, updated_at)
job_artifacts(job_id+step_seq+kind+path PK, created_at)
```

### 状態遷移

```
pending → running → completed | failed
failed  → running（resume / retry）
pending → cancelled | skipped / running → cancelled
completed / cancelled / skipped は終端
```

不正な遷移は `JobSystemError`。同一状態への遷移は冪等（何もしない）。

### 冪等性と Resume

- **Step は冪等**: `run_step()` は completed な Step を再実行しない。
- **細かい再開の真実源は既存の done-set**（`chunk_analysis` / `segments.audio_path`）。
  job_steps.checkpoint は観測用の最新位置（例: `{"segment": "seg_030"}`）。
- **クラッシュ復旧**: 前回 running のまま残った Step は `recover_running_steps()`
  で failed にし、resume 時に fn が done-set から続きを実行する。
- **ジョブ再利用**: `resume_or_create()` は同種の未完了 Job を再利用
  （failed → running 復帰含む）。完了 Job は新規作成。

### Job と Event Log の対応

| 状態変化 | イベント |
|---|---|
| Job 作成 | `JOB_CREATED` |
| Job 開始/完了/失敗/取消 | `JOB_STARTED` / `JOB_COMPLETED` / `JOB_FAILED` / `JOB_CANCELLED` |
| Step 開始/完了/失敗/スキップ | `STEP_STARTED` / `STEP_COMPLETED` / `STEP_FAILED` / `STEP_SKIPPED` |

## 結果

- Python Worker は `run_pipeline_job()` で pipeline Job
  （steps: analyze → tts → export）を実行する。
- C++ Runtime（Phase 3）は `jobs` / `job_steps` の status / progress /
  checkpoint を監視するだけで UI 表示と再開制御ができる。
- CLI は `--job` フラグで Job System 経由を実行（無指定なら従来通り）。
