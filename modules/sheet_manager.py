"""Google Sheets 台帳の読み書き。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNS = [
    "ID",
    "Original_URL",
    "Author_Handle",
    "Status",
    "Location",
    "Generated_Caption",
    "Public_Media_URL",
    "IG_Post_ID",
    "Scheduled_Time",
]

STATUS_VALUES = {"Pending", "Approved", "Posted", "Rejected", "Error"}


def _client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _worksheet() -> gspread.Worksheet:
    gc = _client()
    sh = gc.open_by_key(config.SPREADSHEET_ID)
    return sh.worksheet(config.WORKSHEET_NAME)


def ensure_header() -> None:
    """1行目にカラム定義を書き込む（初回セットアップ用）。"""
    ws = _worksheet()
    first_row = ws.row_values(1)
    if first_row != COLUMNS:
        ws.update("A1", [COLUMNS])


def _col_index(name: str) -> int:
    return COLUMNS.index(name) + 1


def _parse_scheduled(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(config.TIMEZONE))
    return dt


def fetch_pending() -> list[tuple[int, dict]]:
    """Status == 'Pending' の全行を (行番号, dict) で返す。"""
    ws = _worksheet()
    records = ws.get_all_records()
    out: list[tuple[int, dict]] = []
    for i, r in enumerate(records, start=2):
        if (r.get("Status") or "").strip() == "Pending":
            out.append((i, r))
    return out


def fetch_due_approved() -> tuple[Optional[int], Optional[dict]]:
    """Scheduled_Time を過ぎており Status == 'Approved' のレコードを1件返す。"""
    ws = _worksheet()
    records = ws.get_all_records()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    for i, r in enumerate(records, start=2):
        if (r.get("Status") or "").strip() != "Approved":
            continue
        sched = _parse_scheduled(r.get("Scheduled_Time", ""))
        if sched is None or sched <= now:
            return i, r
    return None, None


def update_cell(row: int, column: str, value) -> None:
    ws = _worksheet()
    ws.update_cell(row, _col_index(column), value)


def update_evaluation(row: int, status: str, location: str, caption: str) -> None:
    ws = _worksheet()
    ws.update_cell(row, _col_index("Status"), status)
    ws.update_cell(row, _col_index("Location"), location)
    ws.update_cell(row, _col_index("Generated_Caption"), caption)


def set_public_media(row: int, public_url: str) -> None:
    update_cell(row, "Public_Media_URL", public_url)


def _col_letter(col_1based: int) -> str:
    """1-based 列番号を A1 記法の列文字に変換（A〜Z のみ、本プロジェクトは9列固定）。"""
    return chr(ord("A") + col_1based - 1)


def mark_posted(row: int, ig_post_id: str) -> None:
    """IG_Post_ID は RAW 書き込みで科学記法変換を回避（17桁数値が 1.81e+16 になる問題）。"""
    ws = _worksheet()
    ws.update_cell(row, _col_index("Status"), "Posted")
    col = _col_letter(_col_index("IG_Post_ID"))
    ws.update(
        range_name=f"{col}{row}",
        values=[[str(ig_post_id)]],
        value_input_option="RAW",
    )


def fetch_existing_ids() -> set[str]:
    """ID 列の既存値セットを返す（重複登録防止用）。"""
    ws = _worksheet()
    col = ws.col_values(_col_index("ID"))
    return {v for v in col[1:] if v}


def append_row(
    *,
    id: str,
    url: str,
    author: str,
    status: str = "Approved",
    location: str = "",
    caption: str = "",
    scheduled_time: str = "",
) -> int:
    """新規行を末尾に追加。返り値は追加された行番号。"""
    ws = _worksheet()
    row = [id, url, author, status, location, caption, "", "", scheduled_time]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return len(ws.get_all_values())


def mark_error(row: int, message: str) -> None:
    ws = _worksheet()
    ws.update_cell(row, _col_index("Status"), "Error")
    cur = ws.cell(row, _col_index("Generated_Caption")).value or ""
    suffix = f"\n[ERROR] {message}"
    ws.update_cell(row, _col_index("Generated_Caption"), (cur + suffix)[:49000])
