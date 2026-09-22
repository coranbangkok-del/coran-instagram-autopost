"""
エントリポイント。2モードで動く。

  通常投稿（2026-09-22〜 スマホ承認）
  python src/main.py make-candidate --slot YYYYMMDD-HHMM --out DIR  … ルーティンが候補を作る（送信なし）
  python src/main.py relay --doc post.json --queue-root DIR          … 署名つき承認を ig-queue 用に書く
  python src/main.py publish-approved --queue-root DIR --queue-sha SHA [--dry-run]
                                                                     … post.yml。検証に通ったときだけ投稿

  旧経路（スポット告知 post-spot.yml が使う・既定 OFF）
  python src/main.py prepare / publish
"""
import json
import os
import re
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

    # 画像は必ず CORAN Frame を通す（2026-09-22 社長指示）。作れなければ候補を作らない。
    eyebrow = brandimage.meta_for(photo)[0]
    headline = caption_ai.build_image_headline(caption_kind, photo, review, eyebrow)
    image_url, generated_file, layout = brandimage.build(post_type, photo, review, headline)
    if not image_url:
        raise SystemExit("[PREPARE] CORAN Frame の画像を作れなかったため、この回の候補は作りません。")

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
    # 2026-09-22〜 IG の投稿は「社長の端末の署名つき承認」がある経路（publish-approved）だけにする。
    # スポット告知の旧経路（production の Approve だけが関門）は、スマホ承認に載せ替えるまで止める。
    print("[SPOT] スマホ承認の経路に載せ替えるまで停止中（署名の無い投稿経路は使わない）。")
    _set_output("has_candidate", "false")
    return
    if config.SPOT_SNS != "on":  # noqa: 以下は載せ替え時の参考として残す（到達しない）
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

    photo, _source_url = photo_picker.pick_photo(preferred_tags=["service", "treatment", "ambience"])
    # スポット告知も素材そのままは出さない（CORAN Frame 必須）。作れなければ告知なし。
    image_url, generated_file, layout = brandimage.build("service", photo, None, None)
    if not image_url:
        print("[SPOT] CORAN Frame の画像を作れなかったためスキップ。")
        _set_output("has_candidate", "false")
        return
    candidate = {
        "post_type": "spot",
        "spot": True,
        "photo_file": photo["file"],
        "generated_file": generated_file,
        "layout": layout,
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


# =====================================================================
# スマホ承認（Claude の非公開 Artifact）経路  2026-09-22〜
#   make-candidate   … ルーティンが候補（画像＋本文の下書き）を作る。IG には何も送らない
#   relay            … ルーティンが db の署名つき承認を queue/<slot>/approval.json にする
#   publish-approved … post.yml。署名つき承認を検証し、通ったときだけ投稿する
# =====================================================================
import approval  # noqa: E402

CHUNK_CHARS = 180_000   # db の1文書は 256KiB まで。画像の base64 をこの長さで分ける


def make_candidate(slot, out_dir, caption_file=None, headline_en=None, headline_ja=None, trial=False):
    """投稿枠 slot の候補を out_dir に作る。戻り値は db に入れる候補文書（dict）。

    out_dir/image.jpg          … CORAN Frame の画像（ig-queue の queue/<slot>/image.jpg に置く）
    out_dir/post.json          … db の posts/<slot> に set する文書（本文の下書きを含む＝repo に置かない）
    out_dir/chunks/NN.json     … db の posts/<slot>/img/NN に set する画像の断片
    """
    import base64
    import datetime as dt

    slot_dt = approval.parse_slot(slot)
    if slot_dt is None:
        raise SystemExit(f"[CANDIDATE] 投稿枠ではありません: {slot}（火 19:00／金 11:00 BKK のみ）")

    post_type, seq = _next_post_type()
    review = None
    if post_type == "review":
        good = reviews_mod.fetch_reviews()
        used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
        review = reviews_mod.pick_unused_review(good, set(used_state.get("reviews", [])))
        if not review:
            print("[CANDIDATE] 使えるレビューが無いため sanctuary 投稿に切り替えます。")
            post_type = "sanctuary"
    PREFER = {"review": ["interior"], "sanctuary": ["sanctuary"],
              "service": ["service", "treatment", "ambience"]}
    photo, _src = photo_picker.pick_photo(preferred_tags=PREFER[post_type])
    caption_kind = "review" if post_type == "review" else "service"

    # 本文：ルーティン（Claude）が書いたものを優先。無ければ caption_ai（API かテンプレ）。
    if caption_file:
        with open(caption_file, encoding="utf-8") as f:
            text = approval.normalize_caption(f.read())
        bad = approval.banned_words(text)
        if bad:
            raise SystemExit(f"[CANDIDATE] 本文に価格・割引・販促の語があります: {bad}。書き直してください。")
    else:
        text = approval.normalize_caption(caption_ai.build_caption(caption_kind, photo, review))
        if approval.banned_words(text):
            print("[CANDIDATE] 生成本文に禁止語 → テンプレートに差し替え")
            text = approval.normalize_caption(caption_ai._fallback(caption_kind, photo, review))
        bad = approval.banned_words(text)
        if bad:
            raise SystemExit(f"[CANDIDATE] テンプレートにも禁止語: {bad}")

    if headline_en or headline_ja:
        headline = (headline_en or "", headline_ja or "")
    else:
        eyebrow = brandimage.meta_for(photo)[0]
        headline = caption_ai.build_image_headline(caption_kind, photo, review, eyebrow)

    # 画像は必ず CORAN Frame。失敗したら候補を作らない（素材そのままへは倒さない）。
    try:
        img, layout = brandimage.render(post_type, photo, review, headline)
    except Exception as e:
        raise SystemExit(f"[CANDIDATE] CORAN Frame の画像を作れませんでした: {type(e).__name__}: {e}")
    if img.size != approval.IMAGE_SIZE:
        raise SystemExit(f"[CANDIDATE] 画像の大きさが規定外: {img.size}")

    os.makedirs(os.path.join(out_dir, "chunks"), exist_ok=True)
    img_path = os.path.join(out_dir, "image.jpg")
    img.convert("RGB").save(img_path, "JPEG", quality=90, optimize=True, subsampling=1)
    data = open(img_path, "rb").read()
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [b64[i:i + CHUNK_CHARS] for i in range(0, len(b64), CHUNK_CHARS)]
    for i, c in enumerate(chunks):
        _save_json(os.path.join(out_dir, "chunks", f"{i:02d}.json"), {"i": i, "b64": c})

    now = dt.datetime.now(dt.timezone.utc)
    doc = {
        "slot": slot,
        "slot_at": slot_dt.isoformat(),
        "deadline": approval.deadline_of(slot_dt).isoformat(),
        "created_at": now.isoformat(timespec="seconds"),
        "status": "pending",
        "post_type": post_type,
        "seq": seq,
        "layout": layout,
        "photo_file": photo["file"],
        "review_key": (review["text"][:60] if review else None),
        "caption_draft": text,
        "image_sha256": approval.sha256_hex(data),
        "image_bytes": len(data),
        "image_chunks": len(chunks),
        "image_path": f"queue/{slot}/image.jpg",
    }
    if trial:
        doc["trial"] = True   # お試し（ページの操作確認用）。relay が必ず断る
    _save_json(os.path.join(out_dir, "post.json"), doc)
    print(f"[CANDIDATE] {slot} {post_type} layout={layout} {photo['file']} "
          f"image={len(data)//1024}KB chunks={len(chunks)} sha={doc['image_sha256'][:12]}")
    return doc


def relay(doc_path, queue_root, now=None):
    """db から読んだ posts/<slot> 文書を、ig-queue の承認記録にする。

    承認でない・締切後・本文の禁止語・画像の不一致なら何も書かない（戻り値 False）。
    署名はここでは（鍵があれば）確かめるだけ。最終の判定は post.yml の publish-approved。
    """
    import datetime as dt
    doc = _load_json(doc_path, None)
    if not isinstance(doc, dict) or not doc.get("slot"):
        print("[RELAY] 文書が読めません。")
        return False
    slot = doc["slot"]
    slot_dt = approval.parse_slot(slot)
    if slot_dt is None:
        print(f"[RELAY] 投稿枠ではありません: {slot}")
        return False
    if doc.get("trial"):
        print(f"[RELAY] {slot}: お試しの候補なので送りません")
        return False
    if doc.get("decision") != "approve":
        print(f"[RELAY] {slot}: 承認されていません（decision={doc.get('decision')}）→ 見送り")
        return False
    rec = approval.build_record(doc, f"queue/{slot}/image.jpg")
    img_file = os.path.join(queue_root, rec["image_path"])
    image_bytes = open(img_file, "rb").read() if os.path.exists(img_file) else None
    pub = approval.parse_pubkeys(config.IG_APPROVER_PUBKEYS)
    # 事前確認は「枠の時刻に投稿する」前提で行う（締切と署名時刻の関係を確かめる）
    ok, why = approval.verify(rec, pubkeys=pub, now=slot_dt, image_bytes=image_bytes,
                              posted_slots=_load_json(config.POSTED_SLOTS_PATH, []),
                              require_signature=bool(pub))
    now = now or dt.datetime.now(dt.timezone.utc)
    if not ok:
        print(f"[RELAY] {slot}: 送らない — {why}")
        return False
    out = os.path.join(queue_root, "queue", slot, "approval.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(approval.dumps(rec))
    print(f"[RELAY] {slot}: 承認記録を書きました（{why}）relayed_at={now.isoformat(timespec='seconds')}")
    return True


def publish_approved(queue_root, queue_sha, dry_run=False, now=None, post_fn=None, recent_fn=None):
    """post.yml から呼ぶ。いま投稿してよい枠の署名つき承認を検証し、通れば投稿する。

    戻り値: 投稿した（dry_run なら投稿できる）枠の id、無ければ None。
    承認が無い・検証に落ちたときは例外にせず None（＝その回は投稿なし）。
    """
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    if not re.fullmatch(r"[0-9a-f]{40}", queue_sha or ""):
        _append_summary("\n**投稿なし:** ig-queue の commit が特定できません。\n")
        _set_output("has_approval", "false")
        return None
    pub = approval.parse_pubkeys(config.IG_APPROVER_PUBKEYS)
    posted = _load_json(config.POSTED_SLOTS_PATH, [])
    reasons = []
    for slot_dt in approval.open_slots(now):
        slot = approval.slot_id(slot_dt)
        path = os.path.join(queue_root, "queue", slot, "approval.json")
        try:
            rec = _load_json(path, None) if os.path.exists(path) else None
        except (ValueError, UnicodeDecodeError):
            reasons.append(f"{slot}: 承認記録が壊れている")
            continue
        if rec is None:
            reasons.append(f"{slot}: 承認記録なし（社長の承認が無い／締切切れ）")
            continue
        if not isinstance(rec, dict):
            reasons.append(f"{slot}: 承認記録が JSON オブジェクトではない")
            continue
        expected = f"queue/{slot}/image.jpg"
        img_file = os.path.join(queue_root, expected)
        image_bytes = (open(img_file, "rb").read()
                       if rec.get("image_path") == expected and os.path.isfile(img_file) else None)
        ok, why = approval.verify(rec, pubkeys=pub, now=now, image_bytes=image_bytes, posted_slots=posted)
        if rec.get("slot") != slot:
            ok, why = False, "承認記録の slot が置き場所と違う"
        if not ok:
            reasons.append(f"{slot}: {why}")
            continue

        if dry_run:
            _append_summary(f"\n## 投稿できる承認あり: {slot}\n\n```\n{rec['caption']}\n```\n")
            _set_output("has_approval", "true")
            _set_output("slot", slot)
            return slot

        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            reasons.append(f"{slot}: GITHUB_REPOSITORY が無い")
            break
        # commit を固定した URL＝検証したバイト列と IG が取りに来るバイト列が同じ（差し替え不可）
        image_url = f"https://raw.githubusercontent.com/{repo}/{queue_sha}/{rec['image_path']}"
        if post_fn is None or recent_fn is None:
            import instagram
            post_fn = post_fn or instagram.post_image
            recent_fn = recent_fn or instagram.recent_captions
        # 二重投稿の最後の砦: state の push に失敗した後の再実行などに備え、IG 側の直近48時間に
        # 同じ本文があれば出さない。確かめられなければ（API の失敗）出さない。
        try:
            recent = recent_fn(hours=48)
        except Exception as e:
            reasons.append(f"{slot}: IG の直近の投稿を確かめられない（{type(e).__name__}）")
            break
        if approval.normalize_caption(rec["caption"]) in {approval.normalize_caption(c or "") for c in recent}:
            _save_json(config.POSTED_SLOTS_PATH, (posted + [slot])[-200:])
            reasons.append(f"{slot}: 同じ本文が直近48時間に IG に出ている（二重投稿防止・posted に記録）")
            break
        media_id = post_fn(image_url, rec["caption"])
        print(f"[PUBLISH] 投稿成功 slot={slot} media_id={media_id}")

        manifest = photo_picker.load_manifest()
        photo = next((p for p in manifest if p["file"] == rec["photo_file"]), {"file": rec["photo_file"]})
        photo_picker.mark_used(photo)
        if rec.get("review_key"):
            used_state = _load_json(config.USED_STATE_PATH, {"cycle": [], "history": [], "reviews": []})
            used_state.setdefault("reviews", []).append(rec["review_key"])
            _save_json(config.USED_STATE_PATH, used_state)
        _save_json(config.ROTATION_STATE_PATH, {"last": rec["post_type"], "seq": rec["seq"]})
        _save_json(config.POSTED_SLOTS_PATH, (posted + [slot])[-200:])
        _append_summary(f"\n## 投稿しました: {slot}\n")
        _set_output("has_approval", "true")
        return slot

    _append_summary("\n## 投稿なし（fail-closed）\n\n" + "\n".join(f"- {r}" for r in reasons or ["いま投稿してよい枠がありません"]) + "\n")
    _set_output("has_approval", "false")
    return None


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "make-candidate":
        make_candidate(_arg("--slot") or approval.slot_id(approval.next_slot()), _arg("--out", "candidate_out"),
                       caption_file=_arg("--caption-file"), headline_en=_arg("--headline-en"),
                       headline_ja=_arg("--headline-ja"), trial="--trial" in sys.argv)
        sys.exit(0)
    if mode == "relay":
        ok = relay(_arg("--doc"), _arg("--queue-root", "."))
        sys.exit(0 if ok else 3)
    if mode == "publish-approved":
        publish_approved(_arg("--queue-root", "_queue"), _arg("--queue-sha"), dry_run="--dry-run" in sys.argv)
        sys.exit(0)
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
        raise SystemExit("使い方: python src/main.py [make-candidate|relay|publish-approved|prepare|prepare-spot|prepare-gbp|publish|publish-gbp]")
