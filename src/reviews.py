"""
Google レビュー取得 + 品質フィルタ + 個人情報マスク。

【報告書の指摘に対応】
- 平凡/短すぎるレビューを除外（品質フィルタ）
- 個人名・他店名の混入を抑制（マスク）
- 全文引用しない（最大15語程度に要約引用するのは caption.py 側）
レビューを使わない運用なら GOOGLE_PLACES_API_KEY を空にしておけばよい。
"""
import re
import json

import requests

import config

# 競合店名など、混入したら困る固有名詞（必要に応じて追記）
BLOCKLIST = [
    # "Competitor Spa Name",
]

# 短すぎ・低評価は弾く閾値
MIN_RATING = 5
MIN_CHARS = 40


def _mask_personal(text: str) -> str:
    """簡易な個人名マスク。@メンション・URL・電話番号を伏せる。"""
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"\+?\d[\d\-\s]{7,}\d", "", text)  # 電話番号
    for word in BLOCKLIST:
        if word:
            text = text.replace(word, "")
    return text.strip()


def fetch_reviews():
    """Google Places Details API からレビューを取得して品質フィルタを通す。"""
    if not config.GOOGLE_PLACES_API_KEY or not config.GOOGLE_PLACE_ID:
        return []

    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": config.GOOGLE_PLACE_ID,
        "fields": "review",
        "reviews_sort": "newest",
        "key": config.GOOGLE_PLACES_API_KEY,
        "language": "en",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("result", {}).get("reviews", [])

    good = []
    for r in raw:
        rating = r.get("rating", 0)
        text = _mask_personal(r.get("text", ""))
        if rating < MIN_RATING:
            continue
        if len(text) < MIN_CHARS:
            continue
        good.append({
            "rating": rating,
            "text": text,
            "author_initial": (r.get("author_name", "G")[:1] or "G") + ".",
        })
    return good


def pick_unused_review(good_reviews, used_texts):
    """過去に使ったレビューと重複しないものを1件返す。無ければ None。"""
    for r in good_reviews:
        key = r["text"][:60]
        if key not in used_texts:
            return r
    return None
