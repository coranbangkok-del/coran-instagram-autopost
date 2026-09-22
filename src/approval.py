# -*- coding: utf-8 -*-
"""
社長のスマホ承認（Claude の非公開 Artifact）→ 投稿、の検証部分。2026-09-22〜

流れ
  1. ルーティンが投稿日の24時間前に候補を作る（CORAN Frame の画像＋本文の下書き）。
     画像は ig-queue ブランチの queue/<slot>/image.jpg に置き、本文の下書きは
     非公開 Artifact の db にだけ置く（公開 repo に承認前の本文を置かない）。
  2. 社長が Artifact で本文を直して「承認」を押す。ページは社長の端末の中にある鍵
     （WebCrypto の ECDSA P-256・取り出し不可）で、画像のハッシュ・本文のハッシュ・枠・
     時刻に署名する。
  3. ルーティンが締切（投稿の2時間前）に db を読み、署名つきの承認を
     ig-queue の queue/<slot>/approval.json に置く。
  4. post.yml が承認を検証して、通ったときだけ投稿する。

「社長の端末の鍵で署名されたものしか通らない」ことを、ここで機械的に確かめる。
公開鍵は GitHub の repo の Actions 変数 IG_APPROVER_PUBKEYS から読む。repo に push できる
だけの人や AI は、承認記録を置けても署名は作れない。
ただし守れる範囲には限りがある（README「スマホ承認」の残る穴 a〜e）。とくに repo の Secret にある
GH_PAT（Secrets 書き込み権）はブランチに置いたワークフローからも使えるので、変数の差し替えや
post.yml 自体の書き換えを防ぐには、main の保護と Secret の環境移動（決裁）が要る。

どれか1つでも確かめられなければ投稿しない（fail-closed）。理由は文字列で返す。
"""
import base64
import datetime as _dt
import hashlib
import json
import re
import unicodedata

BKK = _dt.timezone(_dt.timedelta(hours=7))
PAYLOAD_HEADER = "CORAN-IG-APPROVAL/v1"

# 投稿枠（post.yml の cron と同じ）。曜日は Monday=0。
SLOTS = {(1, 19, 0), (4, 11, 0)}           # 火 19:00 / 金 11:00 BKK
CANDIDATE_LEAD = _dt.timedelta(hours=24)   # 候補を作るのは枠の24時間前
DEADLINE_LEAD = _dt.timedelta(hours=2)     # 承認の締切は枠の2時間前
EARLIEST_SIGN = _dt.timedelta(hours=48)    # 枠の48時間より前の署名は受けない（古い承認の使い回し防止）
# GitHub の cron は2〜5時間遅れる。枠から10時間を過ぎた実行では投稿しない。
POST_WINDOW = _dt.timedelta(hours=10)

IMAGE_SIZE = (1080, 1350)                  # CORAN Frame の出力（4:5）。これ以外は通さない
IG_CAPTION_MAX = 2200
IG_HASHTAG_MAX = 30

# 本文に入れてはいけない語（価格・割引・クーポン・販促）。gray r126 条件3 を反映。
#   誤検知はテンプレートの文言を変えて逃がす（パターンを緩めない）。
BANNED_PATTERNS = [
    r"฿", r"THB", r"baht", r"บาท", r"バーツ", r"円", r"\bUSD\b", r"\$", r"€", r"元", r"원",
    r"\d\s*[%％]", r"[%％]\s*off\b", r"percent",
    r"\bdiscounts?\b", r"\bcoupons?\b", r"\bpromo(?:tion)?s?\b", r"\bpromo\s*codes?\b",
    r"\bprices?\b", r"\bpricing\b", r"\bfree\b", r"\boffers?\b", r"\bsale\b", r"\bvouchers?\b",
    r"\b[A-Z]{3,}\d{2,}\b",                                   # クーポンコードの形（GREEN200 など）
    r"割引", r"割引き", r"クーポン", r"料金", r"価格", r"値引", r"セール", r"半額", r"無料", r"お得",
    r"折", r"優惠", r"优惠",
    r"ส่วนลด", r"คูปอง", r"ราคา", r"โปร", r"ลด", r"ฟรี",
    r"할인", r"쿠폰",
]
_BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)
_SLOT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ------------------------------------------------------------------ 小道具
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def caption_sha256(caption: str) -> str:
    """本文のハッシュ。ページと同じく UTF-8 のバイト列そのものに掛ける（正規化はページ側で済ませる）。"""
    return sha256_hex(caption.encode("utf-8"))


def normalize_caption(text: str) -> str:
    """ページが保存前にかける正規化と同じもの（NFC・改行を LF・前後の空白を落とす）。"""
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return t.strip()


