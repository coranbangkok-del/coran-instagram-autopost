"""
写真選択ロジック（シャッフルバッグ方式）。

【あなたの「同じ写真の使い回しでストレス」を根本解決する中核】
- 1巡するまで同じ写真は二度と出さない（used.json で履歴管理）
- 全部使い切ったら自動で履歴をリセットして次の巡へ
- タグ一致（例: フェイシャルのレビュー → フェイシャル写真）でミスマッチも防ぐ
"""
import json
import os
import random

import config


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_manifest():
    """images/manifest.json を読む。各要素: {file, tags:[...], aspect, alt}"""
    manifest = _load_json(config.MANIFEST_PATH, [])
    if not manifest:
        raise SystemExit("[PHOTO ERROR] images/manifest.json が空です。写真を登録してください。")
    return manifest


def pick_photo(preferred_tags=None):
    """
    使用済みでない写真から1枚選ぶ。
    preferred_tags があればまずタグ一致で絞り、無ければ全体から選ぶ。
    戻り値: (photo_dict, public_url)
    """
    manifest = load_manifest()
    used = set(_load_json(config.USED_STATE_PATH, {"cycle": [], "history": []})["cycle"])

    # まだこの巡で使っていない写真
    available = [p for p in manifest if p["file"] not in used]

    # 全部使い切ったら巡をリセット（＝ここで初めて再登場が許される）
    if not available:
        print("[PHOTO] 全写真を1巡しました。履歴をリセットして次の巡へ。")
        used = set()
        available = list(manifest)

    # タグ一致で優先的に絞り込む（ミスマッチ防止）
    pool = available
    if preferred_tags:
        tagged = [p for p in available if set(p.get("tags", [])) & set(preferred_tags)]
        if tagged:
            pool = tagged

    photo = random.choice(pool)
    public_url = f"{config.IMAGE_BASE_URL}/{photo['file']}"
    return photo, public_url


def mark_used(photo):
    """投稿確定後に呼ぶ。used.json を更新（この巡 + 全期間履歴）。"""
    state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": []})
    state["cycle"].append(photo["file"])
    state["history"].append(photo["file"])
    # 全写真を1巡したら cycle をクリア
    manifest = load_manifest()
    if len(set(state["cycle"])) >= len(manifest):
        state["cycle"] = []
    _save_json(config.USED_STATE_PATH, state)
    print(f"[PHOTO] 使用済みに記録: {photo['file']}")
