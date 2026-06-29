"""
キャプション生成（テンプレ反復・固定ハッシュタグからの脱却）。

【報告書の指摘に対応】
- 文型の反復を避けるため、複数プールからランダム合成
- ハッシュタグはコア＋ローテーションで毎回完全一致を避ける（シャドウバン対策）
- レビューは全文引用せず最大15語程度に切り詰める
B2C @coranboutiquespa: 日英バイリンガル / ハッシュタグ 15〜20個。
"""
import random
import textwrap

# サービス紹介の導入フレーズ（反復回避用に複数）
SERVICE_OPENERS = [
    "Slow down. Breathe. You deserve this moment. 🌿",
    "A quiet escape in the heart of Bangkok. 🤍",
    "Where the city fades and calm begins. 🌿",
    "Your body keeps the score — let us help you release it. 🤍",
    "Reset your mind, restore your body. 🌿",
]

SERVICE_OPENERS_JA = [
    "心も体も、ゆっくりほどいていく時間を。🌿",
    "バンコクの真ん中で、静かに整う。🤍",
    "今日のあなたに、ご褒美のひとときを。🌿",
    "頑張った体に、深い休息を。🤍",
    "都会の喧騒を忘れる、癒しの空間へ。🌿",
]

SERVICE_CLOSERS = [
    "Book your moment — link in bio.",
    "Reserve via LINE or our website. ご予約はLINE・サイトから。",
    "DMでもご予約承ります。Feel free to DM us.",
]

# レビュー投稿の導入
REVIEW_OPENERS = [
    "Words from our guests mean everything. 🤍",
    "Real stories from real guests. 🌿",
    "Thank you for trusting CORAN. 🤍",
]

# ハッシュタグ：コア（毎回）＋ローテーション（毎回入れ替え）
CORE_TAGS = ["#coranboutiquespa", "#bangkokspa", "#spabangkok"]
ROTATING_TAGS = [
    "#bangkokmassage", "#asokspa", "#sukhumvitspa", "#facialbangkok",
    "#aromatherapy", "#wellnessbangkok", "#thaimassage", "#luxuryspa",
    "#selfcarebangkok", "#bangkokwellness", "#relaxbangkok", "#นวดกรุงเทพ",
    "#สปากรุงเทพ", "#バンコクスパ", "#バンコクマッサージ", "#bangkoklife",
    "#nanaspa", "#prompongspa", "#facialtreatment", "#bodymassage",
]


def _hashtags(n_total=18):
    """コア3個 + ローテーションから合計 15〜20個になるよう毎回入れ替えて選ぶ。"""
    pool = ROTATING_TAGS[:]
    random.shuffle(pool)
    picked = CORE_TAGS + pool[: max(12, n_total - len(CORE_TAGS))]
    return " ".join(picked)


def _trim_quote(text, max_words=15):
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,") + "…"


def build_service_caption(photo):
    """サービス紹介投稿のキャプション。"""
    en = random.choice(SERVICE_OPENERS)
    ja = random.choice(SERVICE_OPENERS_JA)
    closer = random.choice(SERVICE_CLOSERS)
    body = f"{en}\n{ja}\n\n📍 CORAN Boutique Spa — Sukhumvit Soi 15, Bangkok\n{closer}"
    return f"{body}\n\n{_hashtags()}"


def build_review_caption(review):
    """レビュー投稿のキャプション（要約引用 + 御礼）。"""
    opener = random.choice(REVIEW_OPENERS)
    quote = _trim_quote(review["text"])
    stars = "⭐️" * int(review.get("rating", 5))
    body = (
        f"{opener}\n\n"
        f"{stars}\n"
        f"“{quote}”\n— {review.get('author_initial', 'G.')}\n\n"
        f"皆さまの声が私たちの励みです。ありがとうございます。🤍\n"
        f"📍 CORAN Boutique Spa — Sukhumvit Soi 15, Bangkok"
    )
    return f"{body}\n\n{_hashtags()}"
