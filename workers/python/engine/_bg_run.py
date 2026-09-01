"""バックグラウンド実行ラッパー: main.py を起動し、出力を run.log / run_err.log へ。"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
VENV_PY = HERE.parent / ".venv" / "Scripts" / "python.exe"
args = [str(VENV_PY if VENV_PY.exists() else sys.executable),
        str(HERE / "main.py")] + sys.argv[1:]
r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", cwd=HERE)
(HERE / "run.log").write_text(r.stdout or "", encoding="utf-8")
(HERE / "run_err.log").write_text(r.stderr or "", encoding="utf-8")
(HERE / "run.done").write_text(str(r.returncode), encoding="utf-8")