def banned_words(text: str):
    """本文に含まれる禁止語の一覧（重複なし・出現順）。"""
    seen = []
    # 全角（ＴＨＢ・１５００）もすり抜けないよう NFKC にしてから照合する（署名する本文は NFC のまま）
    for m in _BANNED_RE.finditer(unicodedata.normalize("NFKC", text or "")):
        w = m.group(0)
        if w not in seen:
            seen.append(w)
    return seen


def slot_id(dt_bkk: _dt.datetime) -> str:
    return dt_bkk.astimezone(BKK).strftime("%Y%m%d-%H%M")


def parse_slot(sid: str):
    """'20260926-1100' → BKK の datetime。投稿枠（火19:00／金11:00）でなければ None。"""
    m = _SLOT_RE.match(sid or "")
    if not m:
        return None
    try:
        dt = _dt.datetime(*map(int, m.groups()), tzinfo=BKK)
    except ValueError:
        return None
    if (dt.weekday(), dt.hour, dt.minute) not in SLOTS:
        return None
    return dt


def deadline_of(slot_dt):
    return slot_dt - DEADLINE_LEAD


def next_slot(now=None):
    """now 以降で最初の投稿枠（BKK）。"""
    now = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(BKK)
    d = now.replace(second=0, microsecond=0)
    for i in range(0, 8):
        day = (d + _dt.timedelta(days=i)).date()
        for (wd, hh, mm) in sorted(SLOTS, key=lambda s: (s[1], s[2])):
            if day.weekday() != wd:
                continue
            cand = _dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=BKK)
            if cand >= d:
                return cand
    raise RuntimeError("投稿枠が見つかりません")


def open_slots(now=None):
    """いま投稿してよい枠（枠の時刻を過ぎ、POST_WINDOW 以内）。新しい順。"""
    now = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(BKK)
    out = []
    for i in range(0, 2):
        day = (now - _dt.timedelta(days=i)).date()
        for (wd, hh, mm) in SLOTS:
            if day.weekday() != wd:
                continue
            s = _dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=BKK)
            if s <= now <= s + POST_WINDOW:
                out.append(s)
    return sorted(out, reverse=True)


def parse_iso(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def meta_line(post_type, seq, photo_file, review_key):
    return f"{post_type}|{seq}|{photo_file}|{review_key or ''}"


def signing_payload(rec) -> str:
    """ページが署名する文字列。項目の順番・書き方はページ（ig-approval.html）と完全に同じにする。"""
    return "\n".join([
        PAYLOAD_HEADER,
        f"slot={rec['slot']}",
        f"decision={rec['decision']}",
        f"image_sha256={rec['image_sha256']}",
        f"caption_sha256={rec['caption_sha256']}",
        f"meta={meta_line(rec.get('post_type'), rec.get('seq'), rec.get('photo_file'), rec.get('review_key'))}",
        f"signed_at={rec['signed_at']}",
    ])


def _b64decode(s: str) -> bytes:
    s = (s or "").strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s, validate=True)


def key_fingerprint(spki_b64: str) -> str:
    return sha256_hex(_b64decode(spki_b64))[:16]


def parse_pubkeys(raw: str):
    """IG_APPROVER_PUBKEYS（SPKI の base64 を改行・カンマ・空白区切り）→ {指紋: spki_b64}。"""
    keys = {}
    for tok in re.split(r"[\s,]+", raw or ""):
        tok = tok.strip()
        if not tok:
            continue
        try:
            keys[key_fingerprint(tok)] = tok
        except Exception:
            continue   # 壊れた値は無視（全部壊れていれば鍵なし＝投稿しない）
    return keys


