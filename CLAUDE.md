# coran-instagram-autopost（@coranboutiquespa IG 自動投稿・パープル主管）

## 動かし方（この Mac）
- 素の python3 の Pillow は x86 で落ちる。ローカルは必ず
  `~/.local/bin/uv run --python 3.12 --with pillow --with numpy --with requests --with anthropic python <script>`
- `src/config.py` は import 時に IG_USER_ID／IG_ACCESS_TOKEN／IMAGE_BASE_URL を必須にする。ローカルはダミー値で動かす（`tools/selftest_brand.py` は自分でダミーを入れる）。本物のトークンをローカルに置かない。
- 検証は `tools/selftest_brand.py`（ネットワーク・API 不要。全 PASS が条件）。見本は `tools/preview_grid.py`（`.preview/` は ignore 済）。
- セルフテストは `images/generated/` に `*-_tiny.jpg` を残す。コミット前に消す（CI の prepare は `git add -A images/generated` するので混ざると公開される）。
- `python src/main.py prepare|publish|publish-approved` をローカルで本物の Secrets 付きで叩かない（publish＝IG へ実投稿、prepare＝LINE 送信の可能性）。`make-candidate`／`relay` は送信しない。
- スマホ承認の検証は `tools/selftest_approval.py`（`--with cryptography` を足す）。

## CI（.github/workflows）
- `post.yml` 火 19:00／金 11:00 BKK（2026-09-22〜 スマホ承認・ブランチ ops/ig-mobile-approval-20260922 で未マージ）。check（ig-queue の署名つき承認を検証）→ 通れば publish（`environment: production`）→ `state/` を main へ bot コミット。候補づくりと中継はパープルのルーティン（`main.py make-candidate`／`relay`）。旧 prepare→publish は post-spot.yml だけが使う。
- `post-spot.yml`（09:00）・`post-gbp.yml`（09:10）は Secrets の `SPOT_SNS`／`GBP_POST` が "on" のときだけ候補を作る。GBP の実投稿は GAS 側（coran-review-bot の SpotPromoPoster）で、ここの GBP ジョブは空実行の見込み。
- `refresh-token.yml` 毎月1日 03:00 UTC。長期トークン60日。最後の成功 9/1＝10/31 頃失効。次回 10/1 の成功確認＝r35。
- GitHub cron は2〜5時間遅れる（spot は 09:00 予定が 14 時台に走った実績）。時刻が要る告知はここに載せない。
- 実行履歴は匿名 API で読める（Chrome 不要）:
  `curl -s "https://api.github.com/repos/coranbangkok-del/coran-instagram-autopost/actions/workflows/post.yml/runs?per_page=5"`

## 実際に起きた事故と落とし穴
- 6/29〜9/17 公開0。候補が承認されず30日失効×15 → state コミットが途絶え → 60日無活動で GitHub が schedule を黙って Disabled（9/1 頃）。Enable だけでは再発する。対策として prepare が毎回生成画像をコミットする設計にした（CI 上での実績は 9/22 時点で未実測・r92）。スマホ承認に移ると main へのコミットは投稿した回だけになる。ig-queue への push が「活動」に数えられるかは未確認＝見送りが続くときは注意。
- 承認待ちの古い run は「作られた時点のコード」の候補。機能マージ後に古い run を承認すると旧仕様の画が出る（CORAN Frame 後の run #23 で踏みかけた）。承認前に上の API で `head_sha` と作成日時を確かめる。`concurrency` は post.yml にだけあり、導入前の run と `post-spot.yml`（concurrency なし・承認待ちが複数残っている）には効かない。
- 候補 artifact は7日で消える。それより古い run を承認しても publish は失敗する。
- IG は公開 URL（raw.githubusercontent.com）から画像を取る。repo を非公開にすると投稿が丸ごと失敗する。旧経路は main の `IMAGE_BASE_URL`、スマホ承認は ig-queue の commit を固定した URL（検証したバイト列＝IG が取るバイト列）。
- publish の push は `git pull --rebase` 後でないと prepare の bot コミットと衝突する。ワークフローの push 手順を崩さない。
- `photo_picker.pick_photo` の preferred_tags は「どれか1つ一致」。sanctuary に `ambience` を足すと施術写真が全部当たる（sanctuary=`["sanctuary"]`／review=`["interior"]` のまま）。
- お客様の声（B 型）は `reviews/curated.json` が `[]` で Places キーも無いため、構造上一度も出ていない（r93・ピンク）。入れるなら★5・40字以上・個人名と他店名なし（curated.json にはコードの閾値が掛からないので人が守る）。
- Actions 画面で Cancel run を browser_batch でまとめてクリックすると自動モードに拒否され、そのタブが操作不能になる。1件ずつスクショを挟む。

## 素材と画像の決まり
- manifest の取捨は `tools/build_manifest.py` の EXCLUDE／AROMA_KEEP が唯一の正。manifest.json を手で直さず、理由コメント付きでここを直して再生成。
- Dream Hotel 時代の写真（`gallery_dream_*`・`SOtraveler-DreamBKK-*`・`*_dream_middlesize`）は使わない。価格を焼き込んだ画像・透かし入り素材は入れない。
- 実在しない部屋・スタッフの AI 画像生成はしない（社長方針）。ロゴは現行のみ。
- 新しい写真は毎月1日の取り込み（`~/dev/team-takuro/tools/purple_photo_intake.py`・r107）経由で、ブランチ→PR→社長マージで入れる。スクリプト自体は候補を `team-takuro/purple/photo-intake/YYYY-MM/` に出すだけ。

## 止める条件（GO-2＝決裁箱へ）
- Actions の Approve／Run workflow／Enable・Disable、IG・LINE・GBP への実送信。
- Secrets の追加・変更（LINE 通知の2つ、GBP_POST／SPOT_SNS の "on" 化を含む）とトークン操作。
- main への push とマージ。変更は作業ブランチを push し、PR 作成 URL を報告。反映済と書くのは `git fetch` で origin/main との差分0を見てから。

## 関連リマインダー
r34 初回 Approve／r35 トークン 10/1／r92 CORAN Frame 初回実行の実測／r93 curated.json／r94 SNS 多チャネル Phase0／r107 写真の月次取り込み
