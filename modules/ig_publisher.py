"""Instagram Graph API Content Publishing wrapper."""
from __future__ import annotations

import time

import requests

import config


def _url(path: str) -> str:
    return f"{config.IG_API_BASE}/{path.lstrip('/')}"


def create_container(
    media_type: str,
    public_url: str,
    caption: str,
    *,
    alt_text: str = "",
    location_id: str = "",
) -> str:
    """コンテナを作成して creation_id を返す。"""
    endpoint = _url(f"{config.IG_USER_ID}/media")
    data: dict = {
        "caption": caption,
        "access_token": config.META_ACCESS_TOKEN,
    }
    if media_type == "VIDEO":
        data["media_type"] = "REELS"
        data["video_url"] = public_url
        data["share_to_feed"] = "true"
    else:
        data["image_url"] = public_url
        if alt_text:
            data["alt_text"] = alt_text[:1000]
    if location_id:
        data["location_id"] = location_id

    r = requests.post(endpoint, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"create_container failed: {r.status_code} {r.text}")
    body = r.json()
    cid = body.get("id")
    if not cid:
        raise RuntimeError(f"create_container returned no id: {body}")
    return cid


def create_carousel_item(public_url: str, is_video: bool = False) -> str:
    """カルーセル子要素のコンテナを作成し creation_id を返す。"""
    endpoint = _url(f"{config.IG_USER_ID}/media")
    data: dict = {
        "is_carousel_item": "true",
        "access_token": config.META_ACCESS_TOKEN,
    }
    if is_video:
        data["media_type"] = "VIDEO"
        data["video_url"] = public_url
    else:
        data["image_url"] = public_url
    r = requests.post(endpoint, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"create_carousel_item failed: {r.status_code} {r.text}")
    return r.json()["id"]


def create_carousel_container(children_ids: list[str], caption: str, location_id: str = "") -> str:
    """子ID群をまとめて親カルーセルコンテナを作成。"""
    endpoint = _url(f"{config.IG_USER_ID}/media")
    data: dict = {
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
        "access_token": config.META_ACCESS_TOKEN,
    }
    if location_id:
        data["location_id"] = location_id
    r = requests.post(endpoint, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"create_carousel_container failed: {r.status_code} {r.text}")
    return r.json()["id"]


def share_to_story(media_id: str) -> str | None:
    """投稿済み feed メディアをストーリーに共有。失敗しても None を返す（任意機能）。"""
    endpoint = _url(f"{config.IG_USER_ID}/media")
    data = {
        "media_type": "STORIES",
        "media_id": media_id,
        "access_token": config.META_ACCESS_TOKEN,
    }
    try:
        r = requests.post(endpoint, data=data, timeout=30)
        if not r.ok:
            print(f"  [story share] skip: {r.status_code} {r.text[:200]}")
            return None
        story_cid = r.json().get("id")
        publish_endpoint = _url(f"{config.IG_USER_ID}/media_publish")
        p = requests.post(publish_endpoint, data={
            "creation_id": story_cid,
            "access_token": config.META_ACCESS_TOKEN,
        }, timeout=30)
        if p.ok:
            print(f"  [story share] OK: {p.json().get('id')}")
            return p.json().get("id")
    except Exception as e:  # noqa: BLE001
        print(f"  [story share] failed: {e}")
    return None


def search_location_id(query: str) -> str | None:
    """地名から Instagram Location ID を検索。見つからなければ None。"""
    if not query:
        return None
    endpoint = _url(f"{config.IG_USER_ID}/search")
    try:
        r = requests.get(endpoint, params={
            "fields": "name,id",
            "q": query,
            "access_token": config.META_ACCESS_TOKEN,
        }, timeout=20)
        if r.ok:
            data = r.json().get("data", [])
            if data:
                return data[0].get("id")
    except Exception as e:  # noqa: BLE001
        print(f"  [location search] failed: {e}")
    return None


def wait_for_ready(container_id: str, max_wait_sec: int | None = None) -> None:
    """status_code が FINISHED になるまで最大 max_wait_sec 秒、指数バックオフで待機。"""
    if max_wait_sec is None:
        max_wait_sec = config.CONTAINER_MAX_WAIT_SEC
    endpoint = _url(container_id)
    params = {
        "fields": "status_code,status",
        "access_token": config.META_ACCESS_TOKEN,
    }
    waited = 0
    delay = 2
    while waited < max_wait_sec:
        r = requests.get(endpoint, params=params, timeout=30)
        if not r.ok:
            raise RuntimeError(f"wait_for_ready failed: {r.status_code} {r.text}")
        body = r.json()
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"container {container_id} status={status}: {body}")
        time.sleep(delay)
        waited += delay
        delay = min(delay * 2, 20)
    raise TimeoutError(
        f"container {container_id} not FINISHED within {max_wait_sec}s"
    )


def publish(container_id: str) -> str:
    """コンテナを公開して Instagram メディア ID を返す。"""
    endpoint = _url(f"{config.IG_USER_ID}/media_publish")
    data = {
        "creation_id": container_id,
        "access_token": config.META_ACCESS_TOKEN,
    }
    r = requests.post(endpoint, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"publish failed: {r.status_code} {r.text}")
    body = r.json()
    pid = body.get("id")
    if not pid:
        raise RuntimeError(f"publish returned no id: {body}")
    return pid


def post_media(
    media_type: str,
    public_url: str,
    caption: str,
    *,
    alt_text: str = "",
    location_id: str = "",
    share_story: bool = True,
) -> str:
    """コンテナ作成→待機→公開を一気通貫で実行し IG メディア ID を返す。"""
    container_id = create_container(
        media_type, public_url, caption,
        alt_text=alt_text, location_id=location_id,
    )
    wait_for_ready(container_id)
    media_id = publish(container_id)
    if share_story:
        share_to_story(media_id)
    return media_id


def post_carousel(
    public_urls: list[str],
    caption: str,
    *,
    location_id: str = "",
    share_story: bool = True,
) -> str:
    """複数画像をカルーセル投稿。"""
    child_ids = [create_carousel_item(u, is_video=False) for u in public_urls]
    # 子要素も READY 待ちが必要
    for cid in child_ids:
        wait_for_ready(cid, max_wait_sec=120)
    parent_id = create_carousel_container(child_ids, caption, location_id=location_id)
    wait_for_ready(parent_id)
    media_id = publish(parent_id)
    if share_story:
        share_to_story(media_id)
    return media_id
