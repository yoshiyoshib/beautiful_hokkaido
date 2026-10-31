"""beautiful_hokkaido オーケストレーター CLI。

使い方:
    python main.py --mode auto_source # Unsplashから新規候補を発見→Gemini判定→Approved行を自動追加
    python main.py --mode evaluate    # 既存Pending行をGeminiで判定
    python main.py --mode publish     # 時間到来の Approved を 1 件投稿
    python main.py --mode init_sheet  # 1 行目にカラムヘッダーを書き込む
"""
from __future__ import annotations

import argparse
import sys
import traceback

import config
from modules import (
    asset_processor,
    evaluator,
    ig_publisher,
    insights_collector,
    sheet_manager,
    token_monitor,
    unsplash_source,
)


def run_init_sheet() -> int:
    sheet_manager.ensure_header()
    print("Header written.")
    return 0


def run_auto_source() -> int:
    """Unsplashから候補取得→Gemini判定→AUTO_APPROVE分だけApproved行として追加。"""
    photos = unsplash_source.discover(
        config.UNSPLASH_QUERIES,
        per_query=config.UNSPLASH_PER_QUERY,
        order_by=config.UNSPLASH_ORDER_BY,
    )
    existing = sheet_manager.fetch_existing_ids()
    candidates = [p for p in photos if f"unsplash_{p['id']}" not in existing]
    print(f"[auto_source] fetched={len(photos)} new={len(candidates)} queries={config.UNSPLASH_QUERIES}")

    approved_count = 0
    evaluated_count = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3

    for p in candidates:
        if approved_count >= config.AUTO_SOURCE_MAX_APPROVE:
            print(f"  reached AUTO_SOURCE_MAX_APPROVE={config.AUTO_SOURCE_MAX_APPROVE}, stopping")
            break
        if evaluated_count >= config.AUTO_SOURCE_MAX_EVAL:
            print(f"  reached AUTO_SOURCE_MAX_EVAL={config.AUTO_SOURCE_MAX_EVAL}, stopping")
            break
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            print(f"  [auto_source] {consecutive_failures} consecutive evaluator failures -> aborting, retry later")
            break

        evaluated_count += 1
        print(f"[auto_source] evaluating {p['id']} by @{p['author_handle']} ({evaluated_count}/{config.AUTO_SOURCE_MAX_EVAL})")
        try:
            result = evaluator.evaluate(p["url"])
            consecutive_failures = 0
        except Exception as e:  # noqa: BLE001
            consecutive_failures += 1
            print(f"  evaluate failed ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}")
            continue

        verdict = evaluator.classify_verdict(result)
        location = (result.get("location_guess") or "").strip()
        print(
            f"  verdict={verdict} aesthetic={result.get('aesthetic_score')} "
            f"relevance={result.get('relevance_score')} loc={location!r}"
        )
        if verdict != "AUTO_APPROVE":
            continue

        caption = evaluator.build_final_caption(
            result, p["author_handle"], location=location, seed=p["id"]
        )
        caption += unsplash_source.build_credit_tail(p)

        row_id = f"unsplash_{p['id']}"
        new_row = sheet_manager.append_row(
            id=row_id,
            url=p["url"],
            author=p["author_handle"],
            status="Approved",
            location=location,
            caption=caption,
        )
        approved_count += 1
        print(f"  -> added row {new_row} as Approved")

    print(f"[auto_source] done. new_approved={approved_count}")
    return 0


def run_evaluate() -> int:
    pending = sheet_manager.fetch_pending()
    if not pending:
        print("No Pending rows.")
        return 0

    for row_idx, row in pending:
        url = (row.get("Original_URL") or "").strip()
        author = (row.get("Author_Handle") or "").strip()
        if not url:
            print(f"[evaluate] row={row_idx} skip (no URL)")
            sheet_manager.mark_error(row_idx, "Missing Original_URL")
            continue
        print(f"[evaluate] row={row_idx} url={url}")
        try:
            result = evaluator.evaluate(url)
            verdict = evaluator.classify_verdict(result)
            location = (result.get("location_guess") or "").strip()
            caption = evaluator.build_final_caption(result, author)
            status = {
                "AUTO_APPROVE": "Approved",
                "REVIEW": "Pending",
                "REJECT": "Rejected",
            }.get(verdict, "Pending")
            sheet_manager.update_evaluation(row_idx, status, location, caption)
            print(
                f"  verdict={verdict} status={status} "
                f"aesthetic={result.get('aesthetic_score')} "
                f"relevance={result.get('relevance_score')} "
                f"loc={location!r}"
            )
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            sheet_manager.mark_error(row_idx, str(e))
    return 0


def run_publish(as_reel: bool = False) -> int:
    row_idx, row = sheet_manager.fetch_due_approved()
    if row_idx is None:
        print("No due Approved row.")
        return 0

    url = (row.get("Original_URL") or "").strip()
    caption = (row.get("Generated_Caption") or "").strip()
    location = (row.get("Location") or "").strip()
    # alt_text はキャプションの英語部分の先頭2文を切り出し
    alt_text = ""
    if caption:
        head = caption.split("\n\n")[0]
        alt_text = head[:400]

    print(f"[publish] row={row_idx} url={url} as_reel={as_reel}")
    try:
        media_type, public_url = asset_processor.process_and_host(url, as_reel=as_reel)
        sheet_manager.set_public_media(row_idx, public_url)
        print(f"  hosted -> {public_url} ({media_type})")

        location_id = ig_publisher.search_location_id(location) if location else None
        if location_id:
            print(f"  location_id={location_id}")

        ig_post_id = ig_publisher.post_media(
            media_type, public_url, caption,
            alt_text=alt_text,
            location_id=location_id or "",
            share_story=True,
        )
        sheet_manager.mark_posted(row_idx, ig_post_id)
        print(f"  posted -> IG id={ig_post_id}")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        sheet_manager.mark_error(row_idx, str(e))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="beautiful_hokkaido orchestrator")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "auto_source", "evaluate", "publish", "publish_reel",
            "init_sheet", "check_token", "collect_insights",
        ],
    )
    args = parser.parse_args()

    if args.mode == "init_sheet":
        return run_init_sheet()
    if args.mode == "auto_source":
        return run_auto_source()
    if args.mode == "evaluate":
        return run_evaluate()
    if args.mode == "check_token":
        return token_monitor.monitor()
    if args.mode == "collect_insights":
        return insights_collector.collect()
    if args.mode == "publish_reel":
        return run_publish(as_reel=True)
    return run_publish()


if __name__ == "__main__":
    sys.exit(main())
