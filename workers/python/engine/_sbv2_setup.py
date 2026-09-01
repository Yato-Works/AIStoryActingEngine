"""バックグラウンド実行ラッパー: SBV2 環境構築（venv → 依存 → モデルDL）。"""
import subprocess
from pathlib import Path

REPO = Path(r"c:\Users\smily\AIStoryActingEngine\third_party\Style-Bert-VITS2")
HERE = Path(__file__).parent
LOG = HERE / "_sbv2_setup.log"

log_lines: list[str] = []


def log(msg: str) -> None:
    log_lines.append(msg)
    LOG.write_text("\n".join(log_lines), encoding="utf-8")


def run(cmd: list[str], cwd: Path) -> int:
    log(f"$ {' '.join(cmd)}")
    # capture_output のパイプはプログレスバー出力で詰まるため、直接ファイルに書く
    with open(LOG, "a", encoding="utf-8") as fp:
        r = subprocess.run(cmd, cwd=cwd, stdout=fp, stderr=fp,
                           text=True, encoding="utf-8", errors="replace")
    log(f"→ exit {r.returncode}")
    return r.returncode


code = 0
if not (REPO / ".venv-sbv2" / "pyvenv.cfg").exists():
    code += run(["uv", "venv", "--python", "3.10", ".venv-sbv2"], REPO)
# CUDA 対応 torch（RTX 3050）。失敗しても requirements-infer 内の CPU 版にフォールバック
torch_rc = run(["uv", "pip", "install", "--python", ".venv-sbv2",
                "torch==2.3.1", "torchaudio==2.3.1",
                "--index-url", "https://download.pytorch.org/whl/cu121"], REPO)
log(f"torch(cu121) rc={torch_rc}（失敗なら CPU 版へフォールバック）")
# faster-whisper / librosa 等の学習・文字起こし系依存を除いた推論のみの requirements
code += run(["uv", "pip", "install", "--python", ".venv-sbv2",
             "-r", "requirements-infer.txt"], REPO)
if code == 0:
    code = run([str(REPO / ".venv-sbv2" / "Scripts" / "python.exe"),
                "initialize.py", "--only_infer"], REPO)
# pyopenjtalk は pkg_resources を要求する（setuptools>=82 で削除済み）
# transformers 5.x は torch>=2.5 を要求するため torch 2.3.1 と競合する
code += run(["uv", "pip", "install", "--python", ".venv-sbv2",
             "setuptools<81", "transformers==4.49.0"], REPO)
(HERE / "_sbv2_setup.done").write_text(str(code), encoding="utf-8")
