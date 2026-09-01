# Style-Bert-VITS2 (SBV2) セットアップ

Phase 2 で追加した `--provider sbv2` は、**別 venv のローカル SBV2 サーバ** (http://127.0.0.1:5000) を
HTTP で消費するだけ（ADR-0001 / ADR-0002 参照）。エンジン本体の venv にはモデルを入れない。

## 1. 自動セットアップ（推奨）

```powershell
# バックグラウンドで実行（venv 作成 → requirements インストール → モデルDL）
cd workers\python\engine
C:\Users\<you>\...\pythonw.exe _sbv2_setup.py    # または通常の python でも可（時間がかかる）
Get-Content _sbv2_setup.done    # "0" になれば成功
Get-Content _sbv2_setup.log -Tail 30
```

やっていること:

1. `third_party/Style-Bert-VITS2` に `.venv-sbv2`（Python 3.10）を作成
2. `uv pip install -r requirements.txt`
3. `python initialize.py --only_infer` — BERT モデル + 既定ボイス
   （`jvnv-M1-jp` / `jvnv-M2-jp` / `jvnv-F1-jp` / `jvnv-F2-jp` + 男性1・女性1の日本語モデル）を DL

> 手動で行う場合は `third_party/Style-Bert-VITS2` 内で上記 1〜3 を実行するだけ。

## 2. サーバ起動

```powershell
cd third_party\Style-Bert-VITS2
.venv-sbv2\Scripts\activate
python server_fastapi.py     # http://127.0.0.1:5000 で待機
```

## 3. 動作確認（スモークテスト）

```powershell
cd workers\python\engine
..\.venv\Scripts\python tests\sbv2_smoke.py
# → output/sbv2_smoke/ に male.wav / female.wav が生成されれば OK
```

## 4. エンジンから使う

```powershell
python main.py ..\..\samples\sample_novel_long.txt --provider sbv2
# 保存先ホストを変える場合
$env:SBV2_HOST = "http://127.0.0.1:5000"
```

## ボイスとモデルの対応（既定のキャスティング）

| voice_id | 性別 | sbv2 モデル | edge-tts |
|---|---|---|---|
| voice_01 / voice_01i(内面) | 男 | jvnv-M1-jp | ja-JP-KeitaNeural |
| voice_02 / voice_02i | 女 | jvnv-F1-jp | ja-JP-NanamiNeural |
| voice_03 / voice_03i | 女(落ち着き) | jvnv-F1-jp | ja-JP-NanamiNeural |
| voice_04 / voice_04i | 男(渋い) | jvnv-M1-jp | ja-JP-KeitaNeural |
| voice_narrator | 男 | jvnv-M1-jp | ja-JP-KeitaNeural |

スタイルは既定 `Neutral`。`/styles` API でモデルごとのスタイル一覧を確認でき、
VoiceProfile.sbv2_style に設定することで感情スタイル（Anger 等がモデルにあれば）も使える。

## トラブルシュート

- **`--provider sbv2` で接続エラー** → サーバが起動しているか `curl http://127.0.0.1:5000/docs`
- **サーバ起動時に `ModuleNotFoundError: pkg_resources`** →
  setuptools>=82 で pkg_resources が削除されているため
  `uv pip install --python .venv-sbv2 "setuptools<81"` でダウングレードする
  （pyopenjtalk が pkg_resources を import するため。`_sbv2_setup.py` は自動で pin 済み）
- **サーバ起動時に transformers が torch 2.5 以上を要求して落ちる** →
  `uv pip install --python .venv-sbv2 "transformers==4.49.0"` でダウングレードする
  （CUDA 版 torch 2.3.1 と組み合わせるため。`_sbv2_setup.py` は自動で pin 済み）
- **`initialize_worker` が TimeoutError** → pyopenjtalk worker（ポート 7861）が
  起動できていない。上記 2 つの依存問題が原因のことが多い。手動で worker を起動して確認:
  `cd third_party\Style-Bert-VITS2; .venv-sbv2\Scripts\python.exe -m style_bert_vits2.nlp.japanese.pyopenjtalk_worker --port 7861`
- **`/voice` が 422 を返す** → パラメータはクエリ文字列で渡す必要がある（フォームボディ不可）。
  エンジンの `StyleBertVITS2Provider` は `params=` で送信するので問題ない
- **初回リクエストが遅い** → BERT/モデルのロードに時間がかかる（初回のみ）
- **VRAM 不足** → Phase 4 で Ollama との VRAM 共存管理を予定。現状は LLM 解析 → TTS の完全逐次で回避
