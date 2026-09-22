"""
エントリポイント。2モードで動く。

  python src/main.py prepare   … 投稿候補（写真+文章）を作って candidate.json に出力 + 承認用サマリ表示
  python src/main.py publish   … 承認後に実際に Instagram へ投稿し、使用済み状態を更新
  python src/main.py build-calendar [YYYY-MM] … 翌月の投稿カレンダーと画像を作る（送信なし）
  python src/main.py check-calendar YYYY-MM   … カレンダーの検証だけ
  python src/main.py publish-calendar         … 承認済みカレンダーの今日の1件を公開（CALENDAR_MODE=on）

GitHub Actions では prepare → (人間の承認ゲート) → publish の順で2ジョブに分かれる。
"""
import json
import os
import sys

import config
import photo_picker
import caption as caption_mod
import caption_ai
import brandimage
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


# 投稿の並び。3種を巡回させることで、プロフィールのグリッドで
#   写真(A) → 実店舗の深ブラウン(C) → 写真(A) → お客様の声のクリーム(B)
# と明暗が交互に並び、「肌色一色の壁」にならない。
POST_CYCLE = ["service", "sanctuary", "service", "review"]


def _next_post_type():
    """次の投稿種別と、その巡回位置を返す。状態は rotation.json。"""
    state = _load_json(config.ROTATION_STATE_PATH, {"last": "review"})
    seq = state.get("seq")
    if seq is None:  # 旧形式（last だけ）からの移行
        last = state.get("last")
        seq = POST_CYCLE.index(last) if last in POST_CYCLE else -1
    nxt = (int(seq) + 1) % len(POST_CYCLE)
    return POST_CYCLE[nxt], nxt


