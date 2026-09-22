# -*- coding: utf-8 -*-
"""
IG 通常投稿の「月次カレンダー承認」（社長決定 2026-09-22・S-2）。

    月初に翌月分の calendar/YYYY-MM.json（日付・巡回型・素材・本文・画像）を作る
      → ブランチ routine/ig-calendar-YYYY-MM → PR
      → 社長が PR をマージ ＝ その月の投稿の包括承認
      → post.yml（CALENDAR_MODE=on のとき）は main にある当月カレンダーに載っている投稿だけを公開する

fail-closed の約束（どれか1つでも満たさなければ投稿しない）:
  - main に当月の calendar/YYYY-MM.json がある
  - 今日（BKK）の日付の投稿がある（cron 遅延で日付をまたいだときだけ、前日の未公開分を1日だけ許す）
  - その投稿がまだ公開済みでない（state/calendar_published.json）
  - 画像ファイルが images/calendar/YYYY-MM/ の下に実在し、sha256 がカレンダーの記録と一致する
  - 本文が空でなく、価格・割引・クーポンの語を含まず、IG の上限（2200字・#30個）に収まる

※ モジュール名を calendar にしない（標準ライブラリの calendar を隠してしまう）。
"""
import datetime as _dt
import hashlib
import json
import os
import random
import re

try:
    from zoneinfo import ZoneInfo
    BKK = ZoneInfo("Asia/Bangkok")
except Exception:  # pragma: no cover  zoneinfo が無い環境の保険（BKK は夏時間なし）
    BKK = _dt.timezone(_dt.timedelta(hours=7))

SCHEMA_VERSION = 1

# post.yml の cron（火 19:00 ICT・金 11:00 ICT）と揃える。月=0 … 日=6。
# ここを変えるときは post.yml の cron も同時に変える（カレンダーの日に cron が走らないと投稿されない）。
POST_WEEKDAYS = (1, 4)   # 火・金

# 通常ローテ（main.py の POST_CYCLE と同じ並び。main.py から渡す）
DEFAULT_CYCLE = ["service", "sanctuary", "service", "review"]

# cron は2〜5時間遅れる（火 19:00 の回が翌 0 時を越えうる）。前日の未公開分だけ救う。
GRACE_DAYS = 1

IG_CAPTION_MAX = 2200
IG_HASHTAG_MAX = 30

