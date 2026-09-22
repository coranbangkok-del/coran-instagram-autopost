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
#   既定はON。素材をそのまま投げず、4:5(1080x1350)のCORANの画に変換してから投稿する。
#   不具合時は Secrets/変数に BRAND_IMAGE=off を入れれば従来どおり素材をそのまま使う。
BRAND_IMAGE = (_optional("BRAND_IMAGE", "on") or "on").lower()

# --- パス ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
STATE_DIR = os.path.join(ROOT, "state")
MANIFEST_PATH = os.path.join(IMAGES_DIR, "manifest.json")
USED_STATE_PATH = os.path.join(STATE_DIR, "used.json")
ROTATION_STATE_PATH = os.path.join(STATE_DIR, "rotation.json")
# 月次カレンダー承認（S-2）で公開済みにした投稿の id（= 日付）。二重投稿を防ぐ。
CALENDAR_PUBLISHED_PATH = os.path.join(STATE_DIR, "calendar_published.json")
FONTS_DIR = os.path.join(ROOT, "fonts")
ASSETS_DIR = os.path.join(ROOT, "assets")
MARK_PATH = os.path.join(ASSETS_DIR, "coran-mark.png")
GENERATED_DIR = os.path.join(IMAGES_DIR, "generated")
CANDIDATE_PATH = os.path.join(ROOT, "candidate.json")
GBP_CANDIDATE_PATH = os.path.join(ROOT, "gbp_candidate.json")
