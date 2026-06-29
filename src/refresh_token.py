"""
長期アクセストークンの自動更新（サイレント投稿停止の防止）。

Instagram Graph API（Facebookログイン）の長期トークンは約60日で失効する。
本スクリプトは現行トークンを延長し、新トークンを標準出力に出す。
GitHub Actions 側で `gh secret set IG_ACCESS_TOKEN` により Secret を更新する。

必要な環境変数: FB_APP_ID, FB_APP_SECRET, IG_ACCESS_TOKEN
"""
import os
import sys

import requests

APP_ID = os.environ["FB_APP_ID"]
APP_SECRET = os.environ["FB_APP_SECRET"]
CURRENT = os.environ["IG_ACCESS_TOKEN"]
VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")


def main():
    url = f"https://graph.facebook.com/{VERSION}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": CURRENT,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    new_token = resp.json().get("access_token")
    if not new_token:
        print(f"[TOKEN ERROR] 更新に失敗: {resp.text}", file=sys.stderr)
        sys.exit(1)
    # GitHub Actions の出力に流す（後続ステップで Secret 更新に使う）
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"new_token={new_token}\n")
    print("[TOKEN] 更新成功（新トークンを取得）")


if __name__ == "__main__":
    main()
