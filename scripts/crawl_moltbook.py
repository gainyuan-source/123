#!/usr/bin/env python3
"""Crawl Moltbook posts and detailed discussions to local JSON files."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


DEFAULT_BASE_URL = "https://www.moltbook.com"
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 2.0


def build_url(base_url: str, path: str, params: Optional[Dict[str, Any]] = None) -> str:
    base = base_url.rstrip("/")
    url = f"{base}{path}"
    if params:
        query = urllib.parse.urlencode(params)
        return f"{url}?{query}"
    return url


def fetch_json(url: str, timeout: int, retries: int, backoff: float) -> Dict[str, Any]:
    headers = {"User-Agent": "moltbook-crawler/1.0 (+https://www.moltbook.com)"}
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except urllib.error.HTTPError as error:
            if error.code == 429 or 500 <= error.code < 600:
                if attempt >= retries:
                    raise
                sleep_for = backoff * (attempt + 1)
                time.sleep(sleep_for)
                continue
            raise
        except (urllib.error.URLError, json.JSONDecodeError):
            if attempt >= retries:
                raise
            sleep_for = backoff * (attempt + 1)
            time.sleep(sleep_for)
    raise RuntimeError(f"Failed to fetch {url}")


def iter_posts(
    base_url: str,
    page_size: int,
    start_offset: int,
    timeout: int,
    retries: int,
    backoff: float,
) -> Iterable[Tuple[Dict[str, Any], int, int]]:
    offset = start_offset
    total = None
    while True:
        url = build_url(base_url, "/api/v1/posts", {"limit": page_size, "offset": offset})
        data = fetch_json(url, timeout=timeout, retries=retries, backoff=backoff)
        posts = data.get("posts", [])
        total = data.get("count", total)
        if not posts:
            break
        for post in posts:
            yield post, offset, total or 0
        offset += len(posts)
        if total is not None and offset >= total:
            break


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def crawl_posts(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.jsonl"

    processed = 0
    skipped = 0

    with index_path.open("a", encoding="utf-8") as index_file:
        for post, offset, total in iter_posts(
            base_url=args.base_url,
            page_size=args.page_size,
            start_offset=args.offset,
            timeout=args.timeout,
            retries=args.retries,
            backoff=args.backoff,
        ):
            if args.max_posts is not None and processed >= args.max_posts:
                break

            post_id = post.get("id")
            if not post_id:
                continue
            detail_path = output_dir / f"post_{post_id}.json"
            if args.resume and detail_path.exists():
                skipped += 1
                continue

            detail_url = build_url(args.base_url, f"/api/v1/posts/{post_id}")
            detail = fetch_json(
                detail_url, timeout=args.timeout, retries=args.retries, backoff=args.backoff
            )
            write_json(detail_path, detail)

            index_record = {
                "id": post_id,
                "title": post.get("title"),
                "submolt": post.get("submolt"),
                "detail_path": str(detail_path),
                "offset": offset,
                "total": total,
            }
            index_file.write(json.dumps(index_record, ensure_ascii=False) + "\n")
            processed += 1

            if args.delay:
                time.sleep(args.delay)

    print(f"Done. Processed={processed} Skipped={skipped} Output={output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl Moltbook posts and detailed discussions to JSON files."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL for Moltbook")
    parser.add_argument(
        "--output-dir",
        default="data/moltbook",
        help="Directory to store downloaded post JSON",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Page size")
    parser.add_argument("--offset", type=int, default=0, help="Start offset for posts")
    parser.add_argument(
        "--max-posts", type=int, default=None, help="Stop after this many posts"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay (seconds) between post detail requests",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Request timeout (seconds)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retry count for failed requests",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=DEFAULT_BACKOFF,
        help="Backoff multiplier for retries",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip posts with existing JSON files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl_posts(args)


if __name__ == "__main__":
    main()
