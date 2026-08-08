#!/usr/bin/env python3
"""
Laifu Instagram carousel poster.

GitHub Actions の cron から呼ばれ、キュー CSV の最上段の未投稿カルーセルを1本
Instagram Graph API で公開する。nh-threads-poster の骨組みを IG カルーセル用に移植。

流れ:
1. キュー CSV を読む (drafts/YYYY-MM-queue.csv)
2. FIFO で次の未投稿カルーセルを1本選ぶ(status が hold 系 / posted_at 済み はスキップ)
3. posts/<slug>/ の中身で投稿種別が決まる:
   - .mp4/.mov がある → **リール**(media_type=REELS, video_url=<公開URL>) を1本。
     cover.jpg があれば表紙に使う。動画は変換に数分かかるので最大10分待つ
   - 画像だけ → 各スライドを子コンテナ化 (is_carousel_item=true, image_url=<公開URL>)
     → 親コンテナ(CAROUSEL) → publish。1枚なら単一画像投稿、2〜10枚ならカルーセル
4. その行に posted_at と status=posted を書き戻す(Actions が CSV を commit)

IG API はローカル画像を受け取れない。各スライドは **公開HTTPS URL** が必須。
既定では repo にコミットした画像を PUBLIC_BASE_URL 経由の raw URL として配信する想定。

必要な環境変数 (GitHub Secrets / vars):
  IG_USER_ID       Instagram ビジネスアカウントの ID (数値)
  IG_TOKEN         長期アクセストークン (graph.facebook.com)
  PUBLIC_BASE_URL  画像公開URLのベース。例 https://raw.githubusercontent.com/<owner>/<repo>/main
  QUEUE_FILE       (任意) キュー CSV パス。未指定なら当月の drafts/YYYY-MM-queue.csv
  POSTS_DIR        (任意) カルーセル画像フォルダのルート(repo相対)。既定 "posts"
  DRY_RUN          (任意) "1" なら API を叩かず、やることだけ表示

CSV 列: date | time | slug | caption | status | posted_at
  slug     posts/<slug>/ に 1.jpg,2.jpg,... とキャプション(caption.md 任意)がある
  caption  空なら posts/<slug>/caption.md を使う
  status   draft/hold/skip/保留/スキップ/下書き はスキップ。空欄は approved 扱い
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))
GRAPH = "https://graph.facebook.com/v21.0"

HOLD = {"draft", "hold", "skip", "保留", "スキップ", "下書き"}
FIELDNAMES = ["date", "time", "slug", "caption", "status", "posted_at"]
IMG_EXTS = (".jpg", ".jpeg", ".png")
VIDEO_EXTS = (".mp4", ".mov")
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png")

DRY_RUN = os.environ.get("DRY_RUN", "") == "1"


def queue_path():
    explicit = os.environ.get("QUEUE_FILE")
    if explicit:
        return explicit
    month = datetime.now(JST).strftime("%Y-%m")
    return os.path.join("drafts", f"{month}-queue.csv")


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def save_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in FIELDNAMES})


def _go(rec):
    status = str(rec.get("status", "")).strip().lower()
    posted = str(rec.get("posted_at", "")).strip()
    slug = str(rec.get("slug", "")).strip()
    return bool(slug) and not posted and status not in HOLD


def pick_row(rows):
    """FIFO で次に投稿する行を返す。(idx, rec) or (None, None)。"""
    for idx, rec in enumerate(rows):
        if _go(rec):
            return idx, rec
    return None, None


def _natural_key(name):
    # "1.jpg","2.jpg",...,"10.jpg" を数値順に。数字なしは末尾。
    m = re.match(r"(\d+)", os.path.splitext(name)[0])
    return (0, int(m.group(1))) if m else (1, name.lower())


def collect_media(posts_dir, slug):
    """posts/<slug>/ の中身から投稿種別を決める。

    動画(.mp4/.mov)が1つでもあれば **リール**扱いで、その動画1本を投稿する。
    無ければ従来どおり画像のカルーセル。cover.jpg があればリールの表紙に使う
    (無ければ IG が動画の先頭フレームから自動生成する)。

    returns ("reel", [動画path], cover_path or None)
         or ("images", [画像path...], None)
    """
    folder = os.path.join(posts_dir, slug)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"投稿フォルダが無い: {folder}")
    names = os.listdir(folder)

    videos = [f for f in names if f.lower().endswith(VIDEO_EXTS)]
    if videos:
        videos.sort(key=_natural_key)
        if len(videos) > 1:
            print(f"  [警告] 動画が{len(videos)}本ある → 先頭の {videos[0]} だけ投稿",
                  file=sys.stderr)
        cover = next((f for f in names if f.lower() in COVER_NAMES), None)
        return "reel", [os.path.join(folder, videos[0])], (
            os.path.join(folder, cover) if cover else None
        )

    # カルーセルでは cover.jpg は表紙用なのでスライドに混ぜない
    imgs = [f for f in names
            if f.lower().endswith(IMG_EXTS) and f.lower() not in COVER_NAMES]
    imgs.sort(key=_natural_key)
    if not imgs:
        raise FileNotFoundError(f"画像も動画も無い: {folder}")
    return "images", [os.path.join(folder, f) for f in imgs], None


def public_url(base, local_path):
    rel = local_path.replace(os.sep, "/").lstrip("./")
    return f"{base.rstrip('/')}/{rel}"


def resolve_caption(rec, posts_dir, slug):
    cap = str(rec.get("caption", "")).strip()
    if cap:
        return cap
    cap_md = os.path.join(posts_dir, slug, "caption.md")
    if os.path.exists(cap_md):
        with open(cap_md, encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ── Instagram Graph API ─────────────────────────────────
def _post(path, data):
    if DRY_RUN:
        shown = {k: v for k, v in data.items() if k != "access_token"}
        print(f"    [DRY_RUN] POST {path}  {shown}")
        return "DRYRUN_ID"
    r = requests.post(f"{GRAPH}/{path}", data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"POST {path} 失敗 {r.status_code}: {r.text}")
    return r.json()["id"]


def wait_finished(container_id, token, tries=20, delay=3):
    """コンテナが FINISHED になるまで待つ(IG は処理完了前に publish すると失敗する)。

    画像は数秒で終わるが**動画は変換に数分かかる**ので、リールは呼び出し側が
    tries/delay を伸ばして渡すこと。
    """
    if DRY_RUN:
        return
    for _ in range(tries):
        r = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        r.raise_for_status()
        code = r.json().get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError(f"コンテナ {container_id} が ERROR: {r.json()}")
        time.sleep(delay)
    raise TimeoutError(f"コンテナ {container_id} が FINISHED にならず")


def create_child(ig_user_id, token, image_url):
    return _post(f"{ig_user_id}/media", {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": token,
    })


def create_single(ig_user_id, token, image_url, caption):
    return _post(f"{ig_user_id}/media", {
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    })


def create_reel(ig_user_id, token, video_url, caption, cover_url=None):
    data = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": token,
    }
    if cover_url:
        data["cover_url"] = cover_url
    return _post(f"{ig_user_id}/media", data)


def create_carousel(ig_user_id, token, child_ids, caption):
    return _post(f"{ig_user_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": token,
    })


def publish(ig_user_id, token, creation_id):
    return _post(f"{ig_user_id}/media_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })


def post_reel(ig_user_id, token, video_url, caption, cover_url=None):
    """リールを1本公開する。動画は変換待ちが長いので最大10分まで粘る。"""
    cid = create_reel(ig_user_id, token, video_url, caption, cover_url)
    print(f"    リールコンテナ: {cid}(変換待ち、最大10分)")
    wait_finished(cid, token, tries=60, delay=10)
    time.sleep(3)  # Meta推奨: publish 前に少し待つ
    return publish(ig_user_id, token, cid)


def post_carousel(ig_user_id, token, image_urls, caption):
    if len(image_urls) == 1:
        print("  単一画像として投稿(スライド1枚)")
        cid = create_single(ig_user_id, token, image_urls[0], caption)
        wait_finished(cid, token)
        return publish(ig_user_id, token, cid)

    if len(image_urls) > 10:
        print(f"  [警告] スライド{len(image_urls)}枚 → IG上限の先頭10枚のみ投稿", file=sys.stderr)
        image_urls = image_urls[:10]

    child_ids = []
    for i, url in enumerate(image_urls, 1):
        cid = create_child(ig_user_id, token, url)
        wait_finished(cid, token)
        print(f"    子コンテナ {i}/{len(image_urls)}: {cid}")
        child_ids.append(cid)
        time.sleep(1)

    parent = create_carousel(ig_user_id, token, child_ids, caption)
    wait_finished(parent, token)
    time.sleep(3)  # Meta推奨: publish 前に少し待つ
    return publish(ig_user_id, token, parent)


def main():
    ig_user_id = os.environ.get("IG_USER_ID", "IG_USER_ID?")
    token = os.environ.get("IG_TOKEN", "IG_TOKEN?")
    base = os.environ.get("PUBLIC_BASE_URL", "").strip()
    posts_dir = os.environ.get("POSTS_DIR", "posts")

    if not DRY_RUN and (ig_user_id.endswith("?") or token.endswith("?") or not base):
        print("IG_USER_ID / IG_TOKEN / PUBLIC_BASE_URL が未設定。中断。", file=sys.stderr)
        return 1

    path = queue_path()
    if not os.path.exists(path):
        print(f"キューCSVが無い: {path}。投稿なし、終了。")
        return 0

    rows = load_rows(path)
    idx, rec = pick_row(rows)
    if rec is None:
        print(f"投稿対象なし ({path})。何もせず終了。")
        return 0

    slug = str(rec["slug"]).strip()
    kind, files, cover = collect_media(posts_dir, slug)
    fallback = base or "https://PUBLIC_BASE_URL"
    urls = [public_url(fallback, p) for p in files]
    cover_url = public_url(fallback, cover) if cover else None
    caption = resolve_caption(rec, posts_dir, slug)

    label = "リール動画1本" if kind == "reel" else f"スライド{len(files)}枚"
    print(f"投稿対象: slug='{slug}' {label} (CSV {idx + 2} 行目, {path})"
          + ("  [DRY_RUN]" if DRY_RUN else ""))
    for u in urls:
        print(f"  {'video_url' if kind == 'reel' else 'image_url'}: {u}")
    if cover_url:
        print(f"  cover_url: {cover_url}")
    print(f"  caption ({len(caption)}字): {caption[:80]}{'…' if len(caption) > 80 else ''}")

    if kind == "reel":
        media_id = post_reel(ig_user_id, token, urls[0], caption, cover_url)
    else:
        media_id = post_carousel(ig_user_id, token, urls, caption)
    print(f"投稿成功: media id = {media_id}")

    rows[idx]["posted_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    rows[idx]["status"] = "posted"
    if DRY_RUN:
        print("[DRY_RUN] CSV 書き戻しはスキップ。")
    else:
        save_rows(path, rows)
        print(f"CSV 書き戻し完了: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
