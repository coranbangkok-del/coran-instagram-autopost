"""
Claude(claude-opus-4-8)によるキャプション本文生成。

【方針】
- 本文だけをClaudeが生成（テンプレ反復・Bot臭さを解消、写真カテゴリに必ず一致）
- ハッシュタグは caption.py のローテーションプールから付与（シャドウバン/個数ブレ防止）
- APIキー未設定 or API失敗時は caption.py のテンプレに自動フォールバック（投稿を止めない）
ANTHROPIC_API_KEY を GitHub Secrets に入れると有効化。無ければ自動でテンプレ運用。
"""
import os

import caption as tmpl

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
あなたは高級ブティックスパ「CORAN Boutique Spa」(@coranboutiquespa) の
Instagram運用担当コピーライターです。所在地はバンコク Sukhumvit Soi 15。
読者はB2C(在住者・旅行者)、主に日本語と英語の利用者。

# 書き方のルール
- 必ず英語→日本語の順でバイリンガル。各2〜4行程度。
- 温かく、静かで、上質。五感に訴える描写。スパの落ち着いた世界観。
- 毎回 文体・出だし・構成を変える。定型文の反復は禁止。
- AIっぽい安っぽい常套句(「Indulge in」「Treat yourself」連発等)や絵文字の乱用を避ける。
  絵文字は0〜2個まで、上品に。
- 与えられた「写真カテゴリ」に必ず内容を合わせる(例: フットスパならフット/リフレを語る)。
- 末尾に所在地の一行と、柔らかい予約CTA(LINE/サイト/DM)を1つ。
- ハッシュタグは書かない(別処理で付与する)。
- 価格・金額・割引・クーポン・キャンペーン・所要時間は書かない(事実の主張は別の場所に載せる)。
- レビュー投稿の場合: 提供されたお客様の声を最大15語程度だけ引用し感謝を述べる。
  事実を捏造しない。個人名・他店名は出さない。
- 出力は「投稿にそのまま使える本文のみ」。前置き・説明・コードブロックは一切不要。
"""


def _build_user_prompt(post_type, photo, review):
    cat = (photo or {}).get("alt") or " ".join((photo or {}).get("tags", []))
    if post_type == "review" and review:
        return (
            f"種別: お客様の声(レビュー)投稿\n"
            f"写真カテゴリ: {cat}\n"
            f"お客様の声(評価{review.get('rating', 5)}): \"{review.get('text', '')}\"\n"
            f"この声を最大15語程度だけ引用し、感謝を込めたバイリンガル本文を書いてください。"
        )
    return (
        f"種別: サービス紹介投稿\n"
        f"写真カテゴリ: {cat}\n"
        f"このカテゴリの施術/空間の魅力を伝えるバイリンガル本文を書いてください。"
    )


def _generate_body(post_type, photo, review):
    """Claudeで本文を生成。失敗時は例外を投げる(呼び出し側でフォールバック)。"""
    import anthropic  # 遅延import: 未インストール環境でも import 段階で落ちないように

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境から読む
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(post_type, photo, review)}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("Claudeの応答が空でした")
    return text


def build_caption(post_type, photo, review=None):
    """
    AIで本文生成 → ローテーションのハッシュタグを付与して返す。
    APIキー無し or 失敗時は caption.py のテンプレ全文にフォールバック。
    """
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("[CAPTION] ANTHROPIC_API_KEY 未設定 → テンプレートで生成")
        return _fallback(post_type, photo, review)

    try:
        body = _generate_body(post_type, photo, review)
        print("[CAPTION] Claude生成に成功")
        return f"{body}\n\n{tmpl._hashtags()}"
    except Exception as e:  # API障害・レート制限・ネット断などでも投稿を止めない
        print(f"[CAPTION] Claude生成に失敗({e}) → テンプレートにフォールバック")
        return _fallback(post_type, photo, review)


def _fallback(post_type, photo, review):
    if post_type == "review" and review:
        return tmpl.build_review_caption(review)
    return tmpl.build_service_caption(photo)


# ---------------------------------------------------------------- 画像に載せる一行
HEADLINE_SYSTEM = """\
あなたは高級ブティックスパ「CORAN Boutique Spa」(バンコク Sukhumvit Soi 15) の
Instagram 画像に載せる「見出し」を書くコピーライターです。

# 出力の形式（厳守）
1行目: 英語の見出し
2行目: 日本語の見出し
それ以外は一切出力しない（前置き・説明・記号・引用符・ハッシュタグ・絵文字は禁止）。

# 書き方
- 英語は 最大42文字。日本語は 最大26文字。必ずこの範囲に収める。
- 写真に写っているものと、与えられたカテゴリに必ず合わせる。
- 静かで上質。五感に触れる具体。宣伝文句や誇張はしない。
- 価格・所要時間・割引・受賞名・電話番号など「事実の主張」は書かない（別の場所に載せる）。
- 英語と日本語は直訳でなくてよい。それぞれ自然な一行にする。
- 毎回ちがう言い回しにする。定型の反復は禁止。
"""


def _clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n].rstrip(" 、。,.")


def build_image_headline(post_type, photo, review=None, eyebrow=""):
    """画像用の見出し（英1行・和1行）を Claude で作る。

    戻り値: (en, ja) / 生成できなければ None（呼び出し側がカテゴリ別テンプレを使う）
    """
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return None

    cat = (photo or {}).get("file", "").split("/")[0]
    user = (f"カテゴリ: {eyebrow or cat}\n"
            f"写真: {cat}\n")
    if post_type == "review" and review:
        user += (f"種別: お客様の声\n"
                 f"お客様の声(抜粋): \"{(review.get('text') or '')[:180]}\"\n"
                 "この声に添う、感謝の気持ちが伝わる見出しを書いてください。\n")
    else:
        user += "種別: 施術・空間の紹介\nこのカテゴリの施術や空間が伝わる見出しを書いてください。\n"

    try:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL, max_tokens=200, system=HEADLINE_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) < 2:
            print("[HEADLINE] 2行で返らなかったためテンプレへ")
            return None
        en, ja = _clip(lines[0], 42), _clip(lines[1], 26)
        if not en or not ja:
            return None
        print(f"[HEADLINE] Claude生成に成功: {en} / {ja}")
        return en, ja
    except Exception as e:
        print(f"[HEADLINE] 生成に失敗({type(e).__name__}) → テンプレートにフォールバック")
        return None
