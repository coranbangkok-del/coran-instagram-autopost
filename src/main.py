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


def _set_output(name, value):
    """GitHub Actions のジョブ出力に書く（publish ジョブの条件分岐に使う）。ローカルでは print のみ。"""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"[OUTPUT] {name}={value}")


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


def _run_url():
    """この実行の GitHub Actions 画面（承認ボタンがある場所）。ローカルでは空文字。"""
    server = os.environ.get("GITHUB_SERVER_URL", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not (server and repo and run_id):
        return ""
    return f"{server}/{repo}/actions/runs/{run_id}"


def _append_summary(md):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)


def _notify_line(candidate):
    """任意: LINE に投稿候補を Push（設定があれば）。承認自体は GitHub 側で行う。

    通知の失敗で候補作成を止めない（例外は握って結果を返す）。結果は実行サマリに残す
    ＝「通知が届いていたのに承認されなかった」のか「そもそも通知が無かった」のかを後から区別できる。
    戻り値: "skipped"（未設定）/ "sent" / "failed:<理由>"
    """
    if not config.LINE_CHANNEL_ACCESS_TOKEN or not config.LINE_TO_USER_ID:
        status = "skipped"
    else:
        import requests
        run_url = _run_url()
        text = (
            f"📣 Instagram投稿候補（承認待ち）\n種別: {candidate['post_type']}\n\n"
            f"{candidate['caption'][:300]}...\n\n"
            f"▼ 承認/却下（Review deployments → Approve）\n{run_url or 'GitHub の Actions 画面'}\n\n"
            f"※次の候補が作られると、この候補は自動で取り消されます。"
        )
        try:
            resp = requests.post(
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
            # 本文はログに出さない（トークンや宛先IDを含むエラー文が返ることがあるため、状態コードのみ）。
            status = "sent" if resp.status_code < 300 else f"failed:HTTP {resp.status_code}"
        except Exception as e:
            status = f"failed:{type(e).__name__}"

    label = {"skipped": "未設定（LINE_CHANNEL_ACCESS_TOKEN / LINE_TO_USER_ID）", "sent": "送信済"}.get(status, status)
    _append_summary(f"\n**LINE 承認依頼の通知:** {label}\n")
    return status


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


def prepare_spot():
    """スポット空き告知の投稿候補を作る（既定OFF・SPOT_SNS=on のときだけ）。

    予約バックエンドの /api/spot-announcement?channel=sns から投稿可能キャプションを取得。
    空きが無い/フラグOFF/失敗のときは候補を作らない（has_candidate=false → publish はスキップ）。
    ★通常の review/service ローテとシャッフルバッグは乱さない（candidate に spot:true）。
    """
    if config.SPOT_SNS != "on":
        print("[SPOT] SPOT_SNS がOFFのためスキップ。")
        _set_output("has_candidate", "false")
        return
    if not config.SPOT_ANNOUNCE_URL:
        print("[SPOT] SPOT_ANNOUNCE_URL 未設定のためスキップ。")
        _set_output("has_candidate", "false")
        return

    import requests
    try:
        resp = requests.get(config.SPOT_ANNOUNCE_URL, timeout=30)
        data = resp.json() if resp.status_code < 400 else {}
    except Exception as e:  # ネットワーク等は「告知なし」に倒す（fail-closed）
        print(f"[SPOT] 取得失敗のためスキップ: {e}")
        _set_output("has_candidate", "false")
        return

    content = data.get("content") if data.get("available") else None
    if not content or not content.get("caption"):
        print("[SPOT] 空きが無い/告知なしのためスキップ。")
        _set_output("has_candidate", "false")
        return

    caption = content["caption"]
    hashtags = content.get("hashtagsHint") or []
    if hashtags:
        caption = caption + "\n\n" + " ".join(hashtags)

    photo, image_url = photo_picker.pick_photo(preferred_tags=["service", "treatment", "ambience"])
    candidate = {
        "post_type": "spot",
        "spot": True,
        "photo_file": photo["file"],
        "image_url": image_url,
        "caption": caption,
        "review_key": None,
    }
    _save_json(config.CANDIDATE_PATH, candidate)
    _write_summary(candidate)
    _notify_line(candidate)
    _set_output("has_candidate", "true")
    print(f"[SPOT] 候補を作成しました: {candidate['photo_file']}")


def prepare_gbp():
    """GBP（Google Business Profile）投稿候補を作る（既定OFF・GBP_POST=on のときだけ）。
    予約バックエンドの /api/spot-announcement?channel=gbp から投稿文（summary + CTA）を取得。
    空きが無い/フラグOFF/失敗のときは候補を作らない（has_candidate=false）。写真は不要（テキスト投稿）。"""
    if config.GBP_POST != "on":
        print("[GBP] GBP_POST がOFFのためスキップ。")
        _set_output("has_candidate", "false")
        return
    if not config.GBP_ANNOUNCE_URL:
        print("[GBP] GBP_ANNOUNCE_URL 未設定のためスキップ。")
        _set_output("has_candidate", "false")
        return

    import requests
    try:
        resp = requests.get(config.GBP_ANNOUNCE_URL, timeout=30)
        data = resp.json() if resp.status_code < 400 else {}
    except Exception as e:
        print(f"[GBP] 取得失敗のためスキップ: {e}")
        _set_output("has_candidate", "false")
        return

    content = data.get("content") if data.get("available") else None
    if not content:
        print("[GBP] 空きが無い/告知なしのためスキップ。")
        _set_output("has_candidate", "false")
        return

    summary = content.get("summary_en") if config.GBP_LANG == "en" else content.get("summary_ja")
    summary = summary or content.get("summary_en") or content.get("summary_ja")
    if not summary:
        print("[GBP] summary が無いためスキップ。")
        _set_output("has_candidate", "false")
        return

    candidate = {
        "channel": "gbp",
        "summary": summary,
        "cta_url": (content.get("cta") or {}).get("url"),
        "topic_type": content.get("topicType", "OFFER"),
    }
    _save_json(config.GBP_CANDIDATE_PATH, candidate)
    md = f"## 📍 GBP投稿候補（承認待ち）\n\n**topicType:** {candidate['topic_type']}\n\n**本文:**\n\n```\n{summary}\n```\n\n**CTA:** {candidate['cta_url']}\n"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)
    _set_output("has_candidate", "true")
    print("[GBP] 候補を作成しました。")


