#!/usr/bin/env python3
"""
Instagram (Facebook Login) 長期トークンのリフレッシュ。

graph.facebook.com の long-lived user token は約60日で失効する。月1で
GitHub Actions から呼び、fb_exchange_token で延長して GitHub Secret を更新する。

※恒久トークン(non-expiring Page token)を使う運用なら本スクリプトは不要。
  その場合は refresh-token.yml を無効化してよい。SETUP.md 参照。

必要な環境変数:
  IG_TOKEN        現在の長期ユーザートークン
  FB_APP_ID       Meta アプリ ID
  FB_APP_SECRET   Meta アプリシークレット
  GH_PAT          repo secrets:write 権限つき PAT
  GH_REPO         owner/repo
"""

import os
import subprocess
import sys

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def refresh(app_id, app_secret, token):
    r = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": token,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data.get("expires_in")


def update_secret(repo, pat, new_token):
    env = dict(os.environ, GH_TOKEN=pat)
    subprocess.run(
        ["gh", "secret", "set", "IG_TOKEN", "--repo", repo, "--body", new_token],
        check=True,
        env=env,
    )


def main():
    new_token, expires_in = refresh(
        os.environ["FB_APP_ID"],
        os.environ["FB_APP_SECRET"],
        os.environ["IG_TOKEN"],
    )
    days = (expires_in or 0) // 86400
    print(f"トークン更新成功。残り約 {days} 日。")
    update_secret(os.environ["GH_REPO"], os.environ["GH_PAT"], new_token)
    print("GitHub Secret (IG_TOKEN) 更新完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
