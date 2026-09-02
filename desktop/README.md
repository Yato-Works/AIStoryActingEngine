# Desktop App（Phase 3 / 3.5U）

Qt 6 / QML UI + C++20 Core。**Spotify 風ダーク UI の Audiobook プレイヤー**。

```
desktop/
├── CMakeLists.txt           # Qt6 Core/Gui/Quick/QuickControls2/Multimedia + QML module AIAE
├── build.ps1                # ビルドスクリプト
└── src/
    ├── main.cpp             # アプリ起動・パス解決・bridge 登録
    ├── WorkerBridge.h/.cpp  # QProcess で worker.py を起動 → stdio JSON-RPC 通信
    ├── Main.qml             # シェル: サイドバー + ページ切替 + bridge 配線
    ├── BookshelfPage.qml    # 📚 ライブラリ: 表紙カード + 音声進捗バー + ホバー再生
    ├── PlayerPage.qml       # ▶ 大ジャケット + 章リスト（章シーク）
    ├── StudioPage.qml       # 🎙 本の詳細 + Event Log（SCENE_EVENT / VOICE_STATE_CHANGED 等）
    └── NowPlayingBar.qml    # 下部常時バー: ±15s / 速度 / 音量 / シーク
```

### 機能

- **ライブラリ**: 本ごとのグラデ表紙（id から決定論的色相生成）、audio_done/segments 進捗バー、
  空のときは案内メッセージ（真っ白にならない）
- **プレイヤー**: 章リストのクリックで章シーク（offset_seconds）、±15秒スキップ、
  再生速度 0.8x–2.0x、音量、総長表示
- **スタジオ**: Event Log（SSOT）を色分け表示 — 3.5Q/R の SceneEvent・Judge 結果が流れる
- Worker 未接続時はステータスドット（赤/緑）で表示

## ビルド手順（Windows）

```powershell
# 1. Qt 6（msys2 mingw64 推奨。Qt 6.9.2 で検証）
pacman -S --needed mingw-w64-x86_64-qt6-base `
             mingw-w64-x86_64-qt6-declarative `
             mingw-w64-x86_64-qt6-quickcontrols2 `
             mingw-w64-x86_64-qt6-multimedia

# 2. ビルド（既定は C:\msys64\mingw64 を見る。別パスなら -QtDir 指定）
cd desktop
.\build.ps1

# 3. 起動
.\build\aiae_desktop.exe
```

オプション:
```powershell
.\build\aiae_desktop.exe --python C:\...\python.exe --worker C:\...\worker.py
```

## 注意

- 本のデータは `workers/python/engine/data/story.db`（worker の `list_books` / `get_book`）。
  音声は completed Job の `job_artifacts`（m4b 優先）から解決される。
- 音声未生成の本は「音声ファイルなし」と表示され、解析情報だけ見られる。
