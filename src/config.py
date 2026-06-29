"""
設定の単一情報源（Single Source of Truth）。
すべての秘密情報は環境変数（GitHub Secrets）から読む。ソース直書きは禁止。
"""
import os


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(f"[CONFIG ERROR] 環境変数 {name} が未設定です。GitHub Secrets を確認してください。")
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Instagram Graph API ---
IG_USER_ID = _require("IG_USER_ID")          # Instagram ビジネスアカウントID
IG_ACCESS_TOKEN = _require("IG_ACCESS_TOKEN")  # 長期アクセストークン（60日・自動更新）
GRAPH_API_VERSION = _optional("GRAPH_API_VERSION", "v21.0")

# --- 画像の公開配信ベースURL ---
# 例: https://raw.githubusercontent.com/<owner>/<repo>/main/images
# z.com を完全に捨て、GitHub の raw URL で画像を公開する。
IMAGE_BASE_URL = _require("IMAGE_BASE_URL").rstrip("/")

# --- Google レビュー（任意：レビュー投稿を使う場合のみ）---
GOOGLE_PLACES_API_KEY = _optional("GOOGLE_PLACES_API_KEY")
GOOGLE_PLACE_ID = _optional("GOOGLE_PLACE_ID")

# --- LINE 通知（任意：投稿候補をスマホに飛ばしたい場合のみ）---
LINE_CHANNEL_ACCESS_TOKEN = _optional("LINE_CHANNEL_ACCESS_TOKEN")
LINE_TO_USER_ID = _optional("LINE_TO_USER_ID")

# --- パス ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
STATE_DIR = os.path.join(ROOT, "state")
MANIFEST_PATH = os.path.join(IMAGES_DIR, "manifest.json")
USED_STATE_PATH = os.path.join(STATE_DIR, "used.json")
ROTATION_STATE_PATH = os.path.join(STATE_DIR, "rotation.json")
CANDIDATE_PATH = os.path.join(ROOT, "candidate.json")
