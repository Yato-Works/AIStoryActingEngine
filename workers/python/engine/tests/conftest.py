"""pytest 共通設定: engine モジュールの import パスを解決する。

tests/ 配下のテストは engine 直下のモジュールを import するため、
engine ディレクトリを sys.path に追加する。
"""
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
