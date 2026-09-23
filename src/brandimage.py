# -*- coding: utf-8 -*-
"""
素材写真 → CORAN Frame の1枚を作るところまでの受け持ち。

main.py からは build() を1回呼ぶだけ。中でやること:
  1. どのレイアウト（A/B/C）で組むかを決める
  2. 画像に載せる一行（英・和）を用意する（Claude生成→失敗時はカテゴリ別テンプレ）
  3. brandkit で描画し images/generated/ に保存して、公開URLを返す

画像の生成に失敗しても投稿を止めない（呼び出し側が素材そのままへフォールバックする）。
"""
import glob
import os
import time

import config

# カテゴリ → (小見出し, 既定レイアウト, [(英語の一行, 和文の一行), ...])
#   一行は Claude が使えないときのフォールバック。APIが続けて失敗しても同じ文が並ばないよう
#   カテゴリごとに複数持ち、素材のファイル名から決まる（同じ写真なら毎回同じ・写真が違えば違う）。
#   ★事実の主張（価格・所要時間・人数）はここに書かない。
#   所要時間を書くと、画を選ぶ側（coran-social の selectFrame）はメニューの分数を見ていないので、
#   60分のメニューに「ninety minutes」の画が当たって事実と違う投稿になる（2026-09-23 に実在した）。
#   tools/build_social_frames.py の見出し検査がこれを機械的に弾く。
#   例外は award カテゴリの受賞名だけ（実際の受賞で、受賞写真にしか使われない）。
CATEGORY = {
    "aroma": ("Aromatherapy Massage", "A", [
        ("The city goes quiet under warm oil.", "温めたオイルが、都会の音を遠ざけていく。"),
        ("Warm oil, slow hands.", "温かなオイルと、ゆっくりした手のひら。"),
        ("Breathe out. We will take it from here.", "力を抜いて。あとはこちらで。"),
        ("Where the day stops following you.", "追いかけてくる一日を、ここで置いていく。"),
    ]),
    "award": ("Award Winning", "C", [
        ("World Luxury Spa Awards Winner", "ワールドラグジュアリースパアワード受賞。"),
    ]),
    "body-mask": ("Body Mask & Wrap", "A", [
        ("Wrapped, warmed, and let go.", "包まれて、温まって、ほどけていく。"),
        ("Stillness, and the skin answers.", "動かずにいる時間が、肌を変えていく。"),
    ]),
    "body-scrub": ("Body Scrub", "A", [
        ("Skin remembers kindness.", "肌は、やさしさを覚えている。"),
        ("Rough day, smooth finish.", "ざらついた一日を、なめらかに。"),
    ]),
    "coconut": ("Coconut Treatment", "A", [
        ("Coconut, slow and warm.", "ココナッツの温もりを、ゆっくりと。"),
        ("The islands, in a jar.", "南の島の恵みを、ひと瓶に。"),
    ]),
    "facial": ("Organic Facial", "A", [
        ("Quiet care, face to face.", "静かな時間が、肌を整えていく。"),
        ("Your face, unclenched.", "こわばった表情が、ほどけていく。"),
    ]),
    "foot": ("Foot Reflexology", "A", [
        ("For the part of you that walks all day.", "一日中歩いた足に、ごほうびの時間を。"),
        ("Bangkok is hard on feet.", "歩きどおしの街だから、足から休ませる。"),
    ]),
    "head-massage": ("Head & Scalp Therapy", "A", [
        ("Where the day finally lets go.", "考えごとの多い一日を、頭から解いていく。"),
        ("Too many tabs open.", "頭のなかを、ひとつずつ閉じていく。"),
    ]),
    "herbal-ball": ("Thai Herbal Compress", "A", [
        ("Steamed herbs, pressed warm.", "蒸したてのハーブボールを、ゆっくりと。"),
    ]),
    "herbs": ("Thai Herbal Remedy", "A", [
        ("Old recipes, still working.", "タイに伝わる薬草の知恵を、いまの施術に。"),
        ("Grown here. Used here.", "この土地の薬草を、この手で。"),
    ]),
    "maternity-massage": ("Maternity & Postnatal", "A", [
        ("Rest, for two.", "ふたりぶんの体に、やさしい休息を。"),
        ("Carried all day. Carried here, too.", "抱えてきた重さを、ここでは預けて。"),
    ]),
    "milk-spa": ("Milk Spa", "A", [
        ("Milk, warmth, and quiet.", "ミルクの温もりに包まれる時間。"),
    ]),
    "office-syndrome": ("Office Syndrome Care", "A", [
        ("For shoulders that hold too much.", "抱えこんだ肩に、ほどく時間を。"),
        ("Desk all day, undone here.", "デスクでこわばった体を、ほどいていく。"),
    ]),
    "product": ("Our Products", "A", [
        ("Made for the skin we touch.", "施術で使うものを、そのままお持ち帰りに。"),
    ]),
    "shirodhara": ("Shirodhara · Ayurveda", "A", [
        ("A single thread of warm oil.", "額に落ちる一筋のオイルが、思考を静めていく。"),
        ("Let the mind go quiet.", "考えごとが、しずかに止まっていく。"),
    ]),
    "thai-massage": ("Traditional Thai Massage", "A", [
        ("Stretch, breathe, begin again.", "伸びて、ほどけて、また歩き出せる。"),
        ("An old Thai craft, done with care.", "タイに受け継がれる手技を、ていねいに。"),
    ]),
    "shop": ("Our Sanctuary", "C", [
        ("A quiet street, a quieter room.", "スクンビット soi 15、静かな一角に。"),
        ("Third floor. The city drops away.", "3階のドアを開けると、街の音が遠くなる。"),
        ("Rooms built for not being disturbed.", "邪魔をされないための、個室です。"),
    ]),
}
DEFAULT = ("CORAN Boutique Spa", "A",
           [("A quiet escape in the heart of Bangkok.", "バンコクの真ん中で、静かに整う。")])

