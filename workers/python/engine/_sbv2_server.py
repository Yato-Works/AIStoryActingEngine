"""SBV2 サーバ（server_fastapi.py）をバックグラウンドで起動するラッパー。

pythonw では multiprocessing(spawn) の pyopenjtalk worker が起動できないため、
python.exe + CREATE_NO_WINDOW で起動する。
"""
import subprocess
from pathlib import Path

REPO = Path(r"c:\Users\smily\AIStoryActingEngine\third_party\Style-Bert-VITS2")
HERE = Path(__file__).parent
py = REPO / ".venv-sbv2" / "Scripts" / "python.exe"

CREATE_NO_WINDOW = 0x08000000
r = subprocess.Popen(
    [str(py), "server_fastapi.py"],
    cwd=REPO,
    stdout=open(HERE / "_sbv2_server.log", "wb"),
    stderr=subprocess.STDOUT,
    creationflags=CREATE_NO_WINDOW,
)
(HERE / "_sbv2_server.pid").write_text(str(r.pid), encoding="utf-8")