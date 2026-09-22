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

# --- スポット空き自動告知（任意・既定OFF）---
#   SPOT_SNS="on" のときだけ prepare-spot が候補を作る。SPOT_ANNOUNCE_URL は
#   予約バックエンドの GET /api/spot-announcement?channel=sns（投稿可能キャプションを返す）。
SPOT_SNS = _optional("SPOT_SNS")               # "on" で有効化
SPOT_ANNOUNCE_URL = _optional("SPOT_ANNOUNCE_URL")  # 例: https://book.coranbangkok.com/api/spot-announcement?channel=sns

# --- Google Business Profile 投稿（任意・既定OFF）---
#   GBP_POST="on" のときだけ prepare-gbp が候補を作る。GBP_ANNOUNCE_URL は ?channel=gbp。
#   実投稿(publish-gbp)は GBP(Business Profile) API の OAuth が必要（ピンク/レッド + Takuro）。
GBP_POST = _optional("GBP_POST")                     # "on" で有効化
GBP_ANNOUNCE_URL = _optional("GBP_ANNOUNCE_URL")     # 例: https://book.coranbangkok.com/api/spot-announcement?channel=gbp
GBP_ACCESS_TOKEN = _optional("GBP_ACCESS_TOKEN")     # OAuth2 アクセストークン（Business Profile スコープ）
GBP_ACCOUNT = _optional("GBP_ACCOUNT")               # 例: accounts/1234567890
GBP_LOCATION = _optional("GBP_LOCATION")             # 例: locations/9876543210
GBP_LANG = _optional("GBP_LANG", "en")               # 投稿言語（GBP投稿は単一言語）

# --- 画像のブランド化（CORAN Frame）---
#   画像は必ず CORAN Frame（4:5・1080x1350）を通す。2026-09-22 社長指示で「素材そのまま」の
#   経路（旧 BRAND_IMAGE=off）は撤去した。生成に失敗したら、その回は候補を作らない。

# --- スマホ承認（Claude の非公開 Artifact・2026-09-22〜）---
#   社長の端末の公開鍵（SPKI の base64・改行かカンマ区切り）。GitHub の Actions 変数に置く。
#   未設定なら投稿しない（fail-closed）。
IG_APPROVER_PUBKEYS = _optional("IG_APPROVER_PUBKEYS")
QUEUE_BRANCH = "ig-queue"   # 承認待ちの画像と署名つき承認を置くブランチ（main には置かない）

# --- パス ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
STATE_DIR = os.path.join(ROOT, "state")
MANIFEST_PATH = os.path.join(IMAGES_DIR, "manifest.json")
USED_STATE_PATH = os.path.join(STATE_DIR, "used.json")
ROTATION_STATE_PATH = os.path.join(STATE_DIR, "rotation.json")
FONTS_DIR = os.path.join(ROOT, "fonts")
ASSETS_DIR = os.path.join(ROOT, "assets")
MARK_PATH = os.path.join(ASSETS_DIR, "coran-mark.png")
GENERATED_DIR = os.path.join(IMAGES_DIR, "generated")
CANDIDATE_PATH = os.path.join(ROOT, "candidate.json")
GBP_CANDIDATE_PATH = os.path.join(ROOT, "gbp_candidate.json")
POSTED_SLOTS_PATH = os.path.join(STATE_DIR, "posted_slots.json")