def _write_summary(candidate):
    """GitHub Actions の実行サマリに投稿候補を表示（承認者が中身を見られる）。"""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    layout = candidate.get("layout")
    lname = {"A": "A エディトリアル（写真）", "B": "B お客様の声（クリーム地）",
             "C": "C サンクチュアリ（深ブラウン地）"}.get(layout, "—（素材のまま）")
    md = (
        f"## 📣 投稿候補（承認待ち）\n\n"
        f"**種別:** {candidate['post_type']}　／　**組み方:** {lname}\n\n"
        f"**素材:** `{candidate['photo_file']}`"
        + (f"　→　**生成:** `{candidate['generated_file']}`" if candidate.get("generated_file") else "")
        + "\n\n"
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
    post_type, seq = _next_post_type()
    review = None

    if post_type == "review":
        good = reviews_mod.fetch_reviews()
        used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
        review = reviews_mod.pick_unused_review(good, set(used_state.get("reviews", [])))
        if not review:
            # 引用できる声が無いときは空の吹き出しを出さず、実店舗の回へ振り替える
            print("[PREPARE] 使えるレビューが無いため sanctuary 投稿に切り替えます。")
            post_type = "sanctuary"

    # 注意: "ambience" は施術写真にも付いているので sanctuary の条件に入れない
    #       （入れると実店舗以外が選ばれ、C レイアウトの意味が無くなる）
    PREFER = {
        "review":    ["interior"],
        "sanctuary": ["sanctuary"],
        "service":   ["service", "treatment", "ambience"],
    }
    photo, source_url = photo_picker.pick_photo(preferred_tags=PREFER[post_type])

    caption_kind = "review" if post_type == "review" else "service"
    text = caption_ai.build_caption(caption_kind, photo, review)

    image_url, generated_file, layout = source_url, None, None
    if config.BRAND_IMAGE == "on":
        eyebrow = brandimage.meta_for(photo)[0]
        headline = caption_ai.build_image_headline(caption_kind, photo, review, eyebrow)
        url, rel, lay = brandimage.build(post_type, photo, review, headline)
        if url:
            image_url, generated_file, layout = url, rel, lay
        else:
            print("[PREPARE] ブランド画像を作れなかったため、素材をそのまま使います。")
    else:
        print("[PREPARE] BRAND_IMAGE=off のため素材をそのまま使います。")

    candidate = {
        "post_type": post_type,
        "seq": seq,
        "photo_file": photo["file"],
        "generated_file": generated_file,
        "layout": layout,
        "image_url": image_url,
        "caption": text,
        "review_key": (review["text"][:60] if review else None),
    }
    _save_json(config.CANDIDATE_PATH, candidate)
    _write_summary(candidate)
    _notify_line(candidate)
    print(f"[PREPARE] 候補を作成しました: {candidate['photo_file']} / {post_type} / layout={layout}")


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

    _save_json(config.ROTATION_STATE_PATH,
               {"last": candidate["post_type"], "seq": candidate.get("seq", 0)})


# ------------------------------------------------------------------ 月次カレンダー承認（S-2）
def _calendar_start_state(month):
    """翌月カレンダーの起点（巡回位置・この巡で使った写真）を決める。

    当月のカレンダーが main にあれば、その最後の回から続ける（当月の残りの投稿と写真が重ならない）。
    無ければ state/ の現在値から続ける。state/ には書かない。
    """
    import ig_calendar
    used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
    rot = _load_json(config.ROTATION_STATE_PATH, {"last": "review"})
    seq = rot.get("seq")
    if seq is None:
        last = rot.get("last")
        seq = POST_CYCLE.index(last) if last in POST_CYCLE else -1
    used_cycle = list(used_state.get("cycle", []))
    used_reviews = list(used_state.get("reviews", []))
    prev = ig_calendar.load_calendar(config.ROOT, ig_calendar.prev_month(month))
    if prev and prev.get("posts"):
        seq = prev["posts"][-1].get("seq", seq)
        used_cycle += [p.get("photo_file") for p in prev["posts"]]
        used_reviews += [p["review_key"] for p in prev["posts"] if p.get("review_key")]
    return int(seq), used_cycle, used_reviews


def build_calendar_cmd(month=None):
    """翌月（または指定月）のカレンダーと画像を作る。IG・LINE には何も送らない。"""
    import ig_calendar
    month = month or ig_calendar.next_month(ig_calendar.today_bkk())
    manifest = photo_picker.load_manifest()
    seq, used_cycle, used_reviews = _calendar_start_state(month)
    try:
        good = reviews_mod.fetch_reviews()
    except Exception as e:  # 声が取れなくても実店舗の回に振り替えて作る
        print(f"[CALENDAR] お客様の声を取得できませんでした（{type(e).__name__}）→ sanctuary に振り替え")
        good = []
    cal, notes = ig_calendar.build_calendar(
        month, config.ROOT, config.IMAGES_DIR, manifest, seq, used_cycle, good, used_reviews,
        caption_fn=caption_ai.build_caption,
        headline_fn=caption_ai.build_image_headline,
        render_fn=brandimage.render,
        cycle=POST_CYCLE,
    )
    errs = ig_calendar.validate_calendar(cal, month, config.IMAGES_DIR)
    if errs:
        raise SystemExit("[CALENDAR ERROR] " + " / ".join(errs))
    path = ig_calendar.write_calendar(config.ROOT, cal)
    md, prev = ig_calendar.write_preview(config.ROOT, config.IMAGES_DIR, cal)
    _set_output("month", month)
    _append_summary(
        f"## 🗓 IG 投稿カレンダー {month}（承認待ち）\n\n{len(cal['posts'])} 件。"
        f" PR をマージすると、この月の投稿の包括承認になります。\n\n"
        + "".join(f"- {p['date']} {p['weekday']} {p['post_type']} / {p['layout']} / `{p['photo_file']}`\n" for p in cal["posts"])
        + ("\n**差し替え:**\n" + "".join(f"- {n}\n" for n in notes) if notes else "")
    )
    print(f"[CALENDAR] {path} / {md} / {prev}")


def check_calendar_cmd(month):
    import ig_calendar
    cal = ig_calendar.load_calendar(config.ROOT, month)
    if cal is None:
        raise SystemExit(f"[CALENDAR ERROR] calendar/{month}.json がありません。")
    errs = ig_calendar.validate_calendar(cal, month, config.IMAGES_DIR)
    if errs:
        raise SystemExit("[CALENDAR ERROR] " + " / ".join(errs))
    print(f"[CALENDAR] {month}: {len(cal['posts'])} 件・問題なし")


def publish_calendar():
    """CALENDAR_MODE=on の公開。main にある承認済みカレンダーの今日の1件だけを、個別承認なしで出す。

    fail-closed: カレンダーが無い・今日の分が無い・中身が記録と違う → 投稿しない。
    「今日は投稿日でない」だけは正常終了、それ以外の停止はジョブを失敗させて気づけるようにする。
    """
    import ig_calendar
    import instagram

    today = ig_calendar.today_bkk()
    published = _load_json(config.CALENDAR_PUBLISHED_PATH, {"ids": []})
    entry, month, reason = ig_calendar.resolve_post(
        config.ROOT, config.IMAGES_DIR, today, published.get("ids", []))
    if entry is None:
        _append_summary(f"## 🗓 カレンダー投稿: 公開しない\n\n今日（BKK）: {today.isoformat()}\n\n理由: {reason}\n")
        if reason == "no-post-today" or reason.startswith("already-published"):
            return
        raise SystemExit(f"[CALENDAR] 公開を止めました（fail-closed）: {reason}")

    candidate = ig_calendar.candidate_from_entry(entry, config.IMAGE_BASE_URL)
    ok, why = ig_calendar.verify_candidate(candidate, entry, month, config.IMAGES_DIR, config.IMAGE_BASE_URL)
    if not ok:
        raise SystemExit(f"[CALENDAR] 公開を止めました（fail-closed）: {why}")
    _write_summary(candidate)
    _append_summary(f"\n承認: calendar/{month}.json（{reason}）\n")

    media_id = instagram.post_image(candidate["image_url"], candidate["caption"])
    print(f"[PUBLISH] 投稿成功 media_id={media_id} calendar_id={entry['id']}")

    ids = list(published.get("ids", []))
    ids.append(entry["id"])
    _save_json(config.CALENDAR_PUBLISHED_PATH, {"ids": ids[-120:]})

    # 従来経路に戻したときに続きから巡回できるよう、写真・声・巡回位置も同じ形で更新する
    manifest = photo_picker.load_manifest()
    photo = next((p for p in manifest if p["file"] == candidate["photo_file"]), {"file": candidate["photo_file"]})
    photo_picker.mark_used(photo)
    if candidate.get("review_key"):
        used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
        used_state.setdefault("reviews", []).append(candidate["review_key"])
        _save_json(config.USED_STATE_PATH, used_state)
    _save_json(config.ROTATION_STATE_PATH,
               {"last": candidate["post_type"], "seq": candidate.get("seq", 0)})


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
    elif mode == "build-calendar":
        build_calendar_cmd(sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None)
    elif mode == "check-calendar":
        check_calendar_cmd(sys.argv[2].strip())
    elif mode == "publish-calendar":
        publish_calendar()
    else:
        raise SystemExit("使い方: python src/main.py [prepare|prepare-spot|prepare-gbp|publish|publish-gbp"
                         "|build-calendar [YYYY-MM]|check-calendar YYYY-MM|publish-calendar]")
