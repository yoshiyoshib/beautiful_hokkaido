"""静止画・動画の整形と Cloudinary へのアップロード。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import requests
from PIL import Image, ImageFilter

import config

cloudinary.config(
    cloud_name=config.CLOUDINARY_CLOUD_NAME,
    api_key=config.CLOUDINARY_API_KEY,
    api_secret=config.CLOUDINARY_API_SECRET,
    secure=True,
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

HTTP_HEADERS = {
    "User-Agent": "beautiful_hokkaido/0.1 (+https://github.com/beautiful-hokkaido)",
    "Accept": "*/*",
}

FEED_W, FEED_H = 1080, 1350  # 4:5
REEL_W, REEL_H = 1080, 1920  # 9:16


def _download(url: str) -> Path:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "download.bin"
    dst = config.TMP_DIR / name
    with requests.get(url, stream=True, timeout=120, headers=HTTP_HEADERS) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 64):
                if chunk:
                    f.write(chunk)
    return dst


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


def _fit_image_4x5(src: Path) -> Path:
    """4:5 キャンバスにブラー余白付きで配置した JPEG を返す。"""
    img = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (FEED_W, FEED_H), (0, 0, 0))

    bg = img.copy()
    scale = max(FEED_W / bg.width, FEED_H / bg.height)
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)), Image.LANCZOS)
    bx = (bg.width - FEED_W) // 2
    by = (bg.height - FEED_H) // 2
    bg = bg.crop((bx, by, bx + FEED_W, by + FEED_H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
    canvas.paste(bg, (0, 0))

    fg = img.copy()
    scale = min(FEED_W / fg.width, FEED_H / fg.height)
    nw, nh = max(1, int(fg.width * scale)), max(1, int(fg.height * scale))
    fg = fg.resize((nw, nh), Image.LANCZOS)
    canvas.paste(fg, ((FEED_W - nw) // 2, (FEED_H - nh) // 2))

    dst = config.TMP_DIR / f"feed_{src.stem}.jpg"
    canvas.save(dst, "JPEG", quality=92, optimize=True)
    return dst


def _fit_video_9x16(src: Path) -> Path:
    """FFmpeg で 1080x1920 / 30fps に正規化した mp4 を返す。"""
    dst = config.TMP_DIR / f"reel_{src.stem}.mp4"
    vf = (
        f"scale=w={REEL_W}:h={REEL_H}:force_original_aspect_ratio=decrease,"
        f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps=30"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr.decode(errors='replace')}") from e
    return dst


def _upload(path: Path, resource_type: str) -> str:
    res = cloudinary.uploader.upload_large(
        str(path),
        resource_type=resource_type,
        folder="beautiful_hokkaido",
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )
    return res["secure_url"]


def process_and_host(url: str) -> tuple[str, str]:
    """ソース URL を整形→Cloudinary 保存し (media_type, public_url) を返す。

    media_type は Instagram Graph API 向けに 'IMAGE' か 'VIDEO'。
    """
    local = _download(url)
    if _is_video(local):
        normalized = _fit_video_9x16(local)
        return "VIDEO", _upload(normalized, "video")
    normalized = _fit_image_4x5(local)
    return "IMAGE", _upload(normalized, "image")
