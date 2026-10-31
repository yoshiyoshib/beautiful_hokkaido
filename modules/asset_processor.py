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
REEL_DURATION_SEC = 8  # Reels 長さ（3〜90s）
REEL_FPS = 30


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


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",      # GH Actions ubuntu
    "/System/Library/Fonts/Helvetica.ttc",                        # macOS
    "C:/Windows/Fonts/arialbd.ttf",                               # Windows
    "C:/Windows/Fonts/segoeuib.ttf",
]


def _find_font() -> str:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return ""


def _image_to_reel_kenburns(src: Path) -> Path:
    """静止画を 9:16 Reels (mp4) に変換。軽量なズームイン＋CTA オーバーレイ付き。

    - 8秒動画、30fps
    - 背景に blur、前景に写真（4:5 → 9:16 に空間拡張）
    - 最後 2 秒に "DOUBLE TAP IF YOU LOVE HOKKAIDO ❤" オーバーレイ
    - 右矢印で視線をハートボタンへ誘導
    """
    print(f"  [kenburns] start convert {src.name}", flush=True)
    dst = config.TMP_DIR / f"reel_{src.stem}.mp4"
    font = _find_font()

    # 軽量な ken burns 代替: scale+crop の時変数で実質ズーム効果
    #   1 本の filter_complex で: blur背景 + ズーム前景 + 最後 CTA
    cta = "DOUBLE TAP IF YOU LOVE HOKKAIDO"
    brand = "@beautiful_hokkaido.jp"

    text_filters = ""
    if font:
        # CTA (6s-8s): 下中央、矢印は右端のハートに向ける
        text_filters = (
            f",drawtext=fontfile='{font}':text='{cta}':fontsize=52:fontcolor=white:"
            f"borderw=5:bordercolor=black@0.8:x=(w-text_w)/2:y=h-260:"
            f"enable='between(t,6,8)'"
            f",drawtext=fontfile='{font}':text='->':fontsize=72:fontcolor=white:"
            f"borderw=5:bordercolor=black@0.8:x=w-150:y=(h-text_h)/2:"
            f"enable='between(t,6,8)'"
            # 常時表示: 下にハンドル
            f",drawtext=fontfile='{font}':text='{brand}':fontsize=36:fontcolor=white:"
            f"borderw=3:bordercolor=black@0.7:x=(w-text_w)/2:y=h-120"
        )

    vf = (
        # 背景: ぼかし拡大
        f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{REEL_H},gblur=sigma=20[bg];"
        # 前景: 画像をゆっくりズーム（scale の時変数で代替、zoompan 回避）
        f"[0:v]scale='min({REEL_W},iw*(1+t*0.03))':'-1':eval=frame[fg];"
        # 合成
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={REEL_FPS}{text_filters}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(REEL_DURATION_SEC), "-i", str(src),
        "-filter_complex", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(REEL_FPS),
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    print(f"  [kenburns] running ffmpeg...", flush=True)
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg kenburns timed out (>120s)")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg kenburns failed: {e.stderr.decode(errors='replace')[-500:]}") from e
    print(f"  [kenburns] OK -> {dst.name}", flush=True)
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


def process_and_host(url: str, as_reel: bool = False) -> tuple[str, str]:
    """ソース URL を整形→Cloudinary 保存し (media_type, public_url) を返す。

    - 動画入力: 常に 9:16 Reels として扱う
    - 静止画入力 + as_reel=False: 4:5 フィード画像
    - 静止画入力 + as_reel=True: Ken Burns 効果で 9:16 Reels 動画化
    """
    local = _download(url)
    if _is_video(local):
        normalized = _fit_video_9x16(local)
        return "VIDEO", _upload(normalized, "video")
    if as_reel:
        normalized = _image_to_reel_kenburns(local)
        return "VIDEO", _upload(normalized, "video")
    normalized = _fit_image_4x5(local)
    return "IMAGE", _upload(normalized, "image")
