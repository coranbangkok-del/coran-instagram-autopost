# -*- coding: utf-8 -*-
"""
CORAN Frame — SNS画像のブランド化エンジン。

素材写真（ほとんどが 1366x768 の 16:9）を、Instagram で最も大きく表示される
4:5（1080x1350）の「CORAN の画」へ変換する。

【設計の芯】
- 比率   : 4:5 固定。16:9 のままだとフィード占有面積が約 1/1.8 になる
- トーン : CORAN のカラーグレードで統一。出典がバラバラでも一本の作品に見せる
- リズム : A(写真) / B(クリーム地) / C(深ブラウン地) を巡回し、3列グリッドで明暗を市松に
- 出典   : coran-bangkok の globals.css（Gold/Brown/Cream/Sage + Playfair + Noto Sans JP）

外部APIは使わない（Pillow + numpy のみ・追加費用ゼロ）。
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import config

W, H = 1080, 1350
M = 84

# --- brand tokens（coran-bangkok/src/app/globals.css と同じ値） ---
GOLD = (201, 169, 110)        # #C9A96E
GOLD_LIGHT = (232, 213, 168)  # #E8D5A8
BROWN = (79, 56, 52)          # #4F3834
BROWN_DARK = (46, 32, 30)
CREAM = (250, 246, 240)       # #FAF6F0

# 切り出したあとの幅がこれ未満なら、A(全面)ではなく C(額装)へ逃がす
MIN_CROP_W = 560


# ---------------------------------------------------------------- fonts
_FONT_CACHE = {}


def font(name, size, weight=None):
    key = (name, size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    fname = {"pf": "PlayfairDisplay.ttf",
             "pfi": "PlayfairDisplay-Italic.ttf",
             "jp": "NotoSansJP.ttf"}[name]
    f = ImageFont.truetype(os.path.join(config.FONTS_DIR, fname), size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass  # 可変フォント非対応の環境では既定ウェイトで描く
    _FONT_CACHE[key] = f
    return f


def _tw(d, t, f, ls=0):
    if not ls:
        return d.textlength(t, font=f)
    return sum(d.textlength(c, font=f) for c in t) + ls * (len(t) - 1)


def _text_ls(d, xy, t, f, fill, ls=0, center=False):
    """字間（letter-spacing）付きで描く。Pillow に字間の概念が無いので1文字ずつ置く。"""
    x, y = xy
    if center:
        x = x - _tw(d, t, f, ls) / 2
    for c in t:
        d.text((x, y), c, font=f, fill=fill)
        x += d.textlength(c, font=f) + ls


def _wrap_en(d, t, f, maxw):
    lines, cur = [], ""
    for w_ in t.split():
        trial = (cur + " " + w_).strip()
        if d.textlength(trial, font=f) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def _wrap_jp(d, t, f, maxw):
    """日本語は単語区切りが無いので1文字ずつ詰める。行頭に来てはいけない約物だけ前行へ送る。"""
    NG_HEAD = "、。』」）,.!?！？ー"
    lines, cur = [], ""
    for c in t:
        if c == "\n":
            lines.append(cur)
            cur = ""
            continue
        if d.textlength(cur + c, font=f) <= maxw or (cur and c in NG_HEAD):
            cur += c
        else:
            lines.append(cur)
            cur = c
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- grade
def grade(im, strength=1.0):
    """ストック写真のバラバラな色を CORAN のトーンへ寄せる。

    彩度を少し落とす → ゆるいSカーブ → 影にブラウン・ハイライトにゴールド → 弱いヴィネット。
    """
    a = np.asarray(im.convert("RGB")).astype(np.float32) / 255.0
    lum = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)[..., None]
    a = lum + (a - lum) * (1 - 0.16 * strength)
    a = np.clip(a, 0, 1)
    a = a + (a * (1 - a)) * (a - 0.5) * 0.55 * strength
    sh = np.clip(1 - lum * 1.6, 0, 1)
    hi = np.clip((lum - 0.45) / 0.55, 0, 1)
    a += sh * (np.array(BROWN_DARK) / 255.0 - 0.18) * 0.30 * strength
    a += hi * (np.array(GOLD_LIGHT) / 255.0 - 0.88) * 0.45 * strength
    a = np.clip(a, 0, 1)
    out = (a * 255).astype(np.uint8)

    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    v = np.clip(1 - 0.20 * strength * np.clip(r - 0.55, 0, None) / 0.9, 0, 1)[..., None]
    return Image.fromarray((out.astype(np.float32) * v).clip(0, 255).astype(np.uint8))


# ---------------------------------------------------------------- crop
def crop_width_for(im, ratio=W / H):
    """この素材を ratio で切ったときに残る幅。小さすぎる素材を弾く判定に使う。"""
    iw, ih = im.size
    return int(ih * ratio) if iw / ih > ratio else iw


def smart_crop(im, ratio=W / H):
    """中央切りではなく「情報量が多いところ」を残して切る（顔や手が切れにくい）。"""
    im = im.convert("RGB")
    iw, ih = im.size
    if iw / ih > ratio:
        nw = int(ih * ratio)
        g = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES)).astype(np.float32)
        col = g.sum(axis=0)
        k = max(1, nw // 8)
        sm = np.convolve(col, np.ones(k) / k, mode="same")
        win = np.convolve(sm, np.ones(nw), mode="same")
        x = int(np.clip(int(np.argmax(win)) - nw // 2, 0, iw - nw))
        im = im.crop((x, 0, x + nw, ih))
    else:
        nh = int(iw / ratio)
        y = int((ih - nh) * 0.38)   # 人物は少し上寄せが自然
        im = im.crop((0, y, iw, y + nh))
    return im.resize((W, int(round(W / ratio))), Image.LANCZOS)


# ---------------------------------------------------------------- parts
_MARK = None


def _mark_alpha():
    global _MARK
    if _MARK is None:
        _MARK = Image.open(config.MARK_PATH).convert("RGBA").getchannel("A")
    return _MARK


def mark(size, color):
    a = _mark_alpha()
    a = a.resize((size, max(1, int(size * a.height / a.width))), Image.LANCZOS)
    layer = Image.new("RGBA", a.size, color + (0,))
    layer.putalpha(a)
    return layer


def lockup(canvas, d, cx, y, color, scale=1.0, sub="BOUTIQUE SPA  ·  BANGKOK"):
    m = mark(int(58 * scale), color)
    canvas.paste(m, (int(cx - m.width / 2), int(y)), m)
    _text_ls(d, (cx, y + m.height + 16), "CORAN", font("pf", int(34 * scale), 500),
             color, ls=int(9 * scale), center=True)
    if sub:
        _text_ls(d, (cx, y + m.height + 16 + int(46 * scale)), sub,
                 font("jp", int(15 * scale), 400), color, ls=int(4 * scale), center=True)


def stars(d, cx, cy, n=5, r=17, gap=46, fill=GOLD):
    """★はフォントに無いので多角形で描く（豆腐文字の回避）。"""
    total = (n - 1) * gap
    for i in range(n):
        x = cx - total / 2 + i * gap
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rr = r if k % 2 == 0 else r * 0.42
            pts.append((x + rr * math.cos(ang), cy + rr * math.sin(ang)))
        d.polygon(pts, fill=fill)


def arch_mask(w, h):
    """下は角・上は半円の「アーチ窓」。4倍で描いて縮小＝縁を滑らかに。"""
    m = Image.new("L", (w * 4, h * 4), 0)
    dm = ImageDraw.Draw(m)
    R = w * 4 // 2
    dm.pieslice([0, 0, w * 4, R * 2], 180, 360, fill=255)
    dm.rectangle([0, R, w * 4, h * 4], fill=255)
    return m.resize((w, h), Image.LANCZOS)


def scrim(base, top_frac, alpha_bottom, rgb=BROWN_DARK):
    g = Image.new("L", (1, H))
    px = g.load()
    y0 = int(H * top_frac)
    for y in range(H):
        t = 0 if y < y0 else (y - y0) / (H - y0)
        px[0, y] = int(alpha_bottom * 255 * (t ** 1.55))
    base.paste(Image.new("RGB", (W, H), rgb), (0, 0), g.resize((W, H)))
    return base


# ---------------------------------------------------------------- layouts
def layout_editorial(photo_path, eyebrow, en, ja):
    """A: 写真が主役。下部にスクリム＋ゴールドの小見出し＋Playfair＋和文。"""
    base = grade(smart_crop(Image.open(photo_path))).convert("RGB")
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)

    # 文字が乗る下部の明るさを実測し、必要なだけスクリムを濃くする（白飛び写真でも読める）
    lo = float(np.asarray(base.crop((0, int(H * 0.62), W, H)).convert("L")).mean()) / 255.0
    base = scrim(base, 0.30, float(np.clip(0.80 + (lo - 0.32) * 1.15, 0.80, 0.96)))
    d = ImageDraw.Draw(base)

    fe, fh, fj = font("jp", 21, 500), font("pf", 62, 500), font("jp", 27, 400)
    lines = _wrap_en(d, en, fh, W - 2 * M - 160)[:3]
    jl = _wrap_jp(d, ja, fj, W - 2 * M - 160)[:2]

    y = (H - 112) - len(jl) * 42 - 26 - len(lines) * 76 - 30 - 26 - 22
    _text_ls(d, (M, y), eyebrow.upper(), fe, GOLD_LIGHT, ls=7)
    y += 40
    d.line([(M, y), (M + 72, y)], fill=GOLD, width=2)
    y += 28
    for ln in lines:
        d.text((M, y), ln, font=fh, fill=CREAM)
        y += 76
    y += 8
    for ln in jl:
        d.text((M + 3, y), ln, font=fj, fill=(236, 228, 216))
        y += 42

    m = mark(46, CREAM)
    base.paste(m, (W - M - m.width, H - 112 - m.height + 10), m)
    fs = font("jp", 14, 400)
    _text_ls(d, (W - M - _tw(d, "SUKHUMVIT SOI 15", fs, 3), H - 96),
             "SUKHUMVIT SOI 15", fs, (216, 205, 190), ls=3)
    return base


def layout_testimonial(photo_path, quote, ja, attrib):
    """B: クリーム地。グリッドで「明るい休符」になり、肌色の壁を断ち切る。"""
    base = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(base)

    aw, ah = W - 2 * M, 560
    ph = grade(smart_crop(Image.open(photo_path), aw / ah), 0.85).resize((aw, ah), Image.LANCZOS)
    base.paste(ph, (M, M + 8), arch_mask(aw, ah))

    fr = Image.new("RGBA", (aw + 24, ah + 24), (0, 0, 0, 0))
    dfr = ImageDraw.Draw(fr)
    R = (aw + 24) // 2
    dfr.pieslice([0, 0, aw + 24, R * 2], 180, 360, outline=GOLD, width=2)
    dfr.line([(0, R), (0, ah + 24)], fill=GOLD, width=2)
    dfr.line([(aw + 22, R), (aw + 22, ah + 24)], fill=GOLD, width=2)
    dfr.line([(0, ah + 22), (aw + 24, ah + 22)], fill=GOLD, width=2)
    base.paste(fr, (M - 12, M - 4), fr)

    y = M + 8 + ah + 72
    stars(d, W / 2, y + 14)
    y += 66

    fq = font("pfi", 45, 500)
    for ln in _wrap_en(d, '“' + quote + '”', fq, W - 2 * M - 80)[:4]:
        _text_ls(d, (W / 2, y), ln, fq, BROWN, center=True)
        y += 62
    y += 18
    fj = font("jp", 24, 400)
    for ln in _wrap_jp(d, ja, fj, W - 2 * M - 80)[:2]:
        _text_ls(d, (W / 2, y), ln, fj, (122, 98, 92), center=True)
        y += 38

    y = H - 236
    d.line([(W / 2 - 40, y), (W / 2 + 40, y)], fill=GOLD, width=1)
    _text_ls(d, (W / 2, y + 22), attrib.upper(), font("jp", 16, 400),
             (150, 128, 118), ls=4, center=True)
    lockup(base, d, W / 2, H - 150, BROWN, 0.82)
    return base


def layout_sanctuary(photo_path, eyebrow, en, ja):
    """C: 深ブラウン地。実店舗のワイド写真を切らずに額装する＝自社性と重心。"""
    base = Image.new("RGB", (W, H), BROWN_DARK)
    d = ImageDraw.Draw(base)
    lockup(base, d, W / 2, 104, GOLD_LIGHT, 0.78, sub="")

    pw = W - 2 * M
    ph_h = int(pw * 9 / 16)
    ph = grade(smart_crop(Image.open(photo_path), 16 / 9), 0.9).resize((pw, ph_h), Image.LANCZOS)
    py = 300
    base.paste(ph, (M, py))
    d.rectangle([M - 11, py - 11, M + pw + 10, py + ph_h + 10], outline=GOLD, width=1)

    y = py + ph_h + 92
    _text_ls(d, (W / 2, y), eyebrow.upper(), font("jp", 20, 500), GOLD, ls=7, center=True)
    y += 54
    fh = font("pf", 56, 500)
    for ln in _wrap_en(d, en, fh, W - 2 * M - 60)[:2]:
        _text_ls(d, (W / 2, y), ln, fh, CREAM, center=True)
        y += 70
    y += 14
    fj = font("jp", 25, 400)
    for ln in _wrap_jp(d, ja, fj, W - 2 * M - 60)[:2]:
        _text_ls(d, (W / 2, y), ln, fj, (214, 200, 186), center=True)
        y += 40

    _text_ls(d, (W / 2, H - 108), "SUKHUMVIT SOI 15  ·  BANGKOK  ·  CORANBANGKOK.COM",
             font("jp", 15, 400), (168, 146, 120), ls=3, center=True)
    return base


LAYOUTS = {"A": layout_editorial, "B": layout_testimonial, "C": layout_sanctuary}
