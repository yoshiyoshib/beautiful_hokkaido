"""場所・季節・フィーチャータグを混合してハッシュタグ文字列を動的生成。

目的:
- スパム判定回避（毎回同じタグを使わない）
- 発見経路の多様化（大/中/ニッチ/季節/言語を混ぜる）
- フィーチャーアカウントの公式タグに乗って repost 期待
"""
from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import config

# 大手(10M+): 競争激しいが導線
BIG_POOL = [
    "#japan", "#travel", "#nature", "#photography", "#landscape",
]

# 中位(100k-1M): 日本旅行コア層
MID_POOL = [
    "#visitjapan", "#japantravel", "#japanlandscape", "#japantrip",
    "#explorejapan", "#beautifuljapan", "#japan_photo",
    "#traveljapan", "#japanlovers", "#japan_vacations",
]

# ニッチ・北海道（10k-100k）
NICHE_POOL = [
    "#hokkaido", "#hokkaidotravel", "#hokkaidotrip", "#hokkaidonature",
    "#hokkaidogram", "#hokkaidophoto", "#visithokkaido",
]

# フィーチャーアカウント公式タグ（repost狙い）
FEATURE_POOL = [
    "#visitjapanjp", "#discoverhokkaido", "#gltjp", "#tokyocameraclub",
    "#voyaged", "#discover_earth",
]

# 日本語（日本人フォロワー獲得）
JP_POOL = [
    "#北海道", "#北海道旅行", "#北海道絶景", "#日本の絶景", "#風景写真",
    "#絶景", "#旅行好きな人と繋がりたい",
]

# 北海道野生動物（content_type=wildlife 時に追加）
WILDLIFE_POOL = [
    "#hokkaidowildlife", "#japanesewildlife", "#hokkaidoanimals",
    "#北海道の動物", "#野生動物", "#wildlifephotography",
    "#endemicspecies",
]

SPECIES_SPECIFIC = {
    "crane": ["#redcrownedcrane", "#tancho", "#タンチョウ"],
    "fox": ["#ezofox", "#kitakitsune", "#キタキツネ", "#北きつね"],
    "deer": ["#ezoshika", "#sikadeer", "#エゾシカ"],
    "bear": ["#brownbear", "#higuma", "#ヒグマ"],
    "owl": ["#blakistonsowl", "#shimafukurou", "#シマフクロウ"],
    "squirrel": ["#ezosquirrel", "#エゾリス"],
    "eagle": ["#stellerseagle", "#whitetailedeagle", "#オオワシ", "#オジロワシ"],
    "otter": ["#seaotter", "#rakko", "#ラッコ"],
    "pika": ["#hokkaidopika", "#エゾナキウサギ"],
    "seal": ["#spottedseal", "#アザラシ"],
}

# 場所別ニッチ（キーは location の部分一致でマッチ）
LOCATION_SPECIFIC = {
    "biei": ["#biei", "#bieibluepond", "#patchworkroad", "#美瑛"],
    "otaru": ["#otaru", "#otarucanal", "#小樽運河", "#小樽"],
    "sapporo": ["#sapporo", "#sapporocity", "#札幌", "#すすきの"],
    "furano": ["#furano", "#furanolavender", "#富良野", "#ラベンダー"],
    "hakodate": ["#hakodate", "#hakodatenightview", "#函館", "#函館山"],
    "shiretoko": ["#shiretoko", "#shiretokonationalpark", "#知床"],
    "niseko": ["#niseko", "#nisekopowder", "#ニセコ"],
    "lake toya": ["#laketoya", "#toyako", "#洞爺湖"],
    "noboribetsu": ["#noboribetsu", "#登別温泉", "#登別"],
    "asahikawa": ["#asahikawa", "#旭川"],
    "kushiro": ["#kushiro", "#釧路"],
    "wakkanai": ["#wakkanai", "#稚内"],
}


def _season_tags() -> list[str]:
    month = datetime.now(ZoneInfo(config.TIMEZONE)).month
    if month in (12, 1, 2):
        return ["#hokkaidowinter", "#snowlandscape", "#北海道の冬", "#雪景色"]
    if month in (3, 4, 5):
        return ["#hokkaidospring", "#cherryblossom", "#北海道の春", "#桜"]
    if month in (6, 7, 8):
        return ["#hokkaidosummer", "#lavenderfields", "#北海道の夏", "#ラベンダー"]
    return ["#hokkaidoautumn", "#autumnleaves", "#北海道の秋", "#紅葉"]


def _location_specific(location: str) -> list[str]:
    key = (location or "").lower()
    for k, tags in LOCATION_SPECIFIC.items():
        if k in key:
            return list(tags)
    return []


def _species_specific(subject_detail: str) -> list[str]:
    key = (subject_detail or "").lower()
    out: list[str] = []
    for k, tags in SPECIES_SPECIFIC.items():
        if k in key:
            out += tags
    return out


def _sample(pool: list[str], n: int, seed: random.Random) -> list[str]:
    n = min(n, len(pool))
    return seed.sample(pool, n) if n > 0 else []


def build_hashtags(
    location: str = "",
    content_type: str = "",
    subject_detail: str = "",
    unique_seed: str = "",
) -> str:
    """混合ハッシュタグ文字列を返す。unique_seed で日次ローテ。"""
    rng = random.Random(unique_seed or datetime.now(ZoneInfo(config.TIMEZONE)).isoformat())

    tags: list[str] = []
    tags += _location_specific(location)[:4]      # 場所別4
    tags += _sample(NICHE_POOL, 4, rng)           # 北海道ニッチ4
    tags += _sample(MID_POOL, 4, rng)             # 日本旅行中位4
    tags += _sample(FEATURE_POOL, 3, rng)         # フィーチャー3
    tags += _season_tags()[:3]                    # 季節3
    tags += _sample(JP_POOL, 4, rng)              # 日本語4
    tags += _sample(BIG_POOL, 3, rng)             # 大手3

    if content_type == "wildlife":
        tags += _sample(WILDLIFE_POOL, 4, rng)    # 野生動物4
        tags += _species_specific(subject_detail)[:3]  # 種別3

    # 重複除去（順序維持）
    seen: set[str] = set()
    uniq = []
    for t in tags:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            uniq.append(t)

    return " ".join(uniq[:28])  # Instagram 上限30、安全マージン
