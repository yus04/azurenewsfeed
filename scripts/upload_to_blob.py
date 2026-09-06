#!/usr/bin/env python3
"""
Azure News Feed - Azure Blob Storage Uploader
Takes the staged article records produced by fetch_feeds.py, normalizes them
into the Azure Blob Storage JSON format (one file per article), deduplicates
against what is already stored in the container, and uploads any new
articles.

This does NOT replace or modify the existing Azure Feed site data
(data/feeds.json, data/feed.xml, data/teleprompter/). It is a purely
additive output aimed at downstream systems (e.g. GPT-based Japanese
summarization/tagging).
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings

STAGING_PATH = os.path.join("data", ".blob_staging.json")
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER", "articles")

# Query string parameters that are stripped during URL normalization because
# they do not identify the article (tracking/marketing parameters).
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "wt.mc_id"}

# Bound id-based dedup lookups to this many trailing days. Articles older
# than this are already excluded upstream by fetch_feeds.py's 30-day
# retention window, so a candidate article can never have first been
# uploaded outside this range.
DEDUP_LOOKBACK_DAYS = 31


def normalize_url(url):
    """Normalize a URL so the same article always yields the same id.

    - lowercases scheme and host
    - removes the URL fragment
    - removes tracking query parameters (utm_*, fbclid, gclid, ...)
    - sorts remaining query parameters
    - strips a trailing slash from the path
    """
    if not url:
        return ""

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or ""

    kept_params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in TRACKING_PARAMS:
            continue
        if any(lower_key.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
            continue
        kept_params.append((key, value))
    kept_params.sort()
    query = urlencode(kept_params)

    return urlunsplit((scheme, netloc, path, query, ""))


def generate_article_id(url):
    """Generate a stable article id: sha256 of the normalized URL."""
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_article(raw_article, collected_at):
    """Convert a staged raw article record into the Blob Storage JSON schema."""
    url = raw_article.get("link", "")
    if not url:
        raise ValueError(
            f"Cannot generate a stable id for article without a URL: {raw_article!r}"
        )
    article_id = generate_article_id(url)
    return {
        "id": article_id,
        "title": raw_article.get("title") or "Untitled",
        "source": raw_article.get("source", ""),
        "author": raw_article.get("author") or None,
        "publishedAt": raw_article.get("published") or None,
        "url": url,
        "summary": raw_article.get("summary") or None,
        "content": raw_article.get("content") or "",
        "images": raw_article.get("images") or [],
        "category": raw_article.get("category") or "Specialized",
        "collectedAt": collected_at,
    }


def blob_path_for(article):
    """Build the raw/articles/YYYY/MM/DD/{id}.json blob path."""
    collected_at = article["collectedAt"]
    dt = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    return f"{ARTICLES_PREFIX}{dt.strftime('%Y/%m/%d')}/{article['id']}.json"


def load_staged_articles(path=STAGING_PATH):
    if not os.path.exists(path):
        print(f"No staged articles found at {path}, nothing to upload.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_container_client():
    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise RuntimeError(
            "AZURE_STORAGE_CONNECTION_STRING environment variable is not set."
        )

    service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = service_client.get_container_client(CONTAINER_NAME)
    try:
        container_client.create_container()
        print(f"Created container '{CONTAINER_NAME}'")
    except ResourceExistsError:
        pass
    return container_client


ARTICLES_PREFIX = "raw/articles/"


def _recent_day_prefixes(days=DEDUP_LOOKBACK_DAYS, now=None):
    """Build one raw/articles/YYYY/MM/DD/ prefix per day in the lookback window."""
    now = now or datetime.now(timezone.utc)
    return [
        (now - timedelta(days=offset)).strftime(ARTICLES_PREFIX + "%Y/%m/%d/")
        for offset in range(days)
    ]


def list_existing_article_ids(container_client):
    """List ids of articles already stored under the recent date-partitioned paths.

    Blob paths are date-partitioned (raw/articles/YYYY/MM/DD/{id}.json), but
    the article id itself is stable per URL regardless of the date it was
    first collected on. To guarantee an article is never uploaded twice -
    even if it keeps showing up in the feed across multiple daily runs - we
    dedupe against every id already present under any day in the lookback
    window, not just the exact date-based path we would write to on this
    run. The lookback window matches fetch_feeds.py's 30-day article
    retention, since a candidate article can never have first been
    collected outside that range, which keeps this bounded instead of
    listing the entire (ever-growing) container.
    """
    existing_ids = set()
    for prefix in _recent_day_prefixes():
        for blob in container_client.list_blobs(name_starts_with=prefix):
            filename = blob.name.rsplit("/", 1)[-1]
            if filename.endswith(".json"):
                existing_ids.add(filename[: -len(".json")])
    return existing_ids


def upload_articles(container_client, articles):
    """Upload one blob per article, skipping ids that already exist anywhere in the container."""
    uploaded = 0
    skipped = 0
    failed = []

    existing_ids = list_existing_article_ids(container_client)

    for article in articles:
        if article["id"] in existing_ids:
            skipped += 1
            continue

        blob_path = blob_path_for(article)
        blob_client = container_client.get_blob_client(blob_path)

        try:
            payload = json.dumps(article, indent=2, ensure_ascii=False)
            blob_client.upload_blob(
                payload,
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
            uploaded += 1
            existing_ids.add(article["id"])
            print(f"  Uploaded {blob_path}")
        except ResourceExistsError:
            # Another concurrent run already created this blob; treat as a
            # duplicate rather than a failure.
            skipped += 1
            existing_ids.add(article["id"])
        except Exception as e:
            failed.append((blob_path, str(e)))
            print(f"  Error uploading {blob_path}: {e}")

    return uploaded, skipped, failed


def main():
    print("=" * 60)
    print("Azure News Feed - Uploading Articles to Azure Blob Storage")
    print("=" * 60)

    collected_at = datetime.now(timezone.utc).isoformat()

    raw_articles = load_staged_articles()
    if not raw_articles:
        print("No articles to process. Exiting successfully.")
        return

    articles = []
    for raw_article in raw_articles:
        if not raw_article.get("link"):
            print(f"  Skipping article without a URL: {raw_article.get('title')!r}")
            continue
        articles.append(normalize_article(raw_article, collected_at))

    if not articles:
        print("No valid articles to process. Exiting successfully.")
        return

    container_client = get_container_client()
    uploaded, skipped, failed = upload_articles(container_client, articles)

    print(f"\n{'=' * 60}")
    print(
        f"Done! {uploaded} new article(s) uploaded, {skipped} already existed "
        f"(skipped), {len(failed)} failed."
    )
    print(f"{'=' * 60}")

    if failed:
        for blob_path, error in failed:
            print(f"FAILED: {blob_path}: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
