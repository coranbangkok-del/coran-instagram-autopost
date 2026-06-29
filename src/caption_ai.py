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
