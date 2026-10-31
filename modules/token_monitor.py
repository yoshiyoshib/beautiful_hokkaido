"""Meta アクセストークンの残日数を監視し、期限が近づいたら GitHub Issue で通知。"""
from __future__ import annotations

import os
import time

import requests

import config

WARN_DAYS = 7
ISSUE_LABEL = "token-expiry"


def check_meta_token() -> dict:
    """Meta の debug_token を叩いてトークン情報を返す。

    返り値: {'is_valid': bool, 'expires_at': int, 'days_remaining': int|None}
    days_remaining=None は永続トークン（期限なし）。
    """
    r = requests.get(
        f"{config.IG_API_BASE}/debug_token",
        params={
            "input_token": config.META_ACCESS_TOKEN,
            "access_token": config.META_ACCESS_TOKEN,
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json().get("data", {})
    is_valid = bool(data.get("is_valid"))
    expires_at = int(data.get("expires_at") or 0)
    if expires_at == 0:
        days_remaining = None  # never expires
    else:
        days_remaining = max(0, int((expires_at - time.time()) / 86400))
    return {
        "is_valid": is_valid,
        "expires_at": expires_at,
        "days_remaining": days_remaining,
    }


def _github_env() -> tuple[str | None, str | None]:
    return os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")


def _issue_exists(repo: str, token: str) -> dict | None:
    r = requests.get(
        f"https://api.github.com/repos/{repo}/issues",
        params={"state": "open", "labels": ISSUE_LABEL, "per_page": 1},
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        timeout=20,
    )
    r.raise_for_status()
    arr = r.json()
    return arr[0] if arr else None


def _create_issue(repo: str, token: str, title: str, body: str) -> dict:
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body, "labels": [ISSUE_LABEL]},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _issue_body(repo: str, days_remaining: int | None, is_valid: bool) -> str:
    if not is_valid:
        headline = "Meta アクセストークンが**既に失効**しています。即時更新が必要です。"
    elif days_remaining == 0:
        headline = "Meta アクセストークンが**本日中に失効**します。"
    else:
        headline = f"Meta アクセストークンがあと **{days_remaining} 日** で失効します。"

    return f"""{headline}

失効すると `--mode publish` が全て失敗し Instagram 投稿が停止します。

## 再発行手順（約10分）

### 1. 短期トークン発行
1. https://developers.facebook.com/tools/explorer/ を開く
2. 右の **Meta App** で `beautiful_hokkaido_bot` を選択
3. **User or Page** → **Get User Access Token**
4. **Permissions** 5つにチェック:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
5. **Generate Access Token** → Facebookログイン → ページ選択
6. 画面上部の短期トークンをコピー

### 2. 長期トークン(60日)に変換
ブラウザのアドレスバーに下を貼り付け（`APP_ID` と `APP_SECRET` は Meta for Developers アプリ設定の Basic から取得、`SHORT_TOKEN` は上でコピーしたトークン）:
```
https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN
```
→ レスポンス JSON の `access_token` の値をコピー。

### 3. GitHub Secret 更新
1. https://github.com/{repo}/settings/secrets/actions を開く
2. `META_ACCESS_TOKEN` の **Update** をクリック
3. 新しい長期トークンを貼り付け → **Update secret**

### 4. 動作確認
1. https://github.com/{repo}/actions/workflows/auto_post.yml を開く
2. **Run workflow** → mode = `check_token` → **Run workflow**
3. 緑チェックが出れば OK → この Issue を Close

---
*この Issue は `check_token` モードが毎朝自動検知して作成しています。トークン更新後に Close してください。*
"""


def monitor() -> int:
    """トークン残日数を調べ、閾値以下なら GitHub Issue 作成。終了コードを返す。"""
    try:
        info = check_meta_token()
    except Exception as e:  # noqa: BLE001
        print(f"[monitor] token check failed: {e}")
        return 1

    is_valid = info["is_valid"]
    days = info["days_remaining"]
    print(f"[monitor] is_valid={is_valid} days_remaining={days}")

    if is_valid and (days is None or days >= WARN_DAYS):
        print(f"[monitor] OK, next check tomorrow")
        return 0

    token, repo = _github_env()
    if not token or not repo:
        print("[monitor] GITHUB_TOKEN or GITHUB_REPOSITORY not set, cannot create issue")
        return 0

    try:
        existing = _issue_exists(repo, token)
    except Exception as e:  # noqa: BLE001
        print(f"[monitor] issue check failed: {e}")
        return 1

    if existing:
        print(f"[monitor] existing issue: #{existing['number']} {existing['html_url']}")
        return 0

    if not is_valid:
        title = "⚠️ Meta Access Token EXPIRED — Instagram posting stopped"
    elif days == 0:
        title = "⚠️ Meta Access Token expires TODAY"
    else:
        title = f"⚠️ Meta Access Token expires in {days} days"

    body = _issue_body(repo, days, is_valid)
    try:
        issue = _create_issue(repo, token, title, body)
        print(f"[monitor] created issue #{issue['number']}: {issue['html_url']}")
    except Exception as e:  # noqa: BLE001
        print(f"[monitor] create issue failed: {e}")
        return 1
    return 0
