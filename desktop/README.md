# Desktop App（Phase 3）

Qt 6 / QML UI + C++20 Core。

## 現状（Phase 3 スケルトン）

`workers/python/engine/worker.py`（JSON-RPC Worker, ADR-0004）を `QProcess` で spawn し、
stdio 通信でエンジンを操作する最小構成が動きます。

```
desktop/
├── CMakeLists.txt     # Qt6 Core/Gui/Quick/QuickControls2 + QML module AIAE
├── build.ps1          # ビルドスクリプト
└── src/
    ├── main.cpp       # アプリ起動・パス解決・bridge 登録
    ├── WorkerBridge.h/.cpp  # QProcess で worker.py を起動 → stdio JSON-RPC 通信
    └── Main.qml       # 本棚 / ジョブ開始 / 進行 / ログ
```

### 機能

- `list_books` / `get_events` で本棚と Event Log を表示
- `start_job` で小説の pipeline 処理（analyze → tts → export）を非同期開始
- `get_job` を 1 秒間隔でポーリングし、Step 進捗バー・checkpoint を表示
- `cancel_job`（協調的キャンセル）、worker の stderr をログ表示

## ビルド手順（Windows）

```powershell
# 1. Qt 6（msys2 mingw64 推奨。Qt 6.9.2 で検証）
pacman -S --needed mingw-w64-x86_64-qt6-base `
             mingw-w64-x86_64-qt6-declarative `
             mingw-w64-x86_64-qt6-quickcontrols2

# 2. ビルド（既定は C:\msys64\mingw64 を見る。別パスなら -QtDir 指定）
cd desktop
.\build.ps1

# 3. 起動
.\build\bin\aiae_desktop.exe
```

オプション:
```powershell
.\build\bin\aiae_desktop.exe --python C:\...\pythonw.exe --worker C:\...\worker.py
```

## 注意

- まだ「スケルトン」。書籍リスト・進行表示・ログは実データに接続済みだが、
  スタイル/応答性など UI はこれから。
- 小説パスは worker 実行側（engine ディレクトリ）からの相対パス。
  既定は `../../samples/sample_novel_long.txt`（リポジトリルート基準で開く場合は绝对パス推奨）。
