"""Approved キューの健全性を監視し、空＋最終投稿から QUEUE_ALERT_HOURS 経過なら GitHub Issue 通知。

token_monitor と同じパターンで冪等（ラベル付き Open Issue が既にあれば作らない）。
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import config
from modules import sheet_manager

ISSUE_LABEL = "queue-empty"


def check_health() -> dict:
    """キューの現状を返す。

    返り値: {
      'approved_count': int,
      'posted_count': int,
      'last_posted_at': datetime | None,  # JST
      'hours_since_last_post': float | None,
    }
    """
    ws = sheet_manager._worksheet()
    rows = ws.get_all_records()
    approved = [r for r in rows if (r.get("Status") or "").strip() == "Approved"]
    posted = [r for r in rows if (r.get("Status") or "").strip() == "Posted"]

    # 最終投稿時刻は Scheduled_Time（Posted行にも残っている）または Generated_Caption 末尾の [ERROR] 等で推定しにくい
    # IG API で直接取るのが最確実。insights_collector と重複するが依存最小化のため軽量実装。
    last_posted_at = _fetch_last_post_timestamp()
    hours_since = None
    if last_posted_at:
        now = datetime.now(ZoneInfo(config.TIMEZONE))
        hours_since = (now - last_posted_at).total_seconds() / 3600.0

    return {
        "approved_count": len(approved),
        "posted_count": len(posted),
        "last_posted_at": last_posted_at,
        "hours_since_last_post": hours_since,
    }


def _fetch_last_post_timestamp() -> datetime | None:
    try:
        r = requests.get(
            f"{config.IG_API_BASE}/{config.IG_USER_ID}/media",
            params={
                "fields": "id,timestamp",
                "limit": 1,
                "access_token": config.META_ACCESS_TOKEN,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            return None
        ts = data[0].get("timestamp", "")
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(config.TIMEZONE))
    except Exception as e:  # noqa: BLE001
        print(f"  [queue_monitor] last post timestamp fetch failed: {e}")
        return None


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


def _issue_body(repo: str, health: dict, trigger: str) -> str:
    hours = health.get("hours_since_last_post")
    hours_str = f"{hours:.1f} 時間" if hours is not None else "不明"
    last = health.get("last_posted_at")
    last_str = last.strftime("%Y-%m-%d %H:%M JST") if last else "不明"

    return f"""Approved キューが**空**で、最終投稿から **{hours_str}** 経過しています。

| 項目 | 値 |
|---|---|
| Approved (投稿待ち) | {health['approved_count']} |
| Posted (投稿済み合計) | {health['posted_count']} |
| 最終投稿時刻 | {last_str} |
| 検知トリガー | `{trigger}` |

## 即時復旧手順

1. **手動で auto_source を再実行**:
   https://github.com/{repo}/actions/workflows/auto_post.yml
   → "Run workflow" → mode = `auto_source` → Run workflow

2. **それでも 0 件なら Gemini quota 枯渇の可能性**:
   https://aistudio.google.com/app/apikey で使用量確認。無料枠 20/day はすぐ尽きます。回復は UTC リセット (JST 翌 09:00)。

3. **緩和モードで強制補充** (開発中):
   閾値 8→7 に下げて再評価。auto_source 内部で 0件なら自動で relaxed モードにフォールバックするよう実装済み。

4. **Unsplash API 残枠確認**:
   https://unsplash.com/oauth/applications → 50 req/hour の無料枠。

## 根本対策 (最近のコミット済み)

- `UNSPLASH_ORDER_BY=latest` + 日次ページローテ (1→2→3) で同じ素材ばかり引く問題を解決
- auto_source 0件時に自動で `AUTO_SOURCE_FALLBACK_MIN_*` (7/7) で再評価
- 新 `check_queue` モードが毎日 JST 10:00 に健全性チェック

Approved が 1件以上キューに入れば自動解消します。手動で Approved 行を追加しても OK。

---
*この Issue は `queue_monitor` が自動作成しました。キューが補充されたら Close してください（次回不健全時に新 Issue 作成）。*
"""


def monitor(trigger: str = "scheduled") -> int:
    """キュー健全性を調べ、unhealthy なら GitHub Issue 作成。

    trigger: 呼び出し元を識別するラベル ('scheduled' / 'publish_empty' / 'auto_source_zero')
    """
    try:
        health = check_health()
    except Exception as e:  # noqa: BLE001
        print(f"[queue_monitor] health check failed: {e}")
        return 1

    approved = health["approved_count"]
    hours = health["hours_since_last_post"]
    print(f"[queue_monitor] approved={approved} posted={health['posted_count']} "
          f"hours_since_last_post={hours} trigger={trigger}")

    # 健全判定: Approved が 1件以上 OR 最終投稿が QUEUE_ALERT_HOURS 以内
    if approved >= 1:
        print("[queue_monitor] OK: queue has items")
        return 0
    if hours is not None and hours < config.QUEUE_ALERT_HOURS:
        print(f"[queue_monitor] OK: last post {hours:.1f}h ago (<{config.QUEUE_ALERT_HOURS}h threshold)")
        return 0

    # unhealthy: Issue 作成
    token, repo = _github_env()
    if not token or not repo:
        print("[queue_monitor] GITHUB_TOKEN/REPOSITORY unset, cannot create issue")
        return 0

    try:
        existing = _issue_exists(repo, token)
    except Exception as e:  # noqa: BLE001
        print(f"[queue_monitor] issue check failed: {e}")
        return 1

    if existing:
        print(f"[queue_monitor] existing issue #{existing['number']}: {existing['html_url']}")
        return 0

    hours_str = f"{hours:.0f}h" if hours is not None else "unknown"
    title = f"⚠️ Approved queue empty — no posts for {hours_str}"
    body = _issue_body(repo, health, trigger)
    try:
        issue = _create_issue(repo, token, title, body)
        print(f"[queue_monitor] created issue #{issue['number']}: {issue['html_url']}")
    except Exception as e:  # noqa: BLE001
        print(f"[queue_monitor] create issue failed: {e}")
        return 1
    return 0
