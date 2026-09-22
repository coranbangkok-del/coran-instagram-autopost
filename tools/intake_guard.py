# -*- coding: utf-8 -*-
"""
写真取り込みPR（routine/photo-intake-*）を自動マージしてよいかの門番。

    python tools/intake_guard.py <base-ref>          # 例: origin/main
    python tools/intake_guard.py --files <status-file>  # 単体試験用（"A\\tpath" の行）

自動マージしてよいのは、変更が次だけのときに限る（それ以外が1つでもあれば「社長マージ」に回す）:
  - 追加（A）: images/<既存カテゴリ>/<ファイル名>.jpg|jpeg|png
               ※ images/generated/（従来経路の生成物）と images/calendar/（承認対象の画像）は不可
  - 変更（M）: images/manifest.json だけ（しかも tools/build_manifest.py で作り直した結果と一致すること）
  - 削除・改名・既存画像の上書き・コード・ワークフロー・カレンダー・state/ の変更は不可
  - 「確認済み」の記録（seen.json）は team-takuro 側にあり、この repo の PR には出てこない

CI ではこのファイルを **main の版** で実行する（PR 側で門番を書き換えても効かないように）。
終了コード: 0=自動マージ可 / 1=不可（理由を表示）/ 2=使い方の誤り
"""
import os
import re
import subprocess
import sys

MAX_FILES = 80
MAX_BYTES = 6 * 1024 * 1024       # 取り込みは長辺2400px・品質88に縮小する手順＝通常 1〜2MB
IMAGE_RE = re.compile(r"^images/([a-z0-9-]+)/([A-Za-z0-9._-]+)\.(jpg|jpeg|png)$")
FORBIDDEN_DIRS = {"generated", "calendar"}
MANIFEST = "images/manifest.json"


def check(entries, existing_categories, sizes=None):
    """entries: [(status, path)]。戻り値: 問題点のリスト（空＝自動マージ可）。"""
    errs = []
    sizes = sizes or {}
    if not entries:
        return ["変更が1つも無い"]
    if len(entries) > MAX_FILES:
        errs.append(f"変更が {len(entries)} 件（上限 {MAX_FILES}）")
    added_images = 0
    for status, path in entries:
        st = status[:1]
        if st == "M" and path == MANIFEST:
            continue
        if st == "A":
            m = IMAGE_RE.match(path)
            if not m:
                errs.append(f"許可されていない追加: {path}")
                continue
            cat = m.group(1)
            if cat in FORBIDDEN_DIRS:
                errs.append(f"images/{cat}/ への追加は自動マージしない: {path}")
                continue
            if cat not in existing_categories:
                errs.append(f"新しいカテゴリ（コードの追加が要る）: {path}")
                continue
            if sizes.get(path, 0) > MAX_BYTES:
                errs.append(f"大きすぎる画像 {sizes[path] // 1024}KB: {path}")
                continue
            added_images += 1
            continue
        errs.append(f"許可されていない変更（{status}）: {path}")
    if added_images == 0 and not errs:
        errs.append("画像の追加が無い（manifest だけの変更は自動マージしない）")
    return errs


def _git(*args):
    return subprocess.check_output(["git", *args], text=True)


def main(argv):
    if len(argv) == 3 and argv[1] == "--files":
        entries = [tuple(l.split("\t", 1)) for l in open(argv[2], encoding="utf-8").read().splitlines() if l.strip()]
        cats = {"aroma", "facial", "shop"}
        errs = check(entries, cats)
    elif len(argv) == 2:
        base = argv[1]
        out = _git("diff", "--name-status", "--no-renames", f"{base}...HEAD")
        entries = [tuple(l.split("\t", 1)) for l in out.splitlines() if l.strip()]
        tree = _git("ls-tree", "-d", "--name-only", f"{base}:images").split()
        cats = {c for c in tree if c not in FORBIDDEN_DIRS}
        sizes = {p: os.path.getsize(p) for s, p in entries if s.startswith("A") and os.path.exists(p)}
        errs = check(entries, cats, sizes)
    else:
        print(__doc__)
        return 2

    for s, p in entries:
        print(f"  {s}\t{p}")
    if errs:
        print("自動マージしない（社長マージに回す）:")
        for e in errs:
            print("  - " + e)
        return 1
    print(f"自動マージ可: 画像 {sum(1 for s, _ in entries if s.startswith('A'))} 枚＋manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
