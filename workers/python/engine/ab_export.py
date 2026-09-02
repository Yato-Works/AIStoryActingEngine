"""Phase 3.5U - ab_export: Human A/B Listening session generator。

KPI 4 本柱「Automated Tests + Acoustic Metrics + Performance Judge +
Human A/B Listening」の最後の 1 本。

seed 違いで 2 演技を合成し、**盲検**（どちらがどの seed か分からない形式）で
出力する。人間が variant_1 / variant_2 のどちらが人間っぽいか票を入れ、
listening_sheet.csv に記入する。対応表は answer_key.json（session_seed で
再生可能）に保存し、集計時に開封する。

使い方:
  python ab_export.py <book_id> --provider edge --limit 5
  python ab_export.py <book_id> --seed-a 42 --seed-b 1337 --session-seed 7
出力（ab_session/<book_id>/ 以下）:
  <seg_id>__variant_1.wav / variant_2.wav   盲検用 2 演技
  answer_key.json                           variant -> seed 対応（集計時に開封）
  listening_sheet.csv                       人間の投票シート
  playlist.html                             ブラウザ用再生リスト
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from human_voice import render_segment, seed_for
from models import VoiceProfile, VoiceState
from tts import get_provider

DB_PATH = Path(__file__).parent / "data" / "story.db"


def _playlist_html(seg_ids):
    rows = "".join(
        f"""<tr><td>{sid}</td>
<td><audio controls src="{sid}__variant_1.wav"></audio></td>
<td><audio controls src="{sid}__variant_2.wav"></audio></td>
<td><input type="radio" name="{sid}" value="1">1
    <input type="radio" name="{sid}" value="2">2</td></tr>"""
        for sid in seg_ids)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Blind A/B Listening</title></head><body>
<h1>Blind A/B — どちらが人間っぽい?</h1>
<p>各セグメントで variant_1 / variant_2 を聴き比べ、票を listening_sheet.csv に記入してください。</p>
<table border="1" cellpadding="6"><tr><th>segment</th><th>variant_1</th><th>variant_2</th><th>your pick</th></tr>
{rows}</table>
<p>※対応表（どちらが seed A か）は answer_key.json — 集計時まで開かないこと。</p>
</body></html>"""


def build_ab_session(memory, out_dir: Path, provider_name: str = "edge",
                     seg_ids: list[str] | None = None, limit: int = 5,
                     seed_a: int = 42, seed_b: int = 1337,
                     session_seed: int = 0) -> dict:
    """音声済みセグメントを seed 違いで 2 演技合成し、盲検 A/B セッションを作る。

    戻り値は {seg_id: {"variant_1": "A"|"B", "variant_2": ...}}。
    対応は session_seed で決定論的にシャッフルされる（同じ session_seed なら
    同じ割り当て -> 別マシンでも同じ盲検セッションを再構築できる）。
    """
    from main import _hve_profile_table

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = get_provider(provider_name)
    table = _hve_profile_table(memory)

    done = memory.audio_done()
    by_id = {s.id: s for s in memory.load_segments()
             if s.performance and s.id in done}
    ids = sorted(by_id)
    if seg_ids:
        ids = [sid for sid in ids if sid in set(seg_ids)]
    ids = ids[:max(0, limit)]
    if not ids:
        raise SystemExit("A/B 用の音声済みセグメントがありません"
                         "（先にパイプラインを実行してください）")

    rng = random.Random(session_seed)
    answer_key: dict = {}
    for sid in ids:
        seg = by_id[sid]
        prof, st = table.get(
            seg.performance.voice,
            (VoiceProfile(voice_id=seg.performance.voice), VoiceState()))
        first_is_a = rng.random() < 0.5
        labels = {"variant_1": "A" if first_is_a else "B",
                  "variant_2": "B" if first_is_a else "A"}
        seeds = {"A": seed_a, "B": seed_b}
        for variant, label in labels.items():
            render_segment(seg, prof, st, provider,
                           out_dir / f"{sid}__{variant}.wav",
                           seed=seed_for(sid) + seeds[label])
        answer_key[sid] = {"variant_1": labels["variant_1"],
                           "variant_2": labels["variant_2"],
                           "seed_a": seed_a, "seed_b": seed_b}

    (out_dir / "answer_key.json").write_text(
        json.dumps({"session_seed": session_seed, "seed_a": seed_a,
                    "seed_b": seed_b, "segments": answer_key},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "listening_sheet.csv").open("w", newline="",
                                                encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seg_id", "prefer(1/2)", "notes"])
        for sid in ids:
            w.writerow([sid, "", ""])
    (out_dir / "playlist.html").write_text(_playlist_html(ids), encoding="utf-8")
    return answer_key


def main() -> None:
    from memory import MemoryEngine

    ap = argparse.ArgumentParser(description="Human A/B Listening generator")
    ap.add_argument("book_id", help="DB 内の book_id（--list で一覧）")
    ap.add_argument("--provider", default="edge")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--seed-a", type=int, default=42)
    ap.add_argument("--seed-b", type=int, default=1337)
    ap.add_argument("--session-seed", type=int, default=0)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "output" / "ab_session")
    ap.add_argument("--list", action="store_true", help="book_id 一覧を表示")
    args = ap.parse_args()

    if args.list:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT id, title FROM books ORDER BY created_at"):
            print(f"  {r['id']}: {r['title']}")
        conn.close()
        return

    memory = MemoryEngine(DB_PATH, args.book_id)
    try:
        key = build_ab_session(memory, args.out / args.book_id,
                               provider_name=args.provider, limit=args.limit,
                               seed_a=args.seed_a, seed_b=args.seed_b,
                               session_seed=args.session_seed)
    finally:
        memory.close()
    print(f"🎧 A/B session: {args.out / args.book_id}")
    print(f"   segments: {len(key)} / answer_key.json + listening_sheet.csv + playlist.html")
    print("   集計時まで answer_key.json を開かないこと!")


if __name__ == "__main__":
    main()