"""Unsplash API からの候補画像発見モジュール。

Unsplash License は商用含む自由使用を許可。クレジットは任意だが、キャプションに
Photo by @{username} on Unsplash を自動付与して誠実運用する。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import config

API_BASE = "https://api.unsplash.com"


def _headers() -> dict:
    if not config.UNSPLASH_ACCESS_KEY:
        raise RuntimeError("UNSPLASH_ACCESS_KEY is not set")
    return {
        "Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}",
        "Accept-Version": "v1",
    }


def search_photos(query: str, per_page: int = 10, order_by: str = "latest", page: int = 1) -> list[dict]:
    """1クエリで Unsplash を叩いて、整形済みの候補リストを返す。"""
    r = requests.get(
        f"{API_BASE}/search/photos",
        params={
            "query": query,
            "per_page": per_page,
            "page": page,
            "order_by": order_by,  # "latest" | "relevant"
            "orientation": "portrait",  # Instagram 4:5 向き優先
            "content_filter": "high",
        },
        headers=_headers(),
        timeout=20,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    out = []
    for p in results:
        urls = p.get("urls") or {}
        user = p.get("user") or {}
        out.append({
            "id": p["id"],
            "url": urls.get("regular") or urls.get("full"),
            "full_url": urls.get("full"),
            "author_name": user.get("name") or "",
            "author_handle": user.get("username") or "",
            "unsplash_url": (p.get("links") or {}).get("html", ""),
            "description": p.get("description") or p.get("alt_description") or "",
        })
    return out


def _page_for_today() -> int:
    """日次でページ1〜3をローテ（同じクエリでも日ごとに違う素材を引く）。"""
    day = datetime.now(ZoneInfo(config.TIMEZONE)).day
    return (day % 3) + 1


def discover(queries: list[str], per_query: int = 5, order_by: str = "latest",
             page: int | None = None) -> list[dict]:
    """複数クエリをまとめて叩き、ID で重複排除した候補リストを返す。

    page=None なら日次ローテで 1〜3 を自動選択。
    """
    if page is None:
        page = _page_for_today()
    seen: set[str] = set()
    photos: list[dict] = []
    for q in queries:
        q = q.strip()
        if not q:
            continue
        try:
            for p in search_photos(q, per_page=per_query, order_by=order_by, page=page):
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                photos.append(p)
        except requests.HTTPError as e:
            print(f"  [unsplash] query={q!r} page={page} failed: {e}")
    print(f"  [unsplash] page={page} queries={len(queries)} results={len(photos)}")
    return photos


def build_credit_tail(photo: dict) -> str:
    """キャプション末尾に貼る Unsplash クレジット文を返す。"""
    name = photo.get("author_name") or photo.get("author_handle") or "Unknown"
    handle = photo.get("author_handle") or ""
    link = photo.get("unsplash_url") or "https://unsplash.com"
    if handle:
        return f"\n\n📷 Photo by {name} (@{handle}) on Unsplash\n{link}"
    return f"\n\n📷 Photo via Unsplash\n{link}"
