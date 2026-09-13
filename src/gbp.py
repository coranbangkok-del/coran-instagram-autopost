"""
Google Business Profile（GBP）ローカル投稿クライアント。
  スポット空き告知を GBP の「最新情報 / 特典（localPosts）」として投稿する。

★重要:
  - GBP への投稿は Business Profile（旧 Google My Business）API の OAuth2 が必要。
    Places API キー（レビュー取得用）とは別物。account/location の resource 名も要る。
  - API の提供状況・スコープ承認は Google 側審査に依存する（ピンク/レジ + Takuro が確認）。
    → 認証情報が未設定なら publish-gbp は明示エラーで停止（誤投稿しない）。
"""
import requests

import config

# v4 (mybusiness) の localPosts エンドポイント。account/location は resource 名（accounts/x, locations/y）。
BASE = "https://mybusiness.googleapis.com/v4"


def post_local_post(summary: str, cta_url: str, topic_type: str = "OFFER") -> str:
    """localPost を作成。作成された投稿の name を返す。認証情報不足なら SystemExit。"""
    token = config.GBP_ACCESS_TOKEN
    account = config.GBP_ACCOUNT
    location = config.GBP_LOCATION
    if not token or not account or not location:
        raise SystemExit(
            "[GBP ERROR] GBP_ACCESS_TOKEN / GBP_ACCOUNT / GBP_LOCATION が未設定です。"
            "Business Profile API の OAuth 認証情報を Secrets に設定してください。"
        )

    url = f"{BASE}/{account}/{location}/localPosts"
    body = {
        "languageCode": config.GBP_LANG,
        "summary": summary[:1500],  # GBP summary 上限
        "topicType": topic_type,     # OFFER / STANDARD 等
    }
    if cta_url:
        body["callToAction"] = {"actionType": "BOOK", "url": cta_url}

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"[GBP API ERROR] {resp.status_code}: {resp.text}")
    return resp.json().get("name", "")
