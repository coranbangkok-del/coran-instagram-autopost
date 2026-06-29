"""
Instagram Graph API クライアント（2ステップ投稿）。
1. メディアコンテナ作成（公開画像URL + キャプション）
2. 公開（publish）
画像URLは公開アクセス可能でなければならない → GitHub raw URL を使う（z.com不要）。
"""
import time

import requests

import config

BASE = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"


def _post(path, params):
    url = f"{BASE}/{path}"
    resp = requests.post(url, data=params, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"[IG API ERROR] {resp.status_code}: {resp.text}")
    return resp.json()


def create_container(image_url: str, caption: str) -> str:
    """メディアコンテナを作成し creation_id を返す。"""
    res = _post(
        f"{config.IG_USER_ID}/media",
        {"image_url": image_url, "caption": caption, "access_token": config.IG_ACCESS_TOKEN},
    )
    creation_id = res.get("id")
    if not creation_id:
        raise RuntimeError(f"[IG API ERROR] creation_id が取得できません: {res}")
    return creation_id


def publish(creation_id: str) -> str:
    """コンテナを公開し、投稿IDを返す。"""
    # コンテナが処理完了するまで少し待つ（大きい画像対策）
    time.sleep(5)
    res = _post(
        f"{config.IG_USER_ID}/media_publish",
        {"creation_id": creation_id, "access_token": config.IG_ACCESS_TOKEN},
    )
    media_id = res.get("id")
    if not media_id:
        raise RuntimeError(f"[IG API ERROR] 公開に失敗: {res}")
    return media_id


def post_image(image_url: str, caption: str) -> str:
    """画像URL + キャプションを投稿。投稿IDを返す。"""
    creation_id = create_container(image_url, caption)
    return publish(creation_id)
