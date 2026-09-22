# CORAN Instagram 自動投稿（GitHub Actions版）

z.com を完全に捨て、**コードも画像も GitHub** で動かす自動投稿システム。
@coranboutiquespa（B2C）向け。

## このシステムが解決すること
| 課題 | 解決 |
|---|---|
| z.com依存・中が見えない | GitHub上で完結。コードもログも可視化 |
| 同じ写真の使い回し | **シャッフルバッグ方式**：全部使い切るまで再登場させない |
| 写真と文章のミスマッチ | タグ一致で選択 |
| 週4回固定10:00 | **週2回（火19:00 / 金11:00）**に分散 |
| 承認ゲートが無い | **GitHub Environments の必須レビュアー**で投稿前承認 |
| トークンのサイレント切れ | 月1の自動更新ワークフロー |
| 失敗に気づけない | Actions が失敗時に自動でメール通知 |

## 仕組み
```
火/金 cron → prepare（写真を選ぶ → CORAN Frame で 4:5 のブランド画像を作る → 文章を作る）
          → 生成画像を main へコミット（Instagram は公開URLから画像を取りにくるため）
          → 🚦承認ゲート（あなたが完成画を見てOK）→ publish（投稿）→ state更新
```

## CORAN Frame（画像のブランド化・2026-09-20〜）

素材をそのまま投げず、**4:5（1080×1350）の「CORANの画」**に変換してから投稿する。

| 直したこと | 中身 |
|---|---|
| 比率 | 素材の約9割が 16:9。IGの4:5グリッドで**横の約55%が切られ**、占有面積が約1/1.8だった → 4:5固定 |
| トーン | 彩度−16%・影にブラウン・ハイライトにゴールド。出典がバラバラでも一本の作品に見える |
| リズム | `service(A) → sanctuary(C) → service(A) → review(B)` を巡回。3列グリッドで明暗が市松に並ぶ |
| 自社性 | Webの既存デザインシステム（Gold `#C9A96E`／Brown `#4F3834`／Cream `#FAF6F0`／Playfair + Noto Sans JP）をSNSへ移植 |

**レイアウト3型** … A エディトリアル（写真全面）／B お客様の声（クリーム地・アーチ窓・★5）／C サンクチュアリ（深ブラウン地・実店舗を切らずに額装）

- 実装 … `src/brandkit.py`（描画）・`src/brandimage.py`（組み方と一行の決定）
- 見出し … Claude が英1行・和1行を生成。APIが無い/失敗したらカテゴリ別テンプレ（写真ごとに文言が変わる）
- 生成物 … `images/generated/` に**最新1枚だけ**残る（承認待ちは常に最新1件のため）
- 外部API・追加費用なし（Pillow + numpy のみ）。**実在しない部屋やスタッフのAI生成はしない**
- 画像は必ず CORAN Frame を通す（2026-09-22 社長指示で `BRAND_IMAGE=off`＝素材そのままの経路は撤去）。作れなければその回は候補なし

```bash
python tools/selftest_brand.py    # セルフテスト（ネットワーク不要・48項目）
python tools/selftest_approval.py # スマホ承認の検証（署名・締切・価格語・画像差し替え）
python tools/selftest_intake.py   # 写真取り込み自動マージの門番のセルフテスト
python tools/preview_grid.py      # 9枚のグリッド見本を .preview/ に出す
python tools/build_manifest.py    # manifest.json を実体から作り直す（除外理由もここ）
```

**素材の取捨は `tools/build_manifest.py` の EXCLUDE / AROMA_KEEP が単一の情報源**。
理由をコメントで必ず残すこと（何をなぜ外したかが後から分かるように）。

## スマホ承認（Claude の非公開ページ・2026-09-22〜）

社長がスマホの Claude アプリで「画像と本文の確認・本文の修正・承認／見送り」をする。1投稿ずつ。承認が無い回は投稿しない。

```
投稿の24時間前  ルーティン: make-candidate → 画像を ig-queue の queue/<slot>/image.jpg へ push
                             本文の下書き・画像の断片は確認ページの db（posts/<slot>）へ（repo には置かない）
〜締切          社長: 確認ページで本文を直して「承認」→ 端末の鍵で署名（画像・本文・枠・時刻）
締切（2時間前）  ルーティン: db を読み relay → queue/<slot>/approval.json を ig-queue へ push
投稿枠          post.yml: check（署名・ハッシュ・締切・価格語）→ publish（production）→ state を main へ
```

- 検証は `src/approval.py`。公開鍵は Actions 変数 `IG_APPROVER_PUBKEYS`（未設定なら投稿しない）。
- IG に渡す画像 URL は ig-queue の commit に固定（検証したバイト列と IG が取るバイト列が同じ）。
- 確認ページの元は `approval-page/ig-approval.html`。署名の形・価格語のリストは `src/approval.py` と同じにする（selftest が照合）。
- `python tools/selftest_approval.py`（ネットワーク不要・偽造／締切切れ／価格語／画像差し替えで投稿しないことを確かめる）。
- 端末の登録: ページで「この端末を登録」→ 社長の画面に出た指紋（16桁）と、repo の Actions 変数 `IG_APPROVER_PUBKEYS` に入れる公開鍵の指紋が一致することを**社長自身が見て**確かめる（db の値をそのまま写さない）。変数は環境ではなく repo に置く。
- 必須レビュアーが残っている間は、投稿しない実行を GitHub で Reject する（放置すると次の枠の実行を塞ぐ）。
- 残る穴（2026-09-22 gray 第二レビュー）:
  - a. main に push できる者（ig-queue に push するルーティンの資格情報がワークフロー変更権を持つ場合を含む）は post.yml 自体を書き換えられる。
  - b. IG トークンと `GH_PAT`（Secrets 書き込み権）が repo の Secret。ブランチに置いたワークフローから使え、`IG_APPROVER_PUBKEYS` の差し替えもできうる。
  - c. ページを再公開できる者（社長の Claude セッション＝AI を含む）が悪意あるページを載せ、社長が開くと鍵を使われうる。Artifact 同士が同じ出どころなら別の Artifact からも使われうる（実機で未確認）。
  - d. Artifact db には書き手の刻印が無く、ArtifactData は owner として書ける。だから db の値ではなく端末の署名を正にしている。
  - e. 「取り消して直す」を押しても、取り消す前の署名は締切前なら有効のまま（中継されれば通る）。
  - a・b を閉じるには main のルールセット保護と、トークン類を「main だけが使える production 環境の Secret」に移す設定が要る（決裁）。
