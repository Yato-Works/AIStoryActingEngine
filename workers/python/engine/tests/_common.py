"""テスト共通ユーティリティ（カウンタを単一モジュールで管理）。"""

_passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        raise AssertionError(name)


def passed() -> int:
    return _passed