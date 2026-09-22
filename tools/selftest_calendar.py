# -*- coding: utf-8 -*-
"""
月次カレンダー承認（S-2）と写真取り込み自動マージの門番のセルフテスト。
ネットワーク・API・Secrets を一切使わない。画像は一時ディレクトリに作る（repo を汚さない）。

    python tools/selftest_calendar.py

見ているのは「公開してはいけないときに公開しないこと」（fail-closed）:
  - 一致 → 公開する / 画像の中身が違う → しない / 本文が違う → しない / カレンダーが無い → しない
  - 今日が投稿日でない → しない（正常なお休み）/ 公開済み → 二度出さない
  - cron 遅延で日付をまたいだ前日分だけ救う（2日前は救わない）
  - 価格・割引の語、images/calendar/<月>/ の外を指すパス、火金以外の日付 → 検証で落ちる
  - 門番: 画像の追加＋manifest だけ通す。コード・カレンダー・generated・削除・新カテゴリは通さない
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("IG_USER_ID", "selftest")
os.environ.setdefault("IG_ACCESS_TOKEN", "selftest")
os.environ.setdefault("IMAGE_BASE_URL", "https://raw.githubusercontent.com/o/r/main/images")
os.environ.pop("ANTHROPIC_API_KEY", None)

import config          # noqa: E402
import ig_calendar as C  # noqa: E402
import brandimage      # noqa: E402
import caption_ai      # noqa: E402
import intake_guard    # noqa: E402

PASS, FAIL = [], []
BASE = "https://raw.githubusercontent.com/o/r/main/images"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail else ""))


man = json.load(open(config.MANIFEST_PATH, encoding="utf-8"))

# ---------------------------------------------------------------- 1. 日付
print("== 日付")
d10 = C.post_dates("2026-10")
check("2026-10 の投稿日は火・金だけ", all(d.weekday() in (1, 4) for d in d10), str([d.isoformat() for d in d10]))
check("2026-10 は 9 回（火4・金5）", len(d10) == 9)
check("翌月の計算（12月→翌年1月）", C.next_month(dt.date(2026, 12, 5)) == "2027-01")
check("前月の計算（1月→前年12月）", C.prev_month("2027-01") == "2026-12")
check("BKK の日付（UTC 17:30 は翌日）",
      C.today_bkk(dt.datetime(2026, 10, 6, 17, 30, tzinfo=dt.timezone.utc)) == dt.date(2026, 10, 7))
try:
    C.post_dates("2026-13")
    check("不正な月は例外", False)
except ValueError:
    check("不正な月は例外", True)

# ---------------------------------------------------------------- 2. 本文の規程
print("== 本文の規程（価格・割引を入れない）")
ok_text = "Slow down. Breathe.\n心も体も、ゆっくりと。\n\n📍 CORAN Boutique Spa — Sukhumvit Soi 15, Bangkok\nFeel free to DM us.\n\n#coranboutiquespa #bangkokspa"
check("通常の本文は通る", C.caption_problems(ok_text) == [])
for bad in ["Now 20% off!", "Only ฿1,500", "1500 THB", "Use coupon GREEN200", "割引あり",
            "クーポンをどうぞ", "料金はこちら", "ส่วนลดพิเศษ", "special discount", "1,500バーツ"]:
    check(f"弾く: {bad}", bool(C.caption_problems(ok_text + "\n" + bad)))
check("空の本文は弾く", bool(C.caption_problems("  ")))
check("2200字超は弾く", bool(C.caption_problems("a" * 2201)))
check("ハッシュタグ31個は弾く", bool(C.caption_problems(" ".join(f"#t{i}" for i in range(31)))))
for tmpl_text in [__import__("caption").build_service_caption(man[0]) for _ in range(20)]:
    if C.caption_problems(tmpl_text):
        check("テンプレ本文は規程に触れない", False, tmpl_text)
        break
else:
    check("テンプレ本文は規程に触れない（20回）", True)

# ---------------------------------------------------------------- 3. 生成（一時ディレクトリ）
print("== 生成")
tmp = tempfile.mkdtemp(prefix="igcal-")
try:
    root = tmp
    images = os.path.join(tmp, "images")
    # 素材は repo のものを読む（render は config.IMAGES_DIR から読む）ので、出力先だけ一時にする
    os.makedirs(images)

    plan = C.plan_month("2026-10", man, 3, [], [], [], cycle=["service", "sanctuary", "service", "review"])
    check("割り付けは巡回どおり（声が無ければ review→sanctuary）",
          [p["post_type"] for p in plan] ==
          ["service", "sanctuary", "service", "sanctuary", "service", "sanctuary", "service", "sanctuary", "service"],
          str([p["post_type"] for p in plan]))
    check("同じ月で写真が重ならない", len({p["photo"]["file"] for p in plan}) == len(plan))
    plan2 = C.plan_month("2026-10", man, 3, [], [], [], cycle=["service", "sanctuary", "service", "review"])
    check("割り付けは再現する（同じ月なら同じ）", [p["photo"]["file"] for p in plan] == [p["photo"]["file"] for p in plan2])
    used_all_but = [e["file"] for e in man][:-3]
    plan3 = C.plan_month("2026-10", man, 3, used_all_but, [], [])
    check("この巡で使った写真は避ける", all(p["photo"]["file"] not in used_all_but for p in plan3[:3]))
    rv = [{"text": "Wonderful and calm, the therapist was very attentive and kind to me.", "rating": 5}]
    plan4 = C.plan_month("2026-10", man, 3, [], rv, [])
    check("声があれば review の回は review のまま（1回だけ使う）",
          [p["post_type"] for p in plan4].count("review") == 1)

    def bad_caption(kind, photo, review):
        return "Relax with us. 30% off this week only!\n#coranboutiquespa"

    cal, notes = C.build_calendar(
        "2026-10", root, images, man, 3, [], [], [],
        caption_fn=bad_caption, headline_fn=caption_ai.build_image_headline,
        render_fn=brandimage.render, now=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))
    check("価格入りの AI 本文はテンプレに差し替わる", len(notes) == 9 and all(not C.caption_problems(p["caption"]) for p in cal["posts"]),
          f"notes={len(notes)}")
    errs = C.validate_calendar(cal, "2026-10", images)
    check("作ったカレンダーは検証を通る", errs == [], str(errs[:3]))
    check("画像は images/calendar/2026-10/ に9枚",
          len([f for f in os.listdir(os.path.join(images, "calendar", "2026-10")) if f.endswith(".jpg")]) == 9)
    from PIL import Image
    first = os.path.join(images, cal["posts"][0]["image_path"])
    check("画像は 1080x1350", Image.open(first).size == (1080, 1350))
    C.write_calendar(root, cal)
    md, prev = C.write_preview(root, images, cal)
    check("一覧（md）と縮小一覧（jpg）が出る", os.path.exists(md) and os.path.exists(prev))
    check("state/ に書いていない（生成は副作用なし）", not os.path.exists(os.path.join(root, "state")))

    # ------------------------------------------------------------ 4. 公開時の判定
    print("== 公開時の判定（fail-closed）")
    tue = dt.date.fromisoformat(cal["posts"][0]["date"])     # 2026-10-02 は金… 先頭の日
    e, m, why = C.resolve_post(root, images, tue, [])
    check("一致 → 公開する", e is not None and e["id"] == tue.isoformat() and why == "ok", why)
    cand = C.candidate_from_entry(e, BASE)
    ok, why2 = C.verify_candidate(cand, e, m, images, BASE)
    check("候補の最終照合も通る", ok, why2)
    check("画像URLは IMAGE_BASE_URL/calendar/2026-10/…", cand["image_url"].startswith(BASE + "/calendar/2026-10/"))

    # 候補の本文をすり替え → 公開しない
    c2 = dict(cand, caption=cand["caption"] + " extra")
    check("本文がカレンダーと違う → 公開しない", not C.verify_candidate(c2, e, m, images, BASE)[0])
    c3 = dict(cand, image_url=BASE + "/generated/other.jpg")
    check("画像URLがカレンダーと違う → 公開しない", not C.verify_candidate(c3, e, m, images, BASE)[0])

    # 公開済み → 二度出さない
    e2, _, why = C.resolve_post(root, images, tue, [tue.isoformat()])
    check("公開済み → 公開しない", e2 is None and why.startswith("already-published"), why)

    # 投稿日でない日 → 正常なお休み
    wed_like = tue + dt.timedelta(days=2)
    while wed_like.isoformat() in {p["date"] for p in cal["posts"]} or \
            (wed_like - dt.timedelta(days=1)).isoformat() in {p["date"] for p in cal["posts"]}:
        wed_like += dt.timedelta(days=1)
    e3, _, why = C.resolve_post(root, images, wed_like, [])
    check("投稿日でも翌日でもない日 → 公開しない（no-post-today）", e3 is None and why == "no-post-today", f"{wed_like} {why}")

    # cron 遅延: 前日の未公開分は救う／2日前は救わない
    e4, _, why = C.resolve_post(root, images, tue + dt.timedelta(days=1), [])
    check("前日の未公開分（cron 遅延）→ 公開する", e4 is not None and e4["id"] == tue.isoformat() and why.startswith("ok-grace"), why)
    e5, _, why = C.resolve_post(root, images, tue + dt.timedelta(days=1), [tue.isoformat()])
    check("前日分が公開済みなら翌日は何もしない", e5 is None, why)
    # 2日前の分は救わない（火→木）
    d_fri = [dt.date.fromisoformat(p["date"]) for p in cal["posts"] if dt.date.fromisoformat(p["date"]).weekday() == 1][0]
    e6, _, why = C.resolve_post(root, images, d_fri + dt.timedelta(days=2), [])
    check("2日前の未公開分は救わない", e6 is None, why)

    # 画像を差し替え → 公開しない（その月まるごと止まる）
    target = os.path.join(images, e["image_path"])
    backup = target + ".bak"
    shutil.copy(target, backup)
    with open(target, "ab") as fh:
        fh.write(b"tamper")
    e7, _, why = C.resolve_post(root, images, tue, [])
    check("画像の中身が記録と違う → 公開しない", e7 is None and why.startswith("invalid-calendar"), why[:80])
    check("最終照合でも画像の差し替えを弾く", not C.verify_candidate(cand, e, m, images, BASE)[0])
    shutil.move(backup, target)

    # 本文に価格を足したカレンダー（PR で手直しした想定）→ 公開しない
    cal_bad = json.loads(json.dumps(cal))
    cal_bad["posts"][0]["caption"] += "\nNow 20% off"
    C.write_calendar(root, cal_bad)
    e8, _, why = C.resolve_post(root, images, tue, [])
    check("本文に割引の語 → 公開しない", e8 is None and why.startswith("invalid-calendar"), why[:80])

    # パスの逃げ道
    cal_bad = json.loads(json.dumps(cal))
    cal_bad["posts"][0]["image_path"] = "calendar/2026-10/../../generated/x.jpg"
    check("../ で外に出るパスは検証で落ちる", bool(C.validate_calendar(cal_bad, "2026-10", images)))
    cal_bad["posts"][0]["image_path"] = "generated/x.jpg"
    check("images/calendar/<月>/ 以外のパスは検証で落ちる", bool(C.validate_calendar(cal_bad, "2026-10", images)))
    # 火金以外の日付
    cal_bad = json.loads(json.dumps(cal))
    cal_bad["posts"][0]["date"] = cal_bad["posts"][0]["id"] = "2026-10-07"   # 水
    check("火金以外の日付は検証で落ちる", bool(C.validate_calendar(cal_bad, "2026-10", images)))
    cal_bad = json.loads(json.dumps(cal))
    cal_bad["month"] = "2026-11"
    check("month がファイル名と違えば落ちる", bool(C.validate_calendar(cal_bad, "2026-10", images)))

    # 1件消した（社長が PR で外した）→ その日は出さない・他の日は出る
    cal_skip = json.loads(json.dumps(cal))
    removed = cal_skip["posts"].pop(0)
    C.write_calendar(root, cal_skip)
    e9, _, why = C.resolve_post(root, images, dt.date.fromisoformat(removed["date"]), [])
    check("PR で外した日 → 公開しない", e9 is None, why)
    nxt = cal_skip["posts"][0]
    e10, _, why = C.resolve_post(root, images, dt.date.fromisoformat(nxt["date"]), [])
    check("残した日は公開する", e10 is not None and e10["id"] == nxt["id"], why)

    # カレンダーが無い → 公開しない
    os.remove(C.calendar_path(root, "2026-10"))
    e11, _, why = C.resolve_post(root, images, tue, [])
    check("カレンダーが無い → 公開しない（no-calendar）", e11 is None and why.startswith("no-calendar"), why)
    e12, _, why = C.resolve_post(root, images, dt.date(2026, 11, 3), [])
    check("翌月のカレンダーが無い → 公開しない", e12 is None and why.startswith("no-calendar"), why)
    # 壊れた JSON
    os.makedirs(os.path.join(root, "calendar"), exist_ok=True)
    with open(C.calendar_path(root, "2026-10"), "w") as fh:
        fh.write('{"version": 1, "month": "2026-10", "posts": "x"}')
    e13, _, why = C.resolve_post(root, images, tue, [])
    check("posts が壊れている → 公開しない（停止扱い）", e13 is None and why.startswith("invalid-calendar"), why)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- 5. main.py の配線
print("== main.py の配線")
src_main = open(os.path.join(ROOT, "src", "main.py"), encoding="utf-8").read()
check("publish-calendar は verify_candidate を通してから投稿する",
      src_main.index("verify_candidate(") < src_main.index("instagram.post_image(candidate[\"image_url\"], candidate[\"caption\"])\n    print(f\"[PUBLISH] 投稿成功 media_id={media_id} calendar_id"))
post_yml = open(os.path.join(ROOT, ".github", "workflows", "post.yml"), encoding="utf-8").read()
check("post.yml: 従来の prepare は CALENDAR_MODE が on 以外のときだけ", "if: vars.CALENDAR_MODE != 'on'" in post_yml)
check("post.yml: 従来の publish は production 承認のまま", "    environment: production\n" in post_yml)
check("post.yml: カレンダー経路は main だけ",
      "if: vars.CALENDAR_MODE == 'on' && github.ref == 'refs/heads/main'" in post_yml)

# ---------------------------------------------------------------- 6. 写真取り込みの門番
print("== 写真取り込み PR の門番")
cats = {"aroma", "facial", "shop"}
G = intake_guard.check
check("画像の追加＋manifest → 自動マージ可",
      G([("A", "images/facial/coran-spa-bangkok-facial-src-30.jpg"), ("M", "images/manifest.json")], cats) == [])
check("画像の追加だけ → 可", G([("A", "images/shop/coran-spa-bangkok-shop-src-01.jpg")], cats) == [])
for name, ent in [
    ("コードの変更", [("A", "images/facial/a.jpg"), ("M", "src/main.py")]),
    ("build_manifest.py の変更（aroma の追加）", [("A", "images/aroma/a.jpg"), ("M", "tools/build_manifest.py")]),
    ("ワークフローの変更", [("A", "images/facial/a.jpg"), ("M", ".github/workflows/post.yml")]),
    ("カレンダーの追加", [("A", "calendar/2026-10.json")]),
    ("images/calendar への追加", [("A", "images/calendar/2026-10/x.jpg")]),
    ("images/generated への追加", [("A", "images/generated/x.jpg")]),
    ("既存画像の上書き", [("M", "images/facial/old.png")]),
    ("画像の削除", [("D", "images/facial/old.png")]),
    ("state の変更", [("A", "images/facial/a.jpg"), ("M", "state/used.json")]),
    ("新しいカテゴリ", [("A", "images/newcat/a.jpg")]),
    ("画像以外の拡張子", [("A", "images/facial/a.svg")]),
    ("manifest だけ", [("M", "images/manifest.json")]),
    ("変更なし", []),
    ("深い階層", [("A", "images/facial/sub/a.jpg")]),
]:
    check(f"不可: {name}", bool(G(ent, cats)))
check("不可: 大きすぎる画像", bool(G([("A", "images/facial/a.jpg")], cats, {"images/facial/a.jpg": 7 * 1024 * 1024})))
wf = open(os.path.join(ROOT, ".github", "workflows", "photo-intake-automerge.yml"), encoding="utf-8").read()
check("自動マージは fork の PR を除外する", "github.event.pull_request.head.repo.full_name == github.repository" in wf)
check("自動マージは routine/photo-intake- だけ",
      "startsWith(github.head_ref, 'routine/photo-intake-')" in wf and "startsWith(github.ref_name, 'routine/photo-intake-')" in wf)
check("pull_request_target を使っていない", "pull_request_target:" not in wf.split("jobs:")[0].split("\non:")[1])
check("門番は main の版で実行する", "git show origin/main:tools/intake_guard.py" in wf)
check("検査した commit だけをマージする", "--match-head-commit" in wf)
check("カレンダー PR を自動マージする経路が無い", "ig-calendar" not in wf.split("jobs:")[1])

print()
print(f"== {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
