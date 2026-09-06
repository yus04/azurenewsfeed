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
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings

STAGING_PATH = os.path.join("data", ".blob_staging.json")
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER", "articles")

# Query string parameters that are stripped during URL normalization because
# they do not identify the article (tracking/marketing parameters).
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "wt.mc_id"}


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
    return f"raw/articles/{dt.strftime('%Y/%m/%d')}/{article['id']}.json"


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


def upload_articles(container_client, articles):
    """Upload one blob per article, skipping ids that already exist."""
    uploaded = 0
    skipped = 0
    failed = []

    for article in articles:
        blob_path = blob_path_for(article)
        blob_client = container_client.get_blob_client(blob_path)

        try:
            if blob_client.exists():
                skipped += 1
                continue

            payload = json.dumps(article, indent=2, ensure_ascii=False)
            blob_client.upload_blob(
                payload,
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
            uploaded += 1
            print(f"  Uploaded {blob_path}")
        except ResourceExistsError:
            # Another concurrent run already created this blob; treat as a
            # duplicate rather than a failure.
            skipped += 1
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

    articles = [normalize_article(a, collected_at) for a in raw_articles]

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
