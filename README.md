# laifu-ig-poster

Laifu の Instagram カルーセルを **1日おきに1本、自動投稿**。月額 **$0**（Instagram Graph API + GitHub Actions 無料枠）。
NH の `nh-threads-poster` の骨組みを IG カルーセル用に移植したもの。

投稿先: **@laifu_japanese**（IG ビジネスアカウント）

## 仕組み

```
コンテンツ制作:  /laifu-carousel でスライド生成 → posts/<slug>/1.jpg..N.jpg + caption.md を push
キュー登録:      drafts/YYYY-MM-queue.csv に行を足す(status を空=承認 or draft=保留)
1日おき 21:00 JST: キュー最上段の未投稿を1本 → 子コンテナ→CAROUSEL→publish → posted_at 書き戻し commit
毎月1日:         長期トークンを自動リフレッシュ(約60日失効対策)
```

投稿は **FIFO**（CSV 上から順）。実際の公開は「あなたが承認した行」だけ。

## キュー CSV（`drafts/YYYY-MM-queue.csv`）

列: `date | time | slug | caption | status | posted_at`

- `date` / `time` … あなたがスケジュールを把握するための **表示用ラベル**（投稿選定には使わない）
- `slug` … `posts/<slug>/` に画像（`1.jpg,2.jpg,…` 数値順）または動画とキャプションがある
- `caption` … 空なら `posts/<slug>/caption.md` を使う
- `status` … `draft/hold/skip/保留/スキップ/下書き` はスキップ。**空欄＝承認**。
- `posted_at` … 投稿後に Actions が書き戻す。埋まってる行は投稿済み。

## カルーセルかリールかは posts/<slug>/ の中身で決まる

同じキュー・同じ cron のまま、**フォルダに動画を置けばリールになる**。CSV に列は足さない。

| `posts/<slug>/` の中身 | 投稿される形 |
|---|---|
| `1.jpg, 2.jpg, …` | カルーセル（1枚なら単一画像） |
| `reel.mp4`（+ 任意で `cover.jpg`） | **リール**（`share_to_feed=true` でフィードにも出る） |

- 動画は `.mp4` / `.mov`。**1フォルダ1本**（複数あると先頭だけ使い、警告を出す）
- `cover.jpg` は表紙。無ければ IG が先頭フレームから自動生成する。
  カルーセル側では `cover.jpg` を**スライドに混ぜない**ので、表紙だけ別画像にしたい時も安全
- 動画は IG 側の変換に数分かかる。画像は最大60秒待ちだが、**リールは最大10分**待つ

## 画像・動画の公開URL（重要）

IG Graph API は**ローカル画像を受け取れない**。各スライドは公開HTTPS URLが必須。
既定では **repo にコミットした画像を raw URL で配信**する:

```
image_url = PUBLIC_BASE_URL / posts/<slug>/<file>
例: https://raw.githubusercontent.com/<owner>/laifu-ig-poster/main/posts/nomikai/1.jpg
```

`PUBLIC_BASE_URL` は Actions が repo から自動生成（未設定時）。別の置き場（Supabase 公開バケット等）を
使うなら repo variable `PUBLIC_BASE_URL` を設定。

## ローカルで動作確認（ドライラン）

```bash
pip install -r requirements.txt
DRY_RUN=1 QUEUE_FILE=drafts/2026-07-queue.csv POSTS_DIR=posts \
PUBLIC_BASE_URL=https://raw.githubusercontent.com/<owner>/laifu-ig-poster/main \
python scripts/post_to_instagram.py
```

`status` が空の行が無ければ「投稿対象なし」で終わる（＝承認するまで投稿されない）。

## ファイル

- `scripts/post_to_instagram.py` … 投稿本体（単一画像 / 2〜10枚カルーセル / リール動画）
- `scripts/refresh_token.py` … 月次トークンリフレッシュ
- `.github/workflows/post-scheduled.yml` … cron `0 12 */2 * *` = **1日おき 21:00 JST**
  （手動実行＋ドライランも可）。⚠️ ここは長らく「火・金」と書かれていたが実体と違い、
  2026-08-22 に次の投稿日を読み違える原因になった。cron 式が正。
- `.github/workflows/refresh-token.yml` … 毎月1日
- `posts/<slug>/` … カルーセル画像 or リール動画 + caption.md
- `drafts/YYYY-MM-queue.csv` … 投稿キュー

セットアップは [SETUP.md](SETUP.md)。
