"""Environment-driven configuration for beautiful_hokkaido."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

# --- Google Sheets ---
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", str(BASE_DIR / "service_account.json")
)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "posts")

# --- Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# --- Groq (Gemini のフォールバック) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# --- Cloudinary ---
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

# --- Instagram Graph API ---
IG_USER_ID = os.getenv("IG_USER_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
IG_API_VERSION = os.getenv("IG_API_VERSION", "v21.0")
IG_API_BASE = f"https://graph.facebook.com/{IG_API_VERSION}"

# --- Posting ---
DEFAULT_HASHTAGS = os.getenv(
    "DEFAULT_HASHTAGS",
    "#hokkaido #北海道 #beautifulhokkaido #japan #japantravel",
)
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")

# --- Scoring thresholds (AUTO_APPROVE) ---
MIN_AESTHETIC_SCORE = int(os.getenv("MIN_AESTHETIC_SCORE", "8"))
MIN_RELEVANCE_SCORE = int(os.getenv("MIN_RELEVANCE_SCORE", "8"))

# --- Container polling ---
CONTAINER_MAX_WAIT_SEC = int(os.getenv("CONTAINER_MAX_WAIT_SEC", "180"))

# --- Unsplash (auto source) ---
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_QUERIES = [
    q.strip()
    for q in os.getenv(
        "UNSPLASH_QUERIES",
        "hokkaido,biei,otaru,shiretoko,sapporo,furano,hakodate,niseko,北海道,美瑛,小樽",
    ).split(",")
    if q.strip()
]
UNSPLASH_PER_QUERY = int(os.getenv("UNSPLASH_PER_QUERY", "2"))
UNSPLASH_ORDER_BY = os.getenv("UNSPLASH_ORDER_BY", "relevant")  # "latest" | "relevant"
AUTO_SOURCE_MAX_APPROVE = int(os.getenv("AUTO_SOURCE_MAX_APPROVE", "3"))
AUTO_SOURCE_MAX_EVAL = int(os.getenv("AUTO_SOURCE_MAX_EVAL", "15"))  # 1日の総採点数ハードリミット