# 本文に入れてはいけない語（価格・割引・クーポン）。事実だけを書く方針（D2 規程）。
#   誤検知を避けるため "off" "free" 単体は入れない（"Feel free to DM us" がテンプレにある）。
BANNED_PATTERNS = [
    r"฿", r"\bTHB\b", r"\bbaht\b", r"บาท", r"バーツ", r"円", r"\$\s?\d",
    r"\d\s*%", r"%\s*off\b", r"\bdiscounts?\b", r"\bcoupons?\b", r"\bpromo\s*codes?\b",
    r"\bprices?\b", r"\bpricing\b", r"割引", r"割引き", r"クーポン", r"料金", r"価格", r"値引",
    r"ส่วนลด", r"คูปอง", r"ราคา",
]
_BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ 小道具
def today_bkk(now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return now.astimezone(BKK).date()


def next_month(d):
    y, m = (d.year + (d.month // 12), d.month % 12 + 1)
    return f"{y:04d}-{m:02d}"


def month_of(d):
    return f"{d.year:04d}-{d.month:02d}"


def prev_month(month):
    y, m = map(int, month.split("-"))
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def post_dates(month):
    """その月の投稿日（POST_WEEKDAYS）を昇順で返す。"""
    if not _MONTH_RE.match(month or ""):
        raise ValueError(f"月の形式が不正です: {month!r}（YYYY-MM）")
    y, m = map(int, month.split("-"))
    d = _dt.date(y, m, 1)
    out = []
    while d.month == m:
        if d.weekday() in POST_WEEKDAYS:
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def calendar_path(root, month):
    return os.path.join(root, "calendar", f"{month}.json")


def load_calendar(root, month):
    p = calendar_path(root, month)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        # 壊れた JSON は「承認済みカレンダーあり・ただし不正」として扱う（validate で必ず落ちる＝公開しない）
        return {"version": None, "month": None, "posts": None}


def caption_problems(text):
    """本文の問題点を列挙する（空リスト＝OK）。"""
    probs = []
    if not isinstance(text, str) or not text.strip():
        return ["本文が空"]
    if len(text) > IG_CAPTION_MAX:
        probs.append(f"本文が {len(text)} 字（上限 {IG_CAPTION_MAX}）")
    tags = re.findall(r"(?<!\w)#\w", text)
    if len(tags) > IG_HASHTAG_MAX:
        probs.append(f"ハッシュタグ {len(tags)} 個（上限 {IG_HASHTAG_MAX}）")
    m = _BANNED_RE.search(text)
    if m:
        probs.append(f"価格・割引の語を含む: {m.group(0)!r}")
    return probs


def _safe_image_path(images_dir, month, rel):
    """images/calendar/<month>/ の外を指していないか（../ 等）を確かめ、絶対パスを返す。"""
    if not isinstance(rel, str) or not rel.startswith(f"calendar/{month}/"):
        return None
    base = os.path.realpath(os.path.join(images_dir, "calendar", month))
    full = os.path.realpath(os.path.join(images_dir, rel))
    if not full.startswith(base + os.sep):
        return None
    return full


# ------------------------------------------------------------------ 検証
def validate_calendar(cal, month, images_dir, check_files=True):
    """カレンダー全体を検証し、問題点のリストを返す（空＝OK）。PR 作成前と公開時の両方で使う。"""
    errs = []
    if not isinstance(cal, dict):
        return ["カレンダーが JSON オブジェクトでない"]
    if cal.get("version") != SCHEMA_VERSION:
        errs.append(f"version が {SCHEMA_VERSION} でない: {cal.get('version')!r}")
    if cal.get("month") != month:
        errs.append(f"month がファイル名と違う: {cal.get('month')!r} != {month!r}")
    posts = cal.get("posts")
    if not isinstance(posts, list):
        return errs + ["posts が配列でない"]
    allowed = {d.isoformat() for d in post_dates(month)}
    seen = set()
    for i, p in enumerate(posts):
        tag = f"posts[{i}]"
        if not isinstance(p, dict):
            errs.append(f"{tag} がオブジェクトでない")
            continue
        date = p.get("date")
        if not (isinstance(date, str) and _DATE_RE.match(date)):
            errs.append(f"{tag} date の形式が不正: {date!r}")
            continue
        if date not in allowed:
            errs.append(f"{tag} {date} は投稿日（火・金）でないか、{month} の外")
        if date in seen:
            errs.append(f"{tag} {date} が重複")
        seen.add(date)
        if p.get("id") != date:
            errs.append(f"{tag} id は date と同じにする: {p.get('id')!r}")
        for probs in caption_problems(p.get("caption")):
            errs.append(f"{tag} {date} {probs}")
        full = _safe_image_path(images_dir, month, p.get("image_path"))
        if not full:
            errs.append(f"{tag} {date} image_path が images/calendar/{month}/ の下でない: {p.get('image_path')!r}")
        elif check_files:
            if not os.path.exists(full):
                errs.append(f"{tag} {date} 画像が無い: {p.get('image_path')}")
            elif sha256_file(full) != p.get("image_sha256"):
                errs.append(f"{tag} {date} 画像の sha256 がカレンダーの記録と違う")
    return errs


# ------------------------------------------------------------------ 公開時の判定（純粋関数）
def resolve_post(root, images_dir, today, published_ids):
    """今日公開してよい投稿を決める。

    戻り値: (entry, month, reason)
      entry が None なら公開しない。reason は理由（実行サマリに出す）。
      reason が "no-post-today" のときだけ「正常なお休み」、それ以外は fail-closed の停止。
    """
    published = set(published_ids or [])
    candidates = [today - _dt.timedelta(days=k) for k in range(0, GRACE_DAYS + 1)]
    loaded = {}
    for d in candidates:
        month = month_of(d)
        if month not in loaded:
            loaded[month] = load_calendar(root, month)
    if loaded.get(month_of(today)) is None:
        return None, month_of(today), f"no-calendar: calendar/{month_of(today)}.json が main に無い（承認済みカレンダーなし）"
    # 当月のカレンダーは、今日が投稿日かどうかに関わらず丸ごと検証する（壊れていれば気づけるよう停止扱い）
    errs_today = validate_calendar(loaded[month_of(today)], month_of(today), images_dir, check_files=True)
    if errs_today:
        return None, month_of(today), "invalid-calendar: " + " / ".join(errs_today[:5])

    for d in candidates:
        month = month_of(d)
        cal = loaded.get(month)
        if cal is None:
            continue
        errs = validate_calendar(cal, month, images_dir, check_files=True)
        entry = next((p for p in cal.get("posts", []) if isinstance(p, dict) and p.get("date") == d.isoformat()), None)
        if entry is None:
            continue
        if entry.get("id") in published:
            if d == today:
                return None, month, f"already-published: {d.isoformat()} は公開済み"
            continue
        if errs:
            return None, month, "invalid-calendar: " + " / ".join(errs[:5])
        return entry, month, "ok" if d == today else f"ok-grace: 前日 {d.isoformat()} の未公開分（cron 遅延）"
    return None, month_of(today), "no-post-today"


def candidate_from_entry(entry, image_base_url):
    """公開に使う候補（main.publish と同じ形）をカレンダーの1件から作る。"""
    return {
        "post_type": entry["post_type"],
        "seq": entry.get("seq", 0),
        "photo_file": entry["photo_file"],
        "generated_file": entry["image_path"],
        "layout": entry.get("layout"),
        "image_url": f"{image_base_url.rstrip('/')}/{entry['image_path']}",
        "caption": entry["caption"],
        "review_key": entry.get("review_key"),
        "calendar_id": entry["id"],
    }


def verify_candidate(candidate, entry, month, images_dir, image_base_url):
    """公開直前の最終照合。候補がカレンダーの1件と完全に一致するときだけ True。"""
    if not candidate or not entry:
        return False, "候補かカレンダーの1件が無い"
    if candidate.get("caption") != entry.get("caption"):
        return False, "本文がカレンダーと一致しない"
    if candidate.get("calendar_id") != entry.get("id"):
        return False, "カレンダーの id が一致しない"
    want_url = f"{image_base_url.rstrip('/')}/{entry.get('image_path')}"
    if candidate.get("image_url") != want_url:
        return False, "画像URLがカレンダーと一致しない"
    full = _safe_image_path(images_dir, month, entry.get("image_path"))
    if not full or not os.path.exists(full):
        return False, "画像ファイルが無い"
    if sha256_file(full) != entry.get("image_sha256"):
        return False, "画像の中身がカレンダーの記録と一致しない"
    probs = caption_problems(candidate.get("caption"))
    if probs:
        return False, " / ".join(probs)
    return True, "ok"


# ------------------------------------------------------------------ 生成
def _pick(manifest, used, preferred_tags, rng):
    available = [p for p in manifest if p["file"] not in used]
    if not available:
        used.clear()
        available = list(manifest)
    pool = available
    if preferred_tags:
        tagged = [p for p in available if set(p.get("tags", [])) & set(preferred_tags)]
        if tagged:
            pool = tagged
    photo = rng.choice(pool)
    used.add(photo["file"])
    return photo


PREFER = {   # main.prepare と同じ条件（sanctuary に ambience を入れない）
    "review":    ["interior"],
    "sanctuary": ["sanctuary"],
    "service":   ["service", "treatment", "ambience"],
}


def plan_month(month, manifest, start_seq, used_cycle, reviews, used_review_keys,
               cycle=None, seed=None):
    """画像・本文を作る前の「割り付け」だけを決める（決定的・副作用なし）。"""
    cycle = cycle or DEFAULT_CYCLE
    rng = random.Random(seed if seed is not None else f"coran-ig-{month}")
    used = set(used_cycle or [])
    used_reviews = set(used_review_keys or [])
    seq = int(start_seq)
    plan = []
    for d in post_dates(month):
        seq = (seq + 1) % len(cycle)
        post_type = cycle[seq]
        review = None
        if post_type == "review":
            review = next((r for r in (reviews or []) if r["text"][:60] not in used_reviews), None)
            if review:
                used_reviews.add(review["text"][:60])
            else:
                post_type = "sanctuary"   # 引用できる声が無いときは実店舗の回へ（main.prepare と同じ）
        photo = _pick(manifest, used, PREFER[post_type], rng)
        plan.append({"date": d, "seq": seq, "post_type": post_type, "photo": photo, "review": review})
    return plan


def build_calendar(month, root, images_dir, manifest, start_seq, used_cycle,
                   reviews, used_review_keys, caption_fn, headline_fn, render_fn,
                   cycle=None, seed=None, now=None):
    """カレンダー（JSON 用 dict）と画像を作る。state/ には一切書かない。

    caption_fn(kind, photo, review) -> str
    headline_fn(kind, photo, review, eyebrow) -> (en, ja) | None
    render_fn(post_type, photo, review, headline) -> (PIL.Image, layout)
    """
    import brandimage

    out_dir = os.path.join(images_dir, "calendar", month)
    os.makedirs(out_dir, exist_ok=True)
    posts, notes = [], []
    for item in plan_month(month, manifest, start_seq, used_cycle, reviews, used_review_keys,
                           cycle=cycle, seed=seed):
        d, photo, review, post_type = item["date"], item["photo"], item["review"], item["post_type"]
        kind = "review" if post_type == "review" else "service"

        text = caption_fn(kind, photo, review)
        probs = caption_problems(text)
        if probs:
            # AI の本文が規程に触れたらテンプレへ（テンプレは価格を含まない）
            import caption as tmpl
            notes.append(f"{d.isoformat()}: 本文を差し替え（{' / '.join(probs)}）")
            text = tmpl.build_review_caption(review) if (kind == "review" and review) else tmpl.build_service_caption(photo)

        eyebrow = brandimage.meta_for(photo)[0]
        headline = headline_fn(kind, photo, review, eyebrow)
        if headline and any(_BANNED_RE.search(h or "") for h in headline):
            notes.append(f"{d.isoformat()}: 見出しを既定文に差し替え（価格・割引の語）")
            headline = None

        img, layout = render_fn(post_type, photo, review, headline)
        slug = os.path.splitext(os.path.basename(photo["file"]))[0][:48]
        rel = f"calendar/{month}/{d.isoformat()}-{layout}-{slug}.jpg"
        full = os.path.join(images_dir, rel)
        img.save(full, quality=90, optimize=True, subsampling=1)

        posts.append({
            "id": d.isoformat(),
            "date": d.isoformat(),
            "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()],
            "post_type": post_type,
            "seq": item["seq"],
            "layout": layout,
            "photo_file": photo["file"],
            "image_path": rel,
            "image_sha256": sha256_file(full),
            "headline": list(headline) if headline else None,
            "caption": text,
            "review_key": (review["text"][:60] if review else None),
        })

    # 今回使わない古い画像（再生成の残り）を消す
    keep = {os.path.basename(p["image_path"]) for p in posts}
    for f in os.listdir(out_dir):
        if f.endswith(".jpg") and f not in keep:
            os.remove(os.path.join(out_dir, f))

    cal = {
        "version": SCHEMA_VERSION,
        "month": month,
        "generated_at": (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "approval": "この JSON を main にマージすることが、この月の IG 通常投稿の包括承認になる（社長決定 2026-09-22 S-2）。",
        "posts": posts,
    }
    return cal, notes


def write_calendar(root, cal):
    os.makedirs(os.path.join(root, "calendar"), exist_ok=True)
    p = calendar_path(root, cal["month"])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return p


def write_preview(root, images_dir, cal):
    """PR で見るための一覧（Markdown）と縮小一覧画像を calendar/ に出す。"""
    from PIL import Image, ImageDraw

    month = cal["month"]
    lines = [
        f"# IG 投稿カレンダー {month}",
        "",
        "この PR をマージすると、下の投稿がその日に**個別の承認なしで**公開されます"
        "（CALENDAR_MODE=on のとき）。載せたくない回は、その1件を JSON から消してからマージしてください。",
        "本文を直す場合は calendar/%s.json の caption を編集してください（価格・割引・クーポンの語は公開時に弾かれます）。" % month,
        "",
        f"![一覧]({month}-preview.jpg)",
        "",
    ]
    for p in cal["posts"]:
        lines += [
            f"## {p['date']}（{p['weekday']}）・{p['post_type']}・組み方 {p['layout']}",
            "",
            f"素材: `{p['photo_file']}`",
            "",
            f"![{p['date']}](../images/{p['image_path']})",
            "",
            "```",
            p["caption"],
            "```",
            "",
        ]
    md = os.path.join(root, "calendar", f"{month}.md")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # 縮小一覧（4列）
    tw, th, pad = 270, 338, 12
    n = max(1, len(cal["posts"]))
    cols = 4
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + 36 + pad) + pad), (250, 246, 240))
    dr = ImageDraw.Draw(sheet)
    for i, p in enumerate(cal["posts"]):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + 36 + pad)
        with Image.open(os.path.join(images_dir, p["image_path"])) as im:
            sheet.paste(im.convert("RGB").resize((tw, th)), (x, y))
        dr.text((x, y + th + 8), f"{p['date']} {p['weekday']} {p['post_type']}", fill=(79, 56, 52))
    prev = os.path.join(root, "calendar", f"{month}-preview.jpg")
    sheet.save(prev, quality=85, optimize=True)
    return md, prev
