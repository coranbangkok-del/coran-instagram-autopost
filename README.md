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
火/金 cron → prepare（写真+文章を作成）→ 🚦承認ゲート（あなたがOK）→ publish（投稿）→ state更新
```

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
- 写真在庫が少ないと巡が早く一周する。**最低15〜20枚**あると体感品質が上がる。
- キャプションを将来 Claude API 生成に切り替えると、テンプレ感がさらに消える（別フェーズ）。
- Reels連携は未実装（最大の伸びしろ。次フェーズ候補）。
