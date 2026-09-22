# -*- coding: utf-8 -*-
"""
スマホ承認（Claude の非公開 Artifact）経路のセルフテスト。ネットワーク・Secrets・IG を一切使わない。

    python tools/selftest_approval.py

社長の端末の鍵（WebCrypto の ECDSA P-256）の代わりに、ここで作った鍵で同じ形の署名を作る。
IG への投稿はスタブ（呼ばれた回数と中身だけ記録）。requests は呼ばれたら落ちるようにしてある。
state/ の実ファイルには書かない（一時ディレクトリへ向ける）。

見ていること＝「投稿しない側に倒れるか」:
  承認の偽造／未登録の鍵／鍵の未設定／本文の改ざん／画像の差し替え／価格語／締切切れ／
  枠の時刻外／二重投稿／見送り／使い回し／CORAN Frame 以外の画像／壊れた記録
"""
import base64
import copy
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["IG_USER_ID"] = "selftest"
os.environ["IG_ACCESS_TOKEN"] = "selftest"
os.environ["IMAGE_BASE_URL"] = "https://raw.githubusercontent.com/o/r/main/images"
os.environ["GITHUB_REPOSITORY"] = "coranbangkok-del/coran-instagram-autopost"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("IG_APPROVER_PUBKEYS", None)
os.environ.pop("GITHUB_OUTPUT", None)
os.environ.pop("GITHUB_STEP_SUMMARY", None)

import requests  # noqa: E402


def _no_network(*a, **k):
    raise RuntimeError("selftest: ネットワーク呼び出しは禁止")


requests.post = requests.get = requests.request = _no_network

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature  # noqa: E402
from PIL import Image  # noqa: E402

import config    # noqa: E402
import approval  # noqa: E402
import caption   # noqa: E402
import main as M  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail else ""))


# ------------------------------------------------------------ 端末の鍵（WebCrypto と同じ形）
def new_device():
    priv = ec.generate_private_key(ec.SECP256R1())
    spki = priv.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, base64.b64encode(spki).decode()


