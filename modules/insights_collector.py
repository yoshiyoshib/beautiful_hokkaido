"""投稿後の engagement を取得し、`insights` タブに蓄積して A/B 分析の材料にする。"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import requests

import config
from modules.sheet_manager import _client

INSIGHTS_SHEET = "insights"
INSIGHTS_COLUMNS = [
    "IG_Post_ID", "Posted_At", "Posted_Hour_JST", "Media_Type",
    "Reach", "Plays", "Likes", "Comments", "Saves", "Shares", "Total_Interactions",
    "Fetched_At",
]


def _ensure_insights_sheet() -> gspread.Worksheet:
    gc = _client()
    sh = gc.open_by_key(config.SPREADSHEET_ID)
    try:
        ws = sh.worksheet(INSIGHTS_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=INSIGHTS_SHEET, rows=1000, cols=len(INSIGHTS_COLUMNS))
        ws.update("A1", [INSIGHTS_COLUMNS])
    first_row = ws.row_values(1)
    if first_row != INSIGHTS_COLUMNS:
        ws.update("A1", [INSIGHTS_COLUMNS])
    return ws


def fetch_post_insights(media_id: str) -> dict:
    """IG API から1投稿のインサイトを取得。メトリクスが拒否されたら個別に試行。"""
    # 全メディア共通で安全なメトリクス（v21 で deprecate されたもの除く）
    safe_metrics = ["reach", "likes", "comments", "saves"]
    reel_only = ["plays", "shares", "total_interactions"]

    out: dict = {}
    # 1) バッチで安全セット
    try:
        r = requests.get(
            f"{config.IG_API_BASE}/{media_id}/insights",
            params={"metric": ",".join(safe_metrics), "access_token": config.META_ACCESS_TOKEN},
            timeout=20,
        )
        if r.ok:
            for item in r.json().get("data", []):
                name = item.get("name")
                values = item.get("values") or []
                if values:
                    out[name] = values[0].get("value", 0)
    except Exception:
        pass

    # 2) Reels 専用メトリクスを個別に試行（失敗は無視）
    for m in reel_only:
        try:
            r = requests.get(
                f"{config.IG_API_BASE}/{media_id}/insights",
                params={"metric": m, "access_token": config.META_ACCESS_TOKEN},
                timeout=15,
            )
            if r.ok:
                for item in r.json().get("data", []):
                    values = item.get("values") or []
                    if values:
                        out[m] = values[0].get("value", 0)
        except Exception:
            pass
    return out


def fetch_recent_media(limit: int = 25) -> list[dict]:
    """自分の直近の投稿一覧を取得。"""
    r = requests.get(
        f"{config.IG_API_BASE}/{config.IG_USER_ID}/media",
        params={
            "fields": "id,media_type,timestamp",
            "limit": limit,
            "access_token": config.META_ACCESS_TOKEN,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def collect() -> int:
    """直近投稿のインサイトを insights タブに追記・更新。"""
    ws = _ensure_insights_sheet()
    existing_rows = ws.get_all_records()
    existing_ids = {str(r.get("IG_Post_ID")): i + 2 for i, r in enumerate(existing_rows)}

    tz = ZoneInfo(config.TIMEZONE)
    now_iso = datetime.now(tz).isoformat()
    posts = fetch_recent_media(limit=25)
    appended = 0
    updated = 0

    for p in posts:
        pid = str(p["id"])
        posted_at = p.get("timestamp", "")
        media_type = p.get("media_type", "")
        # 24時間以内の投稿はまだデータ不足気味、48時間後に再取得する想定で両方更新
        try:
            insights = fetch_post_insights(pid)
        except Exception as e:  # noqa: BLE001
            print(f"  [insights] skip {pid}: {e}")
            continue

        try:
            dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00")).astimezone(tz)
            posted_hour = dt.hour
            posted_at_jst = dt.isoformat()
        except Exception:
            posted_hour = ""
            posted_at_jst = posted_at

        row = [
            pid, posted_at_jst, posted_hour, media_type,
            insights.get("reach", 0), insights.get("plays", 0),
            insights.get("likes", 0), insights.get("comments", 0),
            insights.get("saves", 0), insights.get("shares", 0),
            insights.get("total_interactions", 0),
            now_iso,
        ]
        if pid in existing_ids:
            ws.update(f"A{existing_ids[pid]}", [row])
            updated += 1
        else:
            ws.append_row(row, value_input_option="USER_ENTERED")
            appended += 1

    print(f"[insights] appended={appended} updated={updated}")
    return 0
