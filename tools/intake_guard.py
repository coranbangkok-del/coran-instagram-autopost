# -*- coding: utf-8 -*-
"""
写真取り込みPR（routine/photo-intake-*）を自動マージしてよいかの門番。

    python tools/intake_guard.py <base-ref> <head-sha>      # 例: origin/main 1a2b3c…
    python tools/intake_guard.py --files <status-file>      # 単体試験用（"A\\tpath" の行）

自動マージしてよいのは、変更が次だけのときに限る（それ以外が1つでもあれば「社長マージ」に回す）:
  - 追加（A）: images/<既存カテゴリ>/<ファイル名>.jpg|jpeg|png の通常ファイル（mode 100644）
               ※ images/generated/（投稿の生成物）は不可
               ※ シンボリックリンク（120000）・サブモジュール（160000）・実行ビット付きは不可
  - 変更（M）: images/manifest.json だけ（通常ファイルのまま。中身が build_manifest.py の出力と一致することは
               ワークフロー側で別に確かめる）
  - 削除・改名・既存画像の上書き・コード・ワークフロー・state/ の変更は不可
  - 「確認済み」の記録（seen.json）は team-takuro 側にあり、この repo の PR には出てこない

この門番がどこまで守れるか（正確に）:
  - ワークフローは pull_request_target（main 側のワークフロー定義）で動き、この門番も main から checkout した版を
    使う。PR のブランチにあるコードは一切実行しない（PR から取り出すのは、門番が通した画像と manifest だけ）。
    差分と中身は git のオブジェクト（diff --raw・cat-file）で読むので、PR の作業ツリーにも依存しない。
  - ただし repo に書き込める人は main へ直接 push もできる（ブランチ保護なし）。この門番は「写真取り込みの PR に
    意図しない変更が混ざったまま自動マージされる」のを防ぐもので、書き込み権を持つ人の悪意までは防がない。
終了コード: 0=自動マージ可 / 1=不可（理由を表示）/ 2=使い方の誤り
"""
import re
import subprocess
import sys

MAX_FILES = 80
MAX_BYTES = 6 * 1024 * 1024       # 取り込みは長辺2400px・品質88に縮小する手順＝通常 1〜2MB
IMAGE_RE = re.compile(r"^images/([a-z0-9-]+)/([A-Za-z0-9._-]+)\.(jpg|jpeg|png)$")
FORBIDDEN_DIRS = {"generated"}
MANIFEST = "images/manifest.json"
REGULAR = "100644"


def check(entries, existing_categories, sizes=None):
    """entries: [(status, path)] か [(status, path, new_mode)]。戻り値: 問題点のリスト（空＝自動マージ可）。"""
    errs = []
    sizes = sizes or {}
    if not entries:
        return ["変更が1つも無い"]
    if len(entries) > MAX_FILES:
        errs.append(f"変更が {len(entries)} 件（上限 {MAX_FILES}）")
    added_images = 0
    for ent in entries:
        status, path = ent[0], ent[1]
        mode = ent[2] if len(ent) > 2 else REGULAR
        st = status[:1]
        if mode != REGULAR:
            kind = {"120000": "シンボリックリンク", "160000": "サブモジュール", "100755": "実行ビット付き"}.get(mode, mode)
            errs.append(f"通常ファイルでない（{kind}）: {path}")
            continue
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


def parse_raw(out):
    """git diff --raw -z なしの出力を [(status, path, new_mode, new_sha)] に。"""
    rows = []
    for line in out.splitlines():
        if not line.startswith(":") or "\t" not in line:
            continue
        meta, path = line[1:].split("\t", 1)
        _old_mode, new_mode, _old_sha, new_sha, status = meta.split()[:5]
        rows.append((status, path, new_mode, new_sha))
    return rows


def _git(*args):
    return subprocess.check_output(["git", *args], text=True)


def main(argv):
    if len(argv) == 3 and argv[1] == "--files":
        entries = [tuple(l.split("\t")) for l in open(argv[2], encoding="utf-8").read().splitlines() if l.strip()]
        cats = {"aroma", "facial", "shop"}
        errs = check(entries, cats)
    elif len(argv) == 3:
        base, head = argv[1], argv[2]
        merge_base = _git("merge-base", base, head).strip()
        rows = parse_raw(_git("diff", "--raw", "--no-renames", "--abbrev=40", merge_base, head))
        entries = [(s, p, m) for s, p, m, _ in rows]
        tree = _git("ls-tree", "-d", "--name-only", f"{base}:images").split()
        cats = {c for c in tree if c not in FORBIDDEN_DIRS}
        sizes = {p: int(_git("cat-file", "-s", sha).strip())
                 for s, p, m, sha in rows if s.startswith("A") and m == REGULAR}
        errs = check(entries, cats, sizes)
    else:
        print(__doc__)
        return 2

    for e in entries:
        print("  " + "\t".join(e))
    if errs:
        print("自動マージしない（社長マージに回す）:")
        for e in errs:
            print("  - " + e)
        return 1
    print(f"自動マージ可: 画像 {sum(1 for e in entries if e[0].startswith('A'))} 枚＋manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
