# SETUP — laifu-ig-poster

一度やれば、あとは push とキュー承認だけで回る。実投稿が始まるのは **Secrets を入れて、キューの行を承認（status空）にしてから**。

## 0. 前提（IG 側の状態）

- [ ] **@laifu_japanese がプロアカウント（ビジネス or クリエイター）**
- [ ] その IG が **Facebook ページに連携**されている
- [ ] そのページが **Laifu広告と同じ Meta ビジネスポートフォリオ**に入っている
- [ ] Meta 開発者アプリ（既存の広告用アプリでOK）に **Instagram Graph API** を追加、権限 `instagram_content_publish` `instagram_basic` `pages_read_engagement`

> 自分のアカウントで自分の投稿を出すだけなら、アプリ審査なしでも開発者ロールのユーザーで動く。

## 1. 必要な値を取る

- **IG_USER_ID**: `GET /me/accounts` → ページ → `GET /{page-id}?fields=instagram_business_account` で取得
- **IG_TOKEN**: 長期ユーザートークン（fb_exchange_token で60日）。または恒久Pageトークン
- **FB_APP_ID / FB_APP_SECRET**: Meta アプリ設定から（トークン自動更新に使う）

Graph API Explorer で↑を発行するのが早い。

## 2. GitHub リポジトリを作る

このフォルダ（`04-marketing-department/laifu-ig-poster/`）を独立リポジトリとして push:

```bash
cd 04-marketing-department/laifu-ig-poster
git init && git add . && git commit -m "init laifu ig poster"
gh repo create laifu-ig-poster --private --source=. --push
```

## 3. Secrets を登録

repo の Settings → Secrets and variables → Actions:

| 種別 | 名前 | 中身 |
|---|---|---|
| Secret | `IG_USER_ID` | IG ビジネスアカウント ID |
| Secret | `IG_TOKEN` | 長期トークン |
| Secret | `FB_APP_ID` | Meta アプリ ID（トークン更新用） |
| Secret | `FB_APP_SECRET` | Meta アプリシークレット（同上） |
| Secret | `GH_PAT` | `secrets:write` 権限つき PAT（トークン更新でSecret上書き用） |
| Variable | `PUBLIC_BASE_URL` | 任意。未設定なら repo の raw URL を自動使用 |

> **恒久Pageトークン**を使うなら `FB_APP_ID/SECRET/GH_PAT` と `refresh-token.yml` は不要（ワークフロー無効化でOK）。

## 4. 本番前チェック（超重要）

まず **Actions → Post Laifu carousel → Run workflow → dry_run = 1** で空打ち。
ログに `image_url` と `caption` が正しく出て、URL をブラウザで開いて画像が表示されれば準備OK。
（raw URL は repo が private だと開けない → その場合は public repo か Supabase 公開バケットに）

## 5. 投稿を承認して回す

`drafts/YYYY-MM-queue.csv` の出したい行の `status` を **空欄**に（`draft`→空）。
火・金 21:00 JST に最上段から1本ずつ自動投稿。急ぎは `Run workflow`（dry_run=0）で即時。

## トラブル時

- `(#10) ... permission`: 権限不足 → `instagram_content_publish` を確認
- `media ... not ready`: コンテナ処理待ち → スクリプトが FINISHED を待つので通常は自動解消
- 画像が出ない: `PUBLIC_BASE_URL` か repo の公開設定を確認（IG は公開URLしか取れない）