def webcrypto_sign(priv, payload):
    der = priv.sign(payload.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def page_approve(doc, priv, spki, caption_text=None, decision="approve", signed_at=None):
    """ig-approval.html の「承認」と同じことをする（本文の正規化→ハッシュ→署名→db に書く値）。"""
    d = copy.deepcopy(doc)
    cap = approval.normalize_caption(caption_text if caption_text is not None else d["caption_draft"])
    d.update({
        "decision": decision,
        "caption_final": cap,
        "caption_sha256": approval.caption_sha256(cap),
        "signed_at": signed_at or (approval.parse_slot(d["slot"]) - dt.timedelta(hours=5))
        .astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "key_fp": approval.key_fingerprint(spki),
        "status": "approved" if decision == "approve" else "declined",
    })
    d["sig"] = webcrypto_sign(priv, approval.signing_payload(approval.build_record(d, d["image_path"])))
    return d


# ------------------------------------------------------------ 一時の作業場所
TMP = tempfile.mkdtemp(prefix="ig-approval-selftest-")
STATE = os.path.join(TMP, "state")
os.makedirs(STATE)
for fn in ("rotation.json", "used.json"):
    shutil.copy(os.path.join(config.STATE_DIR, fn), os.path.join(STATE, fn))
config.STATE_DIR = STATE
config.ROTATION_STATE_PATH = os.path.join(STATE, "rotation.json")
config.USED_STATE_PATH = os.path.join(STATE, "used.json")
config.POSTED_SLOTS_PATH = os.path.join(STATE, "posted_slots.json")
real_state_before = {fn: open(os.path.join(ROOT, "state", fn), "rb").read()
                     for fn in ("rotation.json", "used.json")}

SLOT = "20260929-1900"                     # 火 19:00
SLOT_DT = approval.parse_slot(SLOT)
AT_POST = SLOT_DT + dt.timedelta(hours=1)  # cron が1時間遅れて動いた想定

posts = []


def stub_post(url, cap):
    posts.append((url, cap))
    return f"media-{len(posts)}"


def fresh_queue(img_bytes, rec=None, slot=SLOT):
    q = tempfile.mkdtemp(prefix="q-", dir=TMP)
    os.makedirs(os.path.join(q, "queue", slot))
    open(os.path.join(q, "queue", slot, "image.jpg"), "wb").write(img_bytes)
    if rec is not None:
        with open(os.path.join(q, "queue", slot, "approval.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    return q


RECENT = []   # IG 側の直近の本文（スタブ）


def stub_recent(hours=48):
    if RECENT == ["__error__"]:
        raise RuntimeError("IG API 失敗の模擬")
    return list(RECENT)


def run_publish(q, now=AT_POST, pubkeys="", sha="a" * 40, dry=False):
    config.IG_APPROVER_PUBKEYS = pubkeys
    before = len(posts)
    r = M.publish_approved(q, sha, dry_run=dry, now=now, post_fn=stub_post, recent_fn=stub_recent)
    return r, len(posts) - before


# ============================================================ 1. 価格語の検査
print("== 本文の価格・割引・販促の語")
for w in ["฿1,500", "1500 THB", "1500THB", "baht", "20% off", "２０％", "10 percent", "discount",
          "coupon", "promo code", "promotion", "price", "free", "special offer", "sale", "voucher",
          "GREEN200", "USD 40", "$40", "€30", "300元", "8折", "優惠", "优惠", "セール", "半額", "無料",
          "お得", "割引", "クーポン", "料金", "価格", "โปรโมชั่น", "ลดราคา", "ฟรี", "할인", "쿠폰", "5만원",
          "ＴＨＢ１５００", "ｆｒｅｅ"]:
    if not approval.banned_words(f"Relax with us. {w} today."):
        check(f"禁止語を拾う: {w}", False)
        break
else:
    check("gray r126 条件3 の語と全角の書き方をすべて拾う（40語）", True)
ok_all = True
for en in caption.SERVICE_OPENERS:
    for ja in caption.SERVICE_OPENERS_JA:
        for cl in caption.SERVICE_CLOSERS:
            t = f"{en}\n{ja}\n\n📍 CORAN Boutique Spa — Sukhumvit Soi 15, Bangkok\n{cl}\n\n" + \
                " ".join(caption.CORE_TAGS + caption.ROTATING_TAGS)
            if approval.banned_words(t):
                ok_all = False
                bad_t = approval.banned_words(t)
check("テンプレートの全組み合わせが禁止語に掛からない（掛かると一度も投稿できない）", ok_all,
      "" if ok_all else str(bad_t))
for opener in caption.REVIEW_OPENERS:
    if approval.banned_words(opener):
        check("レビュー導入文が禁止語に掛からない", False, opener)
        break
else:
    check("レビュー導入文が禁止語に掛からない", True)

# ============================================================ 2. 投稿枠と締切
print("== 投稿枠と締切")
check("火 19:00 は投稿枠", approval.parse_slot("20260929-1900") is not None)
check("金 11:00 は投稿枠", approval.parse_slot("20261002-1100") is not None)
check("水 19:00 は投稿枠ではない", approval.parse_slot("20260930-1900") is None)
check("形の崩れた枠 id は None", approval.parse_slot("2026-09-29T19:00") is None)
check("締切は枠の2時間前", approval.deadline_of(SLOT_DT).hour == 17)
ns = approval.next_slot(dt.datetime(2026, 9, 27, 10, 0, tzinfo=approval.BKK))
check("日曜の次の枠は火 19:00", approval.slot_id(ns) == "20260929-1900", approval.slot_id(ns))
ns2 = approval.next_slot(dt.datetime(2026, 9, 29, 19, 1, tzinfo=approval.BKK))
check("火 19:01 の次の枠は金 11:00", approval.slot_id(ns2) == "20261002-1100", approval.slot_id(ns2))
check("枠の1時間後は投稿してよい", [approval.slot_id(s) for s in approval.open_slots(AT_POST)] == [SLOT])
check("枠の11時間後は投稿しない", approval.open_slots(SLOT_DT + dt.timedelta(hours=11)) == [])

# ============================================================ 3. 候補づくり（CORAN Frame 必須）
print("== 候補づくり")
out = os.path.join(TMP, "cand")
doc = M.make_candidate(SLOT, out, headline_en="Warm oil, quiet city.", headline_ja="静かな時間を。")
img_bytes = open(os.path.join(out, "image.jpg"), "rb").read()
with Image.open(io.BytesIO(img_bytes)) as im:
    check("候補の画像は 1080x1350 の JPEG（CORAN Frame）", im.size == (1080, 1350) and im.format == "JPEG")
check("画像のハッシュが文書に入る", doc["image_sha256"] == approval.sha256_hex(img_bytes))
chunks = sorted(os.listdir(os.path.join(out, "chunks")))
joined = "".join(json.load(open(os.path.join(out, "chunks", c)))["b64"] for c in chunks)
check("断片をつなぐと元の画像に戻る（ページが同じバイト列でハッシュを取れる）",
      base64.b64decode(joined) == img_bytes and len(chunks) == doc["image_chunks"])
check("断片は db の1文書 256KiB に収まる",
      all(os.path.getsize(os.path.join(out, "chunks", c)) < 250 * 1024 for c in chunks))
check("締切が文書に入る", doc["deadline"].startswith("2026-09-29T17:00"))
check("下書きに禁止語が無い", not approval.banned_words(doc["caption_draft"]))
check("候補づくりで state/ を書き換えない",
      json.load(open(config.ROTATION_STATE_PATH)) == json.loads(real_state_before["rotation.json"]))

bad_cap = os.path.join(TMP, "bad_caption.txt")
open(bad_cap, "w", encoding="utf-8").write("今だけ 20% OFF のご案内。")
try:
    M.make_candidate(SLOT, os.path.join(TMP, "cand_bad"), caption_file=bad_cap,
                     headline_en="x", headline_ja="y")
    check("価格語入りの本文では候補を作らない", False)
except SystemExit:
    check("価格語入りの本文では候補を作らない", True)

import brandimage  # noqa: E402
_orig_render = brandimage.render


def _broken(*a, **k):
    raise RuntimeError("描画失敗の模擬")


brandimage.render = _broken
try:
    M.make_candidate(SLOT, os.path.join(TMP, "cand_broken"), headline_en="x", headline_ja="y")
    check("CORAN Frame が作れなければ候補を作らない（素材そのままへ倒さない）", False)
except SystemExit:
    check("CORAN Frame が作れなければ候補を作らない（素材そのままへ倒さない）",
          not os.path.exists(os.path.join(TMP, "cand_broken", "image.jpg")))
finally:
    brandimage.render = _orig_render
check("BRAND_IMAGE=off の設定が無くなっている", not hasattr(config, "BRAND_IMAGE"))
src_main = open(os.path.join(ROOT, "src", "main.py"), encoding="utf-8").read()
import importlib  # noqa: E402
spot_out = []
_so = M._set_output
M._set_output = lambda k, v: spot_out.append((k, v))
config.SPOT_SNS = "on"
M.prepare_spot()
M._set_output = _so
check("スポット告知の旧経路（署名なし）は止まっている", spot_out == [("has_candidate", "false")])
check("main.py に素材そのままへ倒す分岐が無い",
      "BRAND_IMAGE" not in src_main and "素材をそのまま使います" not in src_main)

# ============================================================ 4. 承認 → 中継 → 投稿（正常）
print("== 正常系")
priv, spki = new_device()
priv2, spki2 = new_device()      # 登録されていない別の端末
approved = page_approve(doc, priv, spki,
                        caption_text=doc["caption_draft"] + "\n\n社長が一行足しました。\r\n")
check("本文の修正（改行 CRLF 混じり）も正規化されて署名される",
      "\r" not in approved["caption_final"] and approved["caption_final"].endswith("足しました。"))

q = fresh_queue(img_bytes)
config.IG_APPROVER_PUBKEYS = spki
path_doc = os.path.join(TMP, "doc.json")
json.dump(approved, open(path_doc, "w", encoding="utf-8"), ensure_ascii=False)
check("中継: 署名つき承認を approval.json にする", M.relay(path_doc, q) is True)
rec = json.load(open(os.path.join(q, "queue", SLOT, "approval.json"), encoding="utf-8"))
check("承認記録に本文の最終版が入る", rec["caption"] == approved["caption_final"])

r, n = run_publish(q, pubkeys=spki, dry=True)
check("dry-run は投稿しないで枠を返す", r == SLOT and n == 0)
r, n = run_publish(q, pubkeys=spki + "\n" + spki2)
check("検証に通れば1回だけ投稿する", r == SLOT and n == 1)
url, cap = posts[-1]
check("画像 URL は ig-queue の commit に固定（検証したバイト列＝IG が取るバイト列）",
      url == f"https://raw.githubusercontent.com/coranbangkok-del/coran-instagram-autopost/{'a'*40}/queue/{SLOT}/image.jpg",
      url)
check("投稿本文は社長が直した最終版", cap == approved["caption_final"])
check("投稿後に posted_slots に記録", json.load(open(config.POSTED_SLOTS_PATH)) == [SLOT])
check("投稿後に巡回位置が進む", json.load(open(config.ROTATION_STATE_PATH))["seq"] == doc["seq"])
r, n = run_publish(q, pubkeys=spki)
check("同じ枠をもう一度動かしても投稿しない（二重投稿防止）", r is None and n == 0)
os.remove(config.POSTED_SLOTS_PATH)

# ============================================================ 5. 投稿しない側に倒れるか
print("== fail-closed（どれも投稿 0 回であること）")


def expect_no_post(name, rec_obj, img=img_bytes, now=AT_POST, pubkeys=spki, sha="a" * 40, slot=SLOT):
    qq = fresh_queue(img, rec_obj, slot=slot)
    r_, n_ = run_publish(qq, now=now, pubkeys=pubkeys, sha=sha)
    check(name, r_ is None and n_ == 0, f"posted={n_}")


base = approval.build_record(approved, approved["image_path"])
expect_no_post("鍵（IG_APPROVER_PUBKEYS）が未設定", base, pubkeys="")
expect_no_post("鍵の値が壊れている", base, pubkeys="not-a-key!!")
expect_no_post("登録されていない端末の署名", approval.build_record(page_approve(doc, priv2, spki2), doc["image_path"]))
forged = dict(base, sig=base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip("="))
expect_no_post("署名の偽造（でたらめな64バイト）", forged)
fp_swap = dict(approval.build_record(page_approve(doc, priv2, spki2), doc["image_path"]),
               key_fp=approval.key_fingerprint(spki))
expect_no_post("未登録の鍵で署名して、登録済みの鍵の指紋を名乗る", fp_swap)
t1 = dict(base, caption=base["caption"] + " 追記")
expect_no_post("承認後に本文を書き換え（ハッシュそのまま）", t1)
t2 = dict(t1, caption_sha256=approval.caption_sha256(t1["caption"]))
expect_no_post("承認後に本文を書き換え（ハッシュも合わせる＝署名が合わない）", t2)
other = io.BytesIO()
Image.new("RGB", (1080, 1350), (10, 10, 10)).save(other, "JPEG", quality=90)
other = other.getvalue()
expect_no_post("画像の差し替え（ハッシュそのまま）", base, img=other)
expect_no_post("画像の差し替え（ハッシュも合わせる＝署名が合わない）",
               dict(base, image_sha256=approval.sha256_hex(other)), img=other)
expect_no_post("画像が無い", base, img=b"")
sq = io.BytesIO()
Image.new("RGB", (1080, 1080), (10, 10, 10)).save(sq, "JPEG")
sq_doc = dict(doc, image_sha256=approval.sha256_hex(sq.getvalue()))
expect_no_post("CORAN Frame 以外の画像（正しく署名されていても）",
               approval.build_record(page_approve(sq_doc, priv, spki), doc["image_path"]), img=sq.getvalue())
priced = approval.build_record(page_approve(doc, priv, spki, caption_text="今だけ 20% OFF。GREEN200 で。"),
                               doc["image_path"])
expect_no_post("本文に価格語（社長の署名があっても）", priced)
late = approval.build_record(page_approve(doc, priv, spki, signed_at=(SLOT_DT - dt.timedelta(minutes=90))
                                          .astimezone(dt.timezone.utc).isoformat()), doc["image_path"])
expect_no_post("締切（2時間前）より後の承認", late)
old = approval.build_record(page_approve(doc, priv, spki, signed_at=(SLOT_DT - dt.timedelta(hours=60))
                                         .astimezone(dt.timezone.utc).isoformat()), doc["image_path"])
expect_no_post("枠の48時間より前の承認（使い回し）", old)
expect_no_post("枠から10時間を過ぎた実行", base, now=SLOT_DT + dt.timedelta(hours=10, minutes=1))
expect_no_post("枠の時刻より前の実行", base, now=SLOT_DT - dt.timedelta(minutes=30))
declined = approval.build_record(page_approve(doc, priv, spki, decision="decline"), doc["image_path"])
expect_no_post("見送り（decision=decline）", declined)
prev = dict(doc, slot="20260922-1900", image_path="queue/20260922-1900/image.jpg")
prev_rec = approval.build_record(page_approve(prev, priv, spki), prev["image_path"])
expect_no_post("先週の枠の承認を今週の置き場所に置く（使い回し）", prev_rec)
wd = dict(doc, slot="20260930-1900", image_path="queue/20260930-1900/image.jpg")
expect_no_post("投稿枠でない日時の承認", approval.build_record(page_approve(wd, priv, spki, signed_at="2026-09-30T05:00:00Z"), wd["image_path"]),
               slot="20260930-1900", now=approval.parse_slot("20260929-1900") + dt.timedelta(days=1))
expect_no_post("承認記録の項目が足りない", {k: v for k, v in base.items() if k != "sig"})
expect_no_post("承認記録が配列", [base])
expect_no_post("seq が文字列", dict(base, seq="1"))
expect_no_post("画像の置き場所を別のパスにする", dict(base, image_path="../images/shop/x.jpg"))
expect_no_post("ig-queue の commit が特定できない", base, sha="")
expect_no_post("承認記録が無い", None)
qq = fresh_queue(img_bytes)
open(os.path.join(qq, "queue", SLOT, "approval.json"), "w").write("{not json")
r_, n_ = run_publish(qq, pubkeys=spki)
check("承認記録が壊れた JSON", r_ is None and n_ == 0)
json.dump([SLOT], open(config.POSTED_SLOTS_PATH, "w"))
expect_no_post("投稿済みの枠", base)
os.remove(config.POSTED_SLOTS_PATH)
RECENT[:] = [base["caption"]]
expect_no_post("state の記録が無くても、IG に同じ本文が直近にあれば出さない", base)
check("そのとき posted_slots に記録して次回も止める", json.load(open(config.POSTED_SLOTS_PATH)) == [SLOT])
os.remove(config.POSTED_SLOTS_PATH)
RECENT[:] = ["__error__"]
expect_no_post("IG の直近の投稿を確かめられないときは出さない", base)
RECENT[:] = []

# ============================================================ 6. 中継（ルーティン側）で止まるか
print("== 中継で止まるか（ルーティンは承認でないものを repo に書かない）")


def relay_refuses(name, d, pubkeys=spki):
    qq = fresh_queue(img_bytes)
    config.IG_APPROVER_PUBKEYS = pubkeys
    p = os.path.join(qq, "doc.json")
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    ok_ = M.relay(p, qq)
    check(name, ok_ is False and not os.path.exists(os.path.join(qq, "queue", SLOT, "approval.json")))


relay_refuses("未承認（pending）は書かない", doc)
relay_refuses("お試しの候補は承認されていても書かない", dict(approved, trial=True))
relay_refuses("見送りは書かない", page_approve(doc, priv, spki, decision="decline"))
relay_refuses("締切後の承認は書かない", page_approve(doc, priv, spki, signed_at=(SLOT_DT - dt.timedelta(hours=1))
                                                 .astimezone(dt.timezone.utc).isoformat()))
relay_refuses("価格語入りは書かない", page_approve(doc, priv, spki, caption_text="free drink"))
relay_refuses("署名の合わない承認は書かない（鍵を知っている場合）", dict(approved, caption_final=approved["caption_final"] + "x",
                                                        caption_sha256=approval.caption_sha256(approved["caption_final"] + "x")))

# ============================================================ 7. ページと署名の形が一致するか
print("== 確認ページとの取り決め")
page = os.path.join(ROOT, "approval-page", "ig-approval.html")
if os.path.exists(page):
    html = open(page, encoding="utf-8").read()
    check("ページの署名見出しが同じ", approval.PAYLOAD_HEADER in html)
    order = re.findall(r"`(slot|decision|image_sha256|caption_sha256|meta|signed_at)=", html)
    check("ページの署名項目の順番が同じ",
          order == ["slot", "decision", "image_sha256", "caption_sha256", "meta", "signed_at"], str(order))
    check("ページは ECDSA P-256 / SHA-256・取り出し不可の鍵で署名する",
          "P-256" in html and "SHA-256" in html and "false /* 取り出し不可 */" in html)
    check("ページは NFC 正規化してからハッシュを取る", "normalize(\"NFC\")" in html or "normalize('NFC')" in html)
    m = re.search(r"const BANNED = (\[.*?\]);", html)
    check("ページの価格語リストが src/approval.py と同じ",
          bool(m) and json.loads(m.group(1)) == approval.BANNED_PATTERNS)
else:
    check("確認ページのファイルがある", False, page)

check("実 state/ を書き換えていない",
      all(open(os.path.join(ROOT, "state", fn), "rb").read() == b for fn, b in real_state_before.items()))
check("IG へのスタブ呼び出しは正常系の1回だけ", len(posts) == 1, str(len(posts)))

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"== {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
