# ADR-0002: Character Intelligence と External/Internal デュアルボイス

- ステータス: Accepted (Phase 2)
- 関連: ADR-0001（AIモデルをアプリ本体にしない）

## 背景

Phase 1 では演技が「セグメント単位の感情 × 固定ボイス」だった。 known limits:

- LLM が gender/role/traits をしばしば省略 → キャスティングがフォールバックだらけ
- relationships が自由テキストで空になりがち → 関係性が演技に使えない
- 心の声と台詞が同じ声 → 内面と外面の区別がつかない

## 決定

1. **Character Profile の拡張**: `personality` / `speech_style` / `emotional_baseline` /
   `emotional_range` を Character に追加し、解析プロンプトで抽出を必須化（JSON schema required）。
   DB は列追加マイグレーションで Phase 1 と互換を保つ。
2. **型付き有向関係グラフ**: relationships を `loves / friend / family / rival / respects /
   despises / ...` の語彙（`schema.RELATIONSHIP_TYPES` + エイリアス正規化）で有向エッジとして保存。
   対称型（friend 等）は逆向きを自動生成するが、**既存の有向エッジは上書きしない**（片思いを守る）。
3. **Dossier 集約**: Memory Engine が `get_dossier(character, listener, chunk)` を提供し、
   Director への入力はこれ 1 つに限定する。人物+聞き手+関係+感情の余韻+直近の感情記憶+場面。
4. **CharacterAwareDirector**: Dossier だけを見て Performance を決める。
   - 余韻（carryover）→ 基調（baseline）の優先順位で感情を決定
   - `dialogue` は聞き手との関係タイプで pitch/pace/volume を微調整（同じ台詞でも演じ分け）
   - `speech_style`（polite/rough/quiet...）で常時調整
   - `inner_monologue` は Internal 声 + 低く・遅く・静かに
5. **External/Internal デュアルボイス**: 各キャラに外向きの声（voice_XX）と
   内面の声（voice_XXi、pitch −0.10 / pace ×0.88）を持たせる。
   キャスティングは LLM 提案（`suggest_voice`、スキーマ強制）→ 不備なら性別/年齢ルールへフォールバック。
6. **SBV2 は HTTP クライアント**: `--provider sbv2` は localhost:5000 の
   Style-Bert-VITS2 サーバ（別 venv / 別プロセス）に `model_name` + `style` を POST する。
   VRAM 管理は Phase 4。edge-tts は既定のまま（依存ゼロのフォールバック）。
7. **Performance 契約の v2**: `voicing`（external/internal/narrator）と `style`、
   演出の透明化用に `carryover` / `baseline` / `relationship` を追加（全て下位互換のデフォルト付き）。
8. **新イベント**: `RELATIONSHIP_CREATED` / `CASTING_COMPLETED` を Event Log に追加。

## 結果

- 同じ台詞が関係によって演じ分けられる（loves → 柔らかく / enemy → 張り上げる）
- 心の声が物理的に別の声になり、内面描写が「聞き取れる」
- 中立台詞でもキャラの感情基調（根暗・明るい等）が滲む
- LLM 抽出の漏れがあっても契約レベルで強制（required + 正規化）されフォールバックが減る

## 非目標（Phase 2 ではやらない）

- 聞き手（addressee）の LLM による高精度推定（暫定: 直前の別話者）
- SBV2 の感情スタイル語彙の自動マッピング（手設定の sbv2_style のみ）
- VRAM の動的スワップ（Phase 4）