# お客様の声(B)のときの和文フォールバック。施術紹介の一行を流用すると文脈がずれる。
REVIEW_JA = [
    "うれしいお言葉をありがとうございます。",
    "またお会いできる日を楽しみにしています。",
    "お客様の声が、いちばんの励みです。",
]


def category_of(photo):
    """manifest の file は "<カテゴリ>/<ファイル名>"。"""
    return (photo.get("file") or "").split("/")[0]


def _variant(seq, key):
    """同じ写真には同じ一行、写真が違えば違う一行（乱数を使わないので結果が再現する）。"""
    h = 0
    for ch in str(key):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return seq[h % len(seq)]


def meta_for(photo):
    c = category_of(photo)
    eyebrow, layout, lines = CATEGORY.get(c, DEFAULT)
    en, ja = _variant(lines, photo.get("file", c))
    # manifest 側で個別に上書きできる（将来 1枚単位で変えたくなったとき用）
    return (photo.get("eyebrow") or eyebrow,
            photo.get("layout") or layout,
            en, ja)


def choose_layout(post_type, photo, has_review):
    """投稿の種類と素材から、組み方を決める。

    review     … B（クリーム地の「お客様の声」）
    sanctuary  … C（深ブラウン地・実店舗を切らずに額装）
    service    … 素材のカテゴリ既定（実店舗/受賞/商品は C、それ以外は A）
    """
    if post_type == "review" and has_review:
        return "B"
    if post_type == "sanctuary":
        return "C"
    return meta_for(photo)[1]


def _cleanup(keep=None):
    """承認待ちは常に最新1件（post.yml の concurrency）なので、生成物も最新1枚だけ残す。"""
    for p in glob.glob(os.path.join(config.GENERATED_DIR, "*.jpg")):
        if keep and os.path.abspath(p) == os.path.abspath(keep):
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def render(post_type, photo, review=None, headline=None):
    """描画だけを行い (PIL.Image, layout) を返す。保存と公開URLは build() の担当。

    プレビュー用スクリプトもここを通す＝「プレビューと本番で絵が違う」を起こさない。
    """
    import brandkit
    from PIL import Image

    src = os.path.join(config.IMAGES_DIR, photo["file"])
    if not os.path.exists(src):
        raise FileNotFoundError(src)

    layout = choose_layout(post_type, photo, bool(review))
    eyebrow, _, fb_en, fb_ja = meta_for(photo)
    en, ja = (headline or (None, None))
    en = (en or fb_en).strip()
    ja = (ja or fb_ja).strip()

    # 横が細すぎる素材を 4:5 に引き伸ばすと眠くなる → 切らずに額装する C へ逃がす
    if layout == "A":
        with Image.open(src) as im:
            if brandkit.crop_width_for(im) < brandkit.MIN_CROP_W:
                print(f"[BRAND] 素材が小さいため A→C に変更: {photo['file']}")
                layout = "C"

    if layout == "B":
        quote = " ".join((review or {}).get("text", "").split()[:18]).rstrip(".,")
        if quote:
            # 声への返しなので、施術紹介の一行は流用しない
            b_ja = ja if (headline and headline[1]) else _variant(REVIEW_JA, quote)
            return brandkit.layout_testimonial(src, quote, b_ja, "Guest Review  ·  Google"), "B"
        layout = "C"   # 引用できる声が無ければ空の吹き出しは出さない

    if layout == "C":
        return brandkit.layout_sanctuary(src, eyebrow, en, ja), "C"
    return brandkit.layout_editorial(src, eyebrow, en, ja), "A"


def build(post_type, photo, review=None, headline=None):
    """ブランド画像を1枚作って保存する。

    戻り値: (public_url, rel_path, layout) / 失敗時は (None, None, None)
    """
    try:
        img, layout = render(post_type, photo, review, headline)
    except FileNotFoundError as e:
        print(f"[BRAND] 素材が見つかりません: {e}")
        return None, None, None
    except Exception as e:
        print(f"[BRAND] 生成に失敗しました（素材そのままへフォールバック）: {type(e).__name__}: {e}")
        return None, None, None

    os.makedirs(config.GENERATED_DIR, exist_ok=True)
    slug = os.path.splitext(os.path.basename(photo["file"]))[0][:48]
    rel = f"generated/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{layout}-{slug}.jpg"
    out = os.path.join(config.IMAGES_DIR, rel)
    img.save(out, quality=90, optimize=True, subsampling=1)
    _cleanup(keep=out)

    url = f"{config.IMAGE_BASE_URL}/{rel}"
    print(f"[BRAND] 生成しました layout={layout} {rel} ({os.path.getsize(out)//1024}KB)")
    return url, rel, layout
