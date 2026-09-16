# ADR 0006: Reading Script Layer（読み台本レイヤー / Script Writer）

- Status: Accepted
- Date: 2026-09-16

## Context

Irodori-TTS（v4.1-Small）を Backend として採用するにあたり、公式に明記された
弱点がある: **漢字の読み精度が同規模の TTS と比べて弱い**。
常用漢字ベンチマークでも Kana-CER 約 7% が残り、珍しい人名・専門用語・
文脈依存の読み（貼付 = はりつけ / ちょうふ 等）は誤読しうる。

危険な漢字だけを検出してルビを振る「判定基準」方式は、
どの漢字が落ちるか事前に予測できないため不採用とする。
原則として **全文かな化（all-kana conversion）** を採用する。

メタファー: 「声は天才だが漢字が読めない演者さん」のために、
AI 台本家が**文脈を読解した上で読み仮名付きの台本**を書く。

## Decision

### 1. 全文かな化（All-Kana Principle）

TTS に渡すテキストは原則としてかなのみに変換する。
- 原文（漢字表記）は失わない: `ReadingScript` セグメントに `text`（原文）と
  `text_reading`（かな版）を両方保持する。
- 原文は字幕・Memory Engine・FTS5 検索のソースであり続ける。
- かなはどの TTS でも安定して読めるため、本レイヤーは backend 非依存
  （Irodori 以外でも利用可能）。

### 2. 検証は「漢字残留チェック」のみ

判定基準 AI のような不安定な仕組みは作らない。
決定論的チェック 1 つ: **`text_reading` に元テキスト由来の漢字が残っていないか**。
残っている場合は未カバーとして報告し、呼び出し側が差し戻しを判断する。

### 3. ReadingDictionary — 読みの一貫性はデータベースが保証する

- 表記 → 読み のフラット辞書。**Easy-Irodori-TTS の
  `reading_dictionary.json` と同一形式**（JSON 相互運用）で入出力可能。
- 保存先は JSON ファイルまたは SQLite（`readings` テーブル）。
  どちらも同じ `ReadingDictionary` インターフェースで扱う。
- 適用は**最長一致・決定論的**（LLM 不要、合成ごとに安定）。
- 一度決めた読み（千早 → ちはや）は作品全体で強制統一され、
  チャンクをまたいだ読みの揺れ（7 章で突然別の読み方になる事故）を
  構造的に防ぐ。
- **辞書は Script Writer の LLM 出力よりも強い**: LLM が辞書に反する
  かなを書いても、適用時に辞書側で上書きされる。

### 4. Script Writer — 台本家 AI（LLM, チャンクごと 1 回）

Story Analyzer と同じ Ollama パターン（schema 強制 + JSON 抽出）で実装する。

入力: セグメント群（原文） + キャラ名鑑 + 既存辞書
出力（schema 強制）:
```json
{
  "segments": [{"id": "...", "text_reading": "全文かなの台詞"}],
  "readings": [{"surface": "千早", "reading": "ちはや"}]
}
```

後処理（決定論的）:
1. `readings` を辞書候補として取り込む
2. 辞書（既存 + 新規）を `text_reading` に適用して正規化（辞書が最強）
3. 漢字残留チェック → 未カバー報告

### 5. Irodori Backend との接続（ADR-0005 拡張）

- ActingIR `backend_options["irodori"]` に
  `text_reading`（変換済みかな）または `dictionary`（ReadingDictionary）を
  渡せる。Backend はあれば優先して使用し、なければ原文を渡す。
- BackendManifest に `text_reading` を宣言:
  Irodori = `instruction`（受け入れ必須）、SBV2 等 = `unsupported`（不要）。

### 6. 合成は 1 パス

かな化・絵文字付与・キャプション生成は同一パスで適用し、
合成は 1 回で行う。A/B 比較のときのみ意図的に複数バージョンを生成する。

## Consequences

- **読み精度の問題は構造的に解決**: 漢字そのものを TTS に渡さない。
- **判定基準の保守が不要**: チェックは「漢字が残っていないか」1 つ。
- **コスト**: Script Writer の LLM 呼び出しがチャンクごとに 1 回追加
  （Story Analyzer と同一パターン、qwen3:4b 等で動作）。
- **将来の漢字読み改良に追従可能**: モデルが改良されたら
  `text_reading` を渡さなければ原文のまま使える（挙動は Backend 側で切替）。
- SQLite 統合は既存 Memory Engine に触れず、独立した小さなテーブルで実装する。
