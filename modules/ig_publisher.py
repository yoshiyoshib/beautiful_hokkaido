"""Instagram Graph API Content Publishing wrapper."""
from __future__ import annotations

import time

import requests

import config


def _url(path: str) -> str:
    return f"{config.IG_API_BASE}/{path.lstrip('/')}"


def create_container(media_type: str, public_url: str, caption: str) -> str:
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

    r = requests.post(endpoint, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"create_container failed: {r.status_code} {r.text}")
    body = r.json()
    cid = body.get("id")
    if not cid:
        raise RuntimeError(f"create_container returned no id: {body}")
    return cid


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


def post_media(media_type: str, public_url: str, caption: str) -> str:
    """コンテナ作成→待機→公開を一気通貫で実行し IG メディア ID を返す。"""
    container_id = create_container(media_type, public_url, caption)
    wait_for_ready(container_id)
    return publish(container_id)