- スポット告知（post-spot.yml）の IG 投稿は、署名の無い経路なのでスマホ承認に載せ替えるまで停止（`prepare_spot` が候補を作らない）。

## 写真の月次取り込み PR の自動マージ（2026-09-22〜）

`photo-intake-automerge.yml`。ブランチ `routine/photo-intake-*` だけが対象（fork の PR は対象外）。

- `pull_request_target` で動き、コードは main から checkout する。PR のブランチにあるコードは実行しない。PR から取り出すのは門番が通した画像と manifest だけ。
- 門番 `tools/intake_guard.py`（main の版）：既存カテゴリへの画像（通常ファイル）の追加と `images/manifest.json` の変更だけを通す。コード・ワークフロー・`images/generated`・削除・上書き・新カテゴリ・シンボリックリンク・サブモジュールを含む PR は自動マージしない＝社長マージ。
- manifest は main の `build_manifest.py` で作り直した結果と一致すること。セルフテスト（main のコード × PR の画像）が通ること。
- マージは squash・`--match-head-commit`（検査した commit だけ）。
- 限界：ブランチ保護が無いので、書き込み権を持つ人は main に直接 push できる。この門番は「意図しない変更が混ざったまま自動マージされる」のを防ぐもの。
- aroma への追加（`AROMA_KEEP_FILES` の追記）や新カテゴリはコードの変更を含むので、自動マージされない。

## セットアップ（一度だけ）

### 1. GitHubリポジトリを作る
このフォルダを **private** リポジトリとして push する。

### 2. 写真を入れる
`images/` に実際の写真を入れ、`images/manifest.json` に1枚ずつ登録する。
- `tags`: `service` `treatment` `facial` `massage` `ambience` `review` `guest` など
- 画像は **4:5 推奨**（フィードで最も大きく表示される）
- ファイル名は英数字（日本語名は raw URL で文字化けの恐れ）

### 3. Secrets を登録（Settings → Secrets and variables → Actions）
| Secret | 内容 | 必須 |
|---|---|---|
| `IG_USER_ID` | Instagramビジネスアカウント ID | ✅ |
| `IG_ACCESS_TOKEN` | 長期アクセストークン | ✅ |
| `IMAGE_BASE_URL` | `https://raw.githubusercontent.com/<owner>/<repo>/main/images` | ✅ |
| `GOOGLE_PLACES_API_KEY` | レビュー投稿を使う場合 | 任意 |
| `GOOGLE_PLACE_ID` | CORANのPlace ID | 任意 |
| `LINE_CHANNEL_ACCESS_TOKEN` | 候補をLINEに飛ばす場合 | 任意 |
| `LINE_TO_USER_ID` | 送信先のLINE userId | 任意 |
| `FB_APP_ID` / `FB_APP_SECRET` | トークン自動更新用 | 任意 |
| `GH_PAT` | トークン自動更新用（Secrets書込権のPAT） | 任意 |

### 4. 承認ゲートを設定（最重要）
Settings → Environments → **New environment** → 名前 `production`
→ **Required reviewers** にあなた自身を追加 → Save

これで `publish` ジョブは、あなたが「Review deployments → Approve」するまで止まる。
却下すれば投稿されない。GitHubモバイルアプリからも承認可能。

### 5. テスト実行
Actions → CORAN Instagram Auto-Post → **Run workflow**（手動実行）
→ prepare の実行サマリで写真+文章を確認 → 承認 → 投稿される。

## 投稿スケジュール変更
`.github/workflows/post.yml` の `cron` を編集（UTC基準・ICTは+7時間）。

## 運用メモ
- **承認待ちは常に最新の1件だけ**：次の候補が作られると、承認されなかった古い実行は自動で取り消される（`post.yml` の `concurrency`）。候補ファイルの保存は7日＝それより古い実行を承認しても投稿できない。
- **承認依頼の通知**：`LINE_CHANNEL_ACCESS_TOKEN` と `LINE_TO_USER_ID` を Secrets に入れると、候補の写真・文章・承認画面へのリンクが LINE に届く。送信結果（送信済／未設定／失敗）は prepare の実行サマリに残る。未設定でも GitHub から必須レビュアー宛のメール／モバイルアプリ通知は届く。
- **60日コミットが無いと GitHub は定期実行を黙って無効化する**：承認が続けば state のコミットが入るので起きない。止まっていたら Actions 画面の Enable workflow。
- 写真在庫が少ないと巡が早く一周する。**最低15〜20枚**あると体感品質が上がる。
- キャプションを将来 Claude API 生成に切り替えると、テンプレ感がさらに消える（別フェーズ）。
- Reels連携は未実装（最大の伸びしろ。次フェーズ候補）。
