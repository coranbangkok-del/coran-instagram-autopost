# -*- coding: utf-8 -*-
"""
写真取り込みPR（routine/photo-intake-*）自動マージの門番のセルフテスト。
ネットワーク・API・Secrets を使わない。git の試験は一時ディレクトリの使い捨て repo で行う（この repo を汚さない）。

    python tools/selftest_intake.py

見ているのは「自動マージしてはいけない PR を通さないこと」:
  - 画像の追加＋manifest だけ通す
  - コード・ワークフロー・generated・削除・上書き・新カテゴリ・深い階層・大きすぎる画像は通さない
  - シンボリックリンク・サブモジュール・実行ビット付きは通さない（gray r126）
  - ワークフローは pull_request_target・main のコードで検査し、PR のコードを実行しない（gray r126 条件4）
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import intake_guard  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail else ""))


# ---------------------------------------------------------------- 1. 判定
print("== 判定（check）")
cats = {"aroma", "facial", "shop"}
G = intake_guard.check
check("画像の追加＋manifest → 自動マージ可",
      G([("A", "images/facial/coran-spa-bangkok-facial-src-30.jpg"), ("M", "images/manifest.json")], cats) == [])
check("画像の追加だけ → 可", G([("A", "images/shop/coran-spa-bangkok-shop-src-01.jpg")], cats) == [])
check("mode 100644 を明示しても可", G([("A", "images/shop/a.jpg", "100644")], cats) == [])
for name, ent in [
    ("コードの変更", [("A", "images/facial/a.jpg"), ("M", "src/main.py")]),
    ("build_manifest.py の変更（aroma の追加）", [("A", "images/aroma/a.jpg"), ("M", "tools/build_manifest.py")]),
    ("門番自身の変更", [("A", "images/facial/a.jpg"), ("M", "tools/intake_guard.py")]),
    ("ワークフローの変更", [("A", "images/facial/a.jpg"), ("M", ".github/workflows/post.yml")]),
    ("ワークフローの追加", [("A", "images/facial/a.jpg"), ("A", ".github/workflows/x.yml")]),
    ("images/generated への追加", [("A", "images/generated/x.jpg")]),
    ("既存画像の上書き", [("M", "images/facial/old.png")]),
    ("画像の削除", [("D", "images/facial/old.png")]),
    ("state の変更", [("A", "images/facial/a.jpg"), ("M", "state/used.json")]),
    ("新しいカテゴリ", [("A", "images/newcat/a.jpg")]),
    ("画像以外の拡張子", [("A", "images/facial/a.svg")]),
    ("manifest だけ", [("M", "images/manifest.json")]),
    ("変更なし", []),
    ("深い階層", [("A", "images/facial/sub/a.jpg")]),
    ("パスに ..", [("A", "images/../src/a.jpg")]),
    ("シンボリックリンクの画像", [("A", "images/facial/a.jpg", "120000")]),
    ("シンボリックリンクの manifest", [("M", "images/manifest.json", "120000"), ("A", "images/facial/a.jpg")]),
    ("サブモジュール", [("A", "images/facial/a.jpg", "160000")]),
    ("実行ビット付き", [("A", "images/facial/a.jpg", "100755")]),
]:
    check(f"不可: {name}", bool(G(ent, cats)))
check("不可: 大きすぎる画像", bool(G([("A", "images/facial/a.jpg")], cats, {"images/facial/a.jpg": 7 * 1024 * 1024})))
check("不可: 件数が多すぎる", bool(G([("A", f"images/facial/a{i}.jpg") for i in range(81)], cats)))

raw = (":000000 100644 0000000000000000000000000000000000000000 1111111111111111111111111111111111111111 A\timages/facial/a.jpg\n"
       ":000000 120000 0000000000000000000000000000000000000000 2222222222222222222222222222222222222222 A\timages/facial/b.jpg\n")
rows = intake_guard.parse_raw(raw)
check("diff --raw を読める（mode と sha）",
      rows == [("A", "images/facial/a.jpg", "100644", "1" * 40), ("A", "images/facial/b.jpg", "120000", "2" * 40)], str(rows))

# ---------------------------------------------------------------- 2. 本物の git で（使い捨て repo）
print("== 本物の git で（一時 repo）")


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t",
                                    "-c", "commit.gpgsign=false", *args], text=True)


def run_guard(cwd, base, head):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "intake_guard.py"), base, head],
                       cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout


with tempfile.TemporaryDirectory(prefix="intake-") as d:
    git(d, "init", "-q", "-b", "main")
    os.makedirs(os.path.join(d, "images", "facial"))
    os.makedirs(os.path.join(d, "src"))
    open(os.path.join(d, "images", "facial", "old.png"), "wb").write(b"\x89PNG old")
    open(os.path.join(d, "images", "manifest.json"), "w").write("[]\n")
    open(os.path.join(d, "src", "main.py"), "w").write("print(1)\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "base")

    def branch(name, fn):
        git(d, "checkout", "-q", "-b", name, "main")
        fn()
        git(d, "add", "-A")
        git(d, "commit", "-qm", name)
        sha = git(d, "rev-parse", "HEAD").strip()
        git(d, "checkout", "-q", "main")
        return sha

    ok_sha = branch("routine/photo-intake-ok", lambda: (
        open(os.path.join(d, "images", "facial", "new-src-01.jpg"), "wb").write(b"\xff\xd8 new"),
        open(os.path.join(d, "images", "manifest.json"), "w").write('[{"file":"x"}]\n')))
    rc, out = run_guard(d, "main", ok_sha)
    check("git: 画像の追加＋manifest → 0（可）", rc == 0, out.strip().splitlines()[-1] if out else "")

    link_sha = branch("routine/photo-intake-link", lambda: os.symlink(
        "../../src/main.py", os.path.join(d, "images", "facial", "evil.jpg")))
    rc, out = run_guard(d, "main", link_sha)
    check("git: シンボリックリンクの .jpg → 1（不可）", rc == 1 and "シンボリックリンク" in out, out.strip().splitlines()[-1])

    code_sha = branch("routine/photo-intake-code", lambda: (
        open(os.path.join(d, "images", "facial", "new-src-02.jpg"), "wb").write(b"\xff\xd8 new"),
        open(os.path.join(d, "src", "main.py"), "a").write("print(2)\n")))
    rc, out = run_guard(d, "main", code_sha)
    check("git: コードの変更が混ざる → 1（不可）", rc == 1 and "src/main.py" in out, out.strip().splitlines()[-1])

    def _exec():
        p = os.path.join(d, "images", "facial", "run.jpg")
        open(p, "wb").write(b"\xff\xd8")
        os.chmod(p, 0o755)
    exec_sha = branch("routine/photo-intake-exec", _exec)
    rc, out = run_guard(d, "main", exec_sha)
    check("git: 実行ビット付き → 1（不可）", rc == 1, out.strip().splitlines()[-1])

    # main が先に進んでいても、PR 側の差分だけを見る（merge-base 起点）
    open(os.path.join(d, "src", "main.py"), "a").write("print('main moved')\n")
    git(d, "commit", "-qam", "main moved")
    rc, out = run_guard(d, "main", ok_sha)
    check("git: main が先に進んでも PR の差分だけを見る", rc == 0, out.strip().splitlines()[-1])

# ---------------------------------------------------------------- 3. ワークフローの形
print("== ワークフロー")
wf = open(os.path.join(ROOT, ".github", "workflows", "photo-intake-automerge.yml"), encoding="utf-8").read()
on_block = wf.split("\non:")[1].split("\njobs:")[0]
jobs = wf.split("\njobs:")[1]
check("pull_request_target で動く（定義は main の版）", "pull_request_target:" in on_block)
check("pull_request（PR 側の定義で動く）では動かさない", "\n  pull_request:" not in on_block)
check("fork の PR を除外する", "github.event.pull_request.head.repo.full_name == github.repository" in jobs)
check("対象は routine/photo-intake- だけ",
      "startsWith(github.head_ref, 'routine/photo-intake-')" in jobs and "startsWith(github.ref_name, 'routine/photo-intake-')" in jobs)
check("checkout は main（PR の head を checkout しない）",
      "ref: main" in jobs and "pull_request.head.sha }}\n" not in jobs.split("steps:")[1].split("run:")[0])
check("checkout の資格情報を残さない", "persist-credentials: false" in jobs)
check("門番は main から checkout した tools/intake_guard.py", 'python tools/intake_guard.py origin/main "$HEAD_SHA"' in jobs)
check("PR から取り出すのは追加・変更ファイルだけ（門番の後）",
      jobs.index("intake_guard.py origin/main") < jobs.index('xargs -0 -r git checkout "$HEAD_SHA" --'))
check("manifest は main の build_manifest.py の出力と一致", "python tools/build_manifest.py" in jobs and "diff -u" in jobs)
check("検査した commit だけをマージする", "--match-head-commit" in jobs)
check("GITHUB_TOKEN 以外のシークレットを使わない",
      [l for l in wf.splitlines() if "secrets." in l and "secrets.GITHUB_TOKEN" not in l] == [])
check("ブランチが先に進んでいたら何もしない", 'if [ "$got" != "$HEAD_SHA" ]' in jobs)

print()
print(f"== {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