def publish_gbp():
    import gbp
    candidate = _load_json(config.GBP_CANDIDATE_PATH, None)
    if not candidate:
        raise SystemExit("[GBP PUBLISH ERROR] gbp_candidate.json がありません。")
    name = gbp.post_local_post(candidate["summary"], candidate.get("cta_url"), candidate.get("topic_type", "OFFER"))
    print(f"[GBP PUBLISH] 投稿成功 name={name}")


def publish():
    import instagram
    candidate = _load_json(config.CANDIDATE_PATH, None)
    if not candidate:
        raise SystemExit("[PUBLISH ERROR] candidate.json がありません。")

    media_id = instagram.post_image(candidate["image_url"], candidate["caption"])
    print(f"[PUBLISH] 投稿成功 media_id={media_id}")

    # スポット告知は通常ローテ/シャッフルバッグを乱さない（プロモは自由に再掲可）。
    if candidate.get("spot"):
        print("[PUBLISH] spot promo posted; rotation/shuffle state untouched.")
        return

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
    elif mode == "prepare-spot":
        prepare_spot()
    elif mode == "prepare-gbp":
        prepare_gbp()
    elif mode == "publish-gbp":
        publish_gbp()
    elif mode == "publish":
        publish()
    else:
        raise SystemExit("使い方: python src/main.py [prepare|prepare-spot|prepare-gbp|publish|publish-gbp]")
