"""Vision LLM による北海道風景の品質・テーマ判定とバイリンガルキャプション生成。

優先順位: Gemini（主）→ Groq Llama 4 Scout（Gemini 503 時のフォールバック）→ 残り Gemini 旧版。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import requests
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config

PROVIDER_CHAIN: list[tuple[str, str]] = [
    ("gemini",   "gemini-3.5-flash"),
    ("groq_url", "qwen/qwen3.8-27b"),
    ("gemini",   "gemini-flash-latest"),
    ("gemini",   "gemini-3.8-flash"),
    ("gemini",   "gemini-3.7-flash"),
]

HTTP_HEADERS = {
    "User-Agent": "beautiful_hokkaido/0.1 (+https://github.com/beautiful-hokkaido)",
    "Accept": "image/*,*/*;q=0.8",
}


PROMPT = """You are the art director of a premium Hokkaido travel curation Instagram account.

Evaluate the attached image strictly. Return ONLY valid JSON - no markdown fences, no commentary.

JSON schema (all keys required):
{
  "relevance_score": <int 0-10 - how well it fits Hokkaido>,
  "aesthetic_score": <int 0-10 - composition, exposure, color, pro-level quality>,
  "quality_pass": <true | false - false if selfie, flyer, text-heavy ad, blurry, low resolution, broken image, large watermark covering subject>,
  "content_type": "<one of: 'landscape', 'wildlife', 'cityscape', 'food', 'other'>",
  "location_guess": "<e.g. 'Biei, Hokkaido', 'Otaru Canal', 'Shiretoko Peninsula'; use 'Unknown, Hokkaido' when uncertain>",
  "subject_detail": "<if content_type='wildlife', name the species in English + Japanese e.g. 'Red-crowned Crane (タンチョウ)'; empty otherwise>",
  "caption_en": "<engaging English caption, 2-4 sentences, evocative travel-magazine tone, NO hashtags, NO author credit>",
  "caption_ja": "<attractive Japanese caption 2-3 sentences, no hashtags, no credit>",
  "alt_text": "<concise accessibility description, 1-2 sentences, factual, under 100 words>",
  "verdict": "<AUTO_APPROVE | REVIEW | REJECT>"
}

What counts as HIGH relevance (>=8) for Hokkaido:
- Landscapes: snow fields, lavender, autumn foliage, drift ice, mountains, blue pond, hills, coasts, famous spots
- Hokkaido-native wildlife: Red-crowned Crane (タンチョウ), Blakiston's Fish Owl (シマフクロウ), Ezo Red Fox (キタキツネ), Ezo Sika Deer (エゾシカ), Brown Bear (ヒグマ), Hokkaido Squirrel (エゾリス), White-tailed/Steller's Eagle, Hokkaido Pika (エゾナキウサギ), sea otter, seals around Hokkaido
- Iconic cityscapes: Sapporo clock tower, Otaru canal lamps, Hakodate night view
- Cultural/seasonal: Sapporo Snow Festival, Soranuma falls