def verify_signature(spki_b64: str, payload: str, sig_b64: str) -> bool:
    """WebCrypto の ECDSA P-256/SHA-256 署名（r||s の64バイト）を確かめる。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        pub = serialization.load_der_public_key(_b64decode(spki_b64))
        if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
            return False
        raw = _b64decode(sig_b64)
        if len(raw) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        pub.verify(der, payload.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def _jpeg_size(data: bytes):
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "JPEG":
                return None
            return im.size
    except Exception:
        return None


# ------------------------------------------------------------------ 検証本体
REQUIRED = ("slot", "decision", "caption", "caption_sha256", "image_path", "image_sha256",
            "signed_at", "sig", "key_fp", "post_type", "seq", "photo_file")


def verify(rec, *, pubkeys, now, image_bytes, posted_slots=(), require_signature=True):
    """承認記録を検証する。戻り値 (ok: bool, reason: str)。

    rec          … queue/<slot>/approval.json の中身（dict）
    pubkeys      … parse_pubkeys() の結果。空なら投稿しない
    now          … 現在時刻（aware datetime）
    image_bytes  … rec['image_path'] の実ファイルのバイト列（無ければ None）
    posted_slots … 投稿済みの枠（state/posted_slots.json）
    require_signature … False はルーティンの事前確認用（鍵を持たない側）。CI では必ず True。
    """
    if not isinstance(rec, dict):
        return False, "承認記録が JSON オブジェクトではない"
    missing = [k for k in REQUIRED if k not in rec or rec[k] in (None, "")]
    if missing:
        return False, f"承認記録の項目が足りない: {missing}"
    for k in ("slot", "decision", "caption", "caption_sha256", "image_path", "image_sha256",
              "signed_at", "sig", "key_fp", "post_type", "photo_file"):
        if not isinstance(rec[k], str):
            return False, f"{k} が文字列ではない"
    if not isinstance(rec["seq"], int) or isinstance(rec["seq"], bool):
        return False, "seq が整数ではない"

    slot_dt = parse_slot(rec["slot"])
    if slot_dt is None:
        return False, f"投稿枠ではない: {rec['slot']}"
    if rec["decision"] != "approve":
        return False, f"承認ではない（decision={rec['decision']}）"
    if rec["slot"] in set(posted_slots or ()):
        return False, "この枠は投稿済み（二重投稿防止）"

    now_bkk = now.astimezone(BKK)
    if now_bkk < slot_dt:
        return False, "投稿枠の時刻より前"
    if now_bkk > slot_dt + POST_WINDOW:
        return False, "投稿枠から10時間を過ぎた（見送り）"

    signed = parse_iso(rec["signed_at"])
    if signed is None:
        return False, "signed_at が読めない"
    if signed > deadline_of(slot_dt):
        return False, "締切（枠の2時間前）より後の承認"
    if signed < slot_dt - EARLIEST_SIGN:
        return False, "枠の48時間より前の承認（古い承認の使い回し）"

    if rec["image_path"] != f"queue/{rec['slot']}/image.jpg":
        return False, "画像の置き場所が決まりと違う"
    if not (_HEX64.match(rec["image_sha256"]) and _HEX64.match(rec["caption_sha256"])):
        return False, "ハッシュの形が不正"
    if image_bytes is None:
        return False, "画像が見つからない"
    if sha256_hex(image_bytes) != rec["image_sha256"]:
        return False, "画像が承認されたものと違う（差し替え）"
    if _jpeg_size(image_bytes) != IMAGE_SIZE:
        return False, "画像が CORAN Frame の出力（1080x1350 の JPEG）ではない"

    cap = rec["caption"]
    if caption_sha256(cap) != rec["caption_sha256"]:
        return False, "本文が承認されたものと違う（改ざん）"
    if cap != normalize_caption(cap) or not cap:
        return False, "本文が空か、正規化されていない"
    if len(cap) > IG_CAPTION_MAX:
        return False, f"本文が {IG_CAPTION_MAX} 字を超える"
    if cap.count("#") > IG_HASHTAG_MAX:
        return False, f"ハッシュタグが {IG_HASHTAG_MAX} 個を超える"
    bad = banned_words(cap)
    if bad:
        return False, f"本文に価格・割引・販促の語: {bad}"

    if not require_signature:
        return True, "署名以外は OK（署名は CI で確かめる）"
    if not pubkeys:
        return False, "承認鍵（IG_APPROVER_PUBKEYS）が未登録"
    spki = pubkeys.get(rec["key_fp"])
    if not spki:
        return False, "登録されていない端末の鍵"
    if not verify_signature(spki, signing_payload(rec), rec["sig"]):
        return False, "署名が合わない（偽造・改ざん）"
    return True, "OK"


def build_record(doc, image_path):
    """Artifact db の posts/<slot> 文書 → queue/<slot>/approval.json の中身。

    ルーティンが使う。値の検証はしない（verify() が行う）。
    """
    return {
        "slot": doc.get("slot"),
        "decision": doc.get("decision"),
        "caption": doc.get("caption_final"),
        "caption_sha256": doc.get("caption_sha256"),
        "image_path": image_path,
        "image_sha256": doc.get("image_sha256"),
        "signed_at": doc.get("signed_at"),
        "sig": doc.get("sig"),
        "key_fp": doc.get("key_fp"),
        "post_type": doc.get("post_type"),
        "seq": doc.get("seq"),
        "photo_file": doc.get("photo_file"),
        "review_key": doc.get("review_key"),
    }


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
