"""
長期アクセストークンの自動更新（サイレント投稿停止の防止）。

Instagram Graph API（Facebookログイン）の長期トークンは約60日で失効する。
本スクリプトは現行トークンを延長し、新トークンを GITHUB_OUTPUT に流す。
GitHub Actions 側で `gh secret set IG_ACCESS_TOKEN` により Secret を更新する。

必要な環境変数: FB_APP_ID, FB_APP_SECRET, IG_ACCESS_TOKEN
"""
import os
import sys

import requests


def _require(name: str) -> str:
    """環境変数を strip して返す。空・未設定なら fail-fast。"""
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"[TOKEN ERROR] Missing secret: {name}", file=sys.stderr)
        sys.exit(1)
    return val


def main():
    app_id = _require("FB_APP_ID")
    app_secret = _require("FB_APP_SECRET")
    current = _require("IG_ACCESS_TOKEN")
    version = os.environ.get("GRAPH_API_VERSION", "v21.0").strip() or "v21.0"

    url = f"https://graph.facebook.com/{version}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": current,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        # URL（クエリ含む）を出さない。例外種別のみ。
        print(f"[TOKEN ERROR] リクエスト失敗: {type(e).__name__}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        # resp.text / URL 全文は出さず、Meta の error.message のみ抽出。
        try:
            msg = resp.json().get("error", {}).get("message", "(no message)")
        except ValueError:
            msg = "(non-JSON response)"
        print(f"[TOKEN ERROR] HTTP {resp.status_code}: {msg}", file=sys.stderr)
        sys.exit(1)

    new_token = resp.json().get("access_token")
    if not new_token:
        print("[TOKEN ERROR] 更新に失敗: access_token がレスポンスに含まれません", file=sys.stderr)
        sys.exit(1)

    # 新トークンをログ上でマスク（自動マスク対象外のため明示）。
    print(f"::add-mask::{new_token}")

    # GitHub Actions の出力に流す（後続ステップで Secret 更新に使う）。
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"new_token={new_token}\n")
    print("[TOKEN] 更新成功（新トークンを取得）")


if __name__ == "__main__":
    main()