Verdict rules:
- "AUTO_APPROVE" ONLY if aesthetic_score>=8 AND relevance_score>=8 AND quality_pass is true.
- "REJECT" if quality_pass is false OR either score is < 5.
- Otherwise "REVIEW".
"""


# ---------- image loading ----------

def _load_image_bytes(src: str) -> tuple[bytes, str]:
    if src.startswith(("http://", "https://")):
        r = requests.get(src, timeout=30, headers=HTTP_HEADERS)
        r.raise_for_status()
        mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        return r.content, mime
    p = Path(src)
    data = p.read_bytes()
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    return data, mime


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in LLM output:\n{text}")
    return json.loads(m.group(0))


# ---------- Gemini provider ----------

_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


def _call_gemini(model: str, data: bytes, mime: str) -> dict:
    client = _get_gemini_client()
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=data, mime_type=mime),
            PROMPT,
        ],
    )
    return _extract_json(resp.text)


# ---------- Groq provider ----------

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        from groq import Groq
        _groq_client = Groq(api_key=config.GROQ_API_KEY)
    return _groq_client


def _call_groq_url(model: str, url: str) -> dict:
    """Groq Qwen は URL 方式でのみ画像を受け付ける（Groq サーバがダウンロード）。"""
    client = _get_groq_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    text = resp.choices[0].message.content or ""
    return _extract_json(text)


# ---------- public API ----------

def evaluate(image_src: str) -> dict:
    """画像を Vision LLM に送って判定 JSON を返す。プロバイダ横断フォールバック。

    - Gemini は bytes (base64) で送る
    - Groq (Qwen) は URL で送る（Groq サーバ側がダウンロード）
    - 入力が URL でない場合、Groq プロバイダはスキップされる
    """
    is_url = image_src.startswith(("http://", "https://"))
    data: bytes | None = None
    mime: str | None = None
    last_error: Exception | None = None

    for provider, model in PROVIDER_CHAIN:
        try:
            if provider == "gemini":
                if data is None:
                    data, mime = _load_image_bytes(image_src)
                return _call_gemini(model, data, mime)
            if provider == "groq_url":
                if not is_url:
                    print(f"  [evaluator] {provider}:{model}: skip (local file)")
                    continue
                return _call_groq_url(model, image_src)
        except genai_errors.ServerError as e:
            last_error = e
            print(f"  [evaluator] {provider}:{model}: ServerError -> next")
        except genai_errors.ClientError as e:
            last_error = e
            print(f"  [evaluator] {provider}:{model}: ClientError -> next")
        except RuntimeError as e:
            last_error = e
            print(f"  [evaluator] {provider}:{model}: {e} -> next")
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"  [evaluator] {provider}:{model}: {type(e).__name__}: {str(e)[:120]} -> next")

    raise RuntimeError(f"All vision providers failed. Last error: {last_error}")


def classify_verdict(result: dict, relaxed: bool = False) -> str:
    """閾値を自前チェックして verdict を上書き（LLMの暴走を抑える安全装置）。

    relaxed=True のとき、AUTO_SOURCE_FALLBACK_* の緩和閾値を使う。
    auto_source が通常閾値で 0 件になった時の救済用。
    """
    try:
        aesthetic = int(result.get("aesthetic_score", 0))
        relevance = int(result.get("relevance_score", 0))
    except (TypeError, ValueError):
        return "REVIEW"
    if not result.get("quality_pass", False):
        return "REJECT"
    if aesthetic < 5 or relevance < 5:
        return "REJECT"
    min_a = config.AUTO_SOURCE_FALLBACK_MIN_AESTHETIC if relaxed else config.MIN_AESTHETIC_SCORE
    min_r = config.AUTO_SOURCE_FALLBACK_MIN_RELEVANCE if relaxed else config.MIN_RELEVANCE_SCORE
    if aesthetic >= min_a and relevance >= min_r:
        return "AUTO_APPROVE"
    return "REVIEW"


CTA_ROTATION = [
    "❤️ Double tap if you'd visit here!",
    "❤️ Save this for your next Hokkaido trip!",
    "❤️ Tap the heart if this made you smile 😊",
    "✨ Follow @beautiful_hokkaido.jp for daily Hokkaido magic",
    "❤️ Which season of Hokkaido do you love most?",
    "📍 Tag someone you'd take here!",
    "❤️ Which place in Hokkaido is on your bucket list?",
]


def build_final_caption(result: dict, author_handle: str, location: str = "", seed: str = "") -> str:
    from modules import hashtag_strategy  # 遅延 import で循環回避

    en = (result.get("caption_en") or "").strip()
    ja = (result.get("caption_ja") or "").strip()
    loc = (location or result.get("location_guess") or "").strip()
    content_type = (result.get("content_type") or "").strip()
    subject = (result.get("subject_detail") or "").strip()

    # CTA 冒頭: seed（Unsplash photo id等）でローテ→同じ投稿なら一貫
    import hashlib
    idx = int(hashlib.md5((seed or loc).encode()).hexdigest(), 16) % len(CTA_ROTATION)
    cta = CTA_ROTATION[idx]

    handle = (author_handle or "").lstrip("@").strip()
    credit = f"\n\n📷 Photo by @{handle}" if handle else ""

    tags = hashtag_strategy.build_hashtags(
        location=loc, content_type=content_type, subject_detail=subject,
        unique_seed=seed,
    )
    tags_block = f"\n\n{tags}" if tags else ""

    body = en if not ja else f"{en}\n\n{ja}"
    return f"{cta}\n\n{body}{credit}{tags_block}"
