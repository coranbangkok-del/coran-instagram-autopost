"""
エントリポイント。2モードで動く。

  python src/main.py prepare   … 投稿候補（写真+文章）を作って candidate.json に出力 + 承認用サマリ表示
  python src/main.py publish   … 承認後に実際に Instagram へ投稿し、使用済み状態を更新

GitHub Actions では prepare → (人間の承認ゲート) → publish の順で2ジョブに分かれる。
"""
import json
import os
import sys

import config
import photo_picker
import caption as caption_mod
import caption_ai
import reviews as reviews_mod


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_post_type():
    """レビュー投稿とサービス投稿を交互に。状態は rotation.json。"""
    state = _load_json(config.ROTATION_STATE_PATH, {"last": "review"})
    return "service" if state.get("last") == "review" else "review"


def _write_summary(candidate):
    """GitHub Actions の実行サマリに投稿候補を表示（承認者が中身を見られる）。"""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    md = (
        f"## 📣 投稿候補（承認待ち）\n\n"
        f"**種別:** {candidate['post_type']}\n\n"
        f"**写真:** `{candidate['photo_file']}`\n\n"
        f"![preview]({candidate['image_url']})\n\n"
        f"**キャプション:**\n\n```\n{candidate['caption']}\n```\n"
    )
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)


def _notify_line(candidate):
    """任意: LINE に投稿候補を Push（設定があれば）。承認自体は GitHub 側で行う。"""
    if not config.LINE_CHANNEL_ACCESS_TOKEN or not config.LINE_TO_USER_ID:
        return
    import requests
    text = (
        f"📣 Instagram投稿候補（承認待ち）\n種別: {candidate['post_type']}\n\n"
        f"{candidate['caption'][:300]}...\n\nGitHubで承認/却下してください。"
    )
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
        json={
            "to": config.LINE_TO_USER_ID,
            "messages": [
                {"type": "image", "originalContentUrl": candidate["image_url"],
                 "previewImageUrl": candidate["image_url"]},
                {"type": "text", "text": text},
            ],
        },
        timeout=30,
    )


def prepare():
    post_type = _next_post_type()
    review = None

    if post_type == "review":
        good = reviews_mod.fetch_reviews()
        used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
        review = reviews_mod.pick_unused_review(good, set(used_state.get("reviews", [])))
        if not review:
            print("[PREPARE] 使えるレビューが無いため service 投稿に切り替えます。")
            post_type = "service"

    if post_type == "review":
        photo, image_url = photo_picker.pick_photo(preferred_tags=["guest", "ambience", "review"])
        text = caption_ai.build_caption("review", photo, review)
    else:
        photo, image_url = photo_picker.pick_photo(preferred_tags=["service", "treatment", "ambience"])
        text = caption_ai.build_caption("service", photo, None)

    candidate = {
        "post_type": post_type,
        "photo_file": photo["file"],
        "image_url": image_url,
        "caption": text,
        "review_key": (review["text"][:60] if review else None),
    }
    _save_json(config.CANDIDATE_PATH, candidate)
    _write_summary(candidate)
    _notify_line(candidate)
    print(f"[PREPARE] 候補を作成しました: {candidate['photo_file']} / {post_type}")


def publish():
    import instagram
    candidate = _load_json(config.CANDIDATE_PATH, None)
    if not candidate:
        raise SystemExit("[PUBLISH ERROR] candidate.json がありません。")

    media_id = instagram.post_image(candidate["image_url"], candidate["caption"])
    print(f"[PUBLISH] 投稿成功 media_id={media_id}")

    # 使用済み状態を更新（写真・レビュー・交互フラグ）
    manifest = photo_picker.load_manifest()
    photo = next((p for p in manifest if p["file"] == candidate["photo_file"]), {"file": candidate["photo_file"]})
    photo_picker.mark_used(photo)

    used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
    if candidate.get("review_key"):
        used_state.setdefault("reviews", []).append(candidate["review_key"])
        _save_json(config.USED_STATE_PATH, used_state)

    _save_json(config.ROTATION_STATE_PATH, {"last": candidate["post_type"]})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prepare":
        prepare()
    elif mode == "publish":
        publish()
    else:
        raise SystemExit("使い方: python src/main.py [prepare|publish]")
