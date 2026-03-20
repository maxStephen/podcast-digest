"""
handler.py
Lambda entry point — orchestrates the full morning podcast digest pipeline.

Flow:
    1. Load config from S3
    2. For each podcast (ordered by priority):
        a. Fetch new episodes from RSS
        b. For each episode: get transcript, summarize, apply Pocket Casts action
        c. On error: log, skip show, update error state in config
    3. Build digest structure
    4. Write manifest to S3 (for Apple Shortcut feedback menus)
    5. Deliver to OneNote and SES in parallel
    6. Update config state (last_summarized, error counts) in S3
    7. Flush run log
"""

import os
import time
import boto3
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import config as cfg
from fetcher import fetch_episodes, get_feed_image
from transcriber import get_transcript, source_label
from summarizer import summarize_episode, summarize_backcatalogue
from delivery_onenote import deliver as deliver_onenote
from delivery_ses import deliver as deliver_ses
from pocket_casts import apply_action
from utils import CostTracker, RunLogger

s3 = boto3.client("s3")

BUCKET = os.environ["S3_BUCKET"]
LOG_KEY = os.environ["LOG_KEY"]


# ── Lambda entry point ─────────────────────────────────────────────────────────

def lambda_handler(event: dict, context) -> dict:
    start_time = time.time()
    cost_tracker = CostTracker()
    run_logger = RunLogger(s3, BUCKET, LOG_KEY)

    try:
        config = cfg.load_config()
    except Exception as e:
        return _fatal(f"Failed to load config from S3: {e}")

    podcasts = cfg.get_podcasts(config)
    digest_shows = []
    episodes_by_show = {}

    for podcast in podcasts:
        show_result = _process_show(podcast, cost_tracker, run_logger)
        digest_shows.append(show_result)
        if show_result.get("episodes"):
            episodes_by_show[podcast["name"]] = [
                {"title": ep["title"], "published": ep["published"]}
                for ep in show_result["episodes"]
            ]

    digest = {
        "date": _format_date(date.today()),
        "shows": digest_shows,
    }

    cfg.write_manifest(config, episodes_by_show)

    _deliver(digest, cost_tracker)

    _update_config(config, digest_shows)
    cfg.save_config(config)

    duration = time.time() - start_time
    run_logger.flush(cost_tracker, duration)

    return {
        "statusCode": 200,
        "body": f"Digest complete in {duration:.1f}s — cost ${cost_tracker.total_cost:.4f}",
    }


# ── Show processor ─────────────────────────────────────────────────────────────

def _process_show(podcast: dict, cost_tracker: CostTracker, run_logger: RunLogger) -> dict:
    """
    Process a single podcast show. Returns a show dict for the digest.
    Catches all exceptions — errors are logged and the show is skipped.
    """
    name = podcast["name"]
    cover_art = None

    try:
        cover_art = get_feed_image(podcast)
        episodes = fetch_episodes(podcast)

        if not episodes:
            run_logger.log_skipped(name)
            return {
                "name": name,
                "cover_art": cover_art,
                "episodes": [],
                "no_new_episodes": True,
                "last_summarized": podcast.get("last_summarized", "never"),
                "error": None,
            }

        is_backcatalogue = podcast.get("last_summarized") == "never"

        if is_backcatalogue:
            processed = _process_backcatalogue(episodes, podcast, cost_tracker)
        else:
            processed = _process_episodes(episodes, podcast, cost_tracker)

        run_logger.log_processed(name, len(processed))

        return {
            "name": name,
            "cover_art": cover_art,
            "episodes": processed,
            "no_new_episodes": False,
            "last_summarized": podcast.get("last_summarized", "never"),
            "error": None,
        }

    except Exception as e:
        error_msg = str(e)
        cfg.mark_error(podcast, error_msg)
        run_logger.log_error(name, error_msg)

        return {
            "name": name,
            "cover_art": cover_art,
            "episodes": [],
            "no_new_episodes": False,
            "last_summarized": podcast.get("last_summarized", "never"),
            "error": error_msg,
            "error_consecutive_days": podcast.get("error_consecutive_days", 0),
            "error_cumulative_days_this_year": podcast.get("error_cumulative_days_this_year", 0),
        }


# ── Episode processors ─────────────────────────────────────────────────────────

def _process_episodes(episodes: list, podcast: dict, cost_tracker: CostTracker) -> list:
    """Summarize each episode individually."""
    processed = []
    for episode in episodes:
        transcript, source_used = get_transcript(episode, podcast, cost_tracker)
        summary = summarize_episode(episode, transcript, podcast, cost_tracker)

        try:
            apply_action(episode, podcast)
        except Exception as e:
            print(f"Pocket Casts action failed for {episode['title']}: {e}")

        processed.append({
            **episode,
            "summary": summary,
            "transcript_source": source_used,
            "transcript_source_label": source_label(source_used),
        })

    return processed


def _process_backcatalogue(episodes: list, podcast: dict, cost_tracker: CostTracker) -> list:
    """
    Produce a single rolled-up back-catalogue summary.
    Returns a list with one synthetic episode entry for digest rendering.
    """
    summary = summarize_backcatalogue(episodes[:10], podcast, cost_tracker)

    return [{
        "title": f"Back catalogue — {len(episodes)} episodes",
        "published": f"Through {episodes[-1]['published'] if episodes else 'unknown'}",
        "published_date": episodes[-1]["published_date"] if episodes else None,
        "duration_display": None,
        "overcast_url": None,
        "is_backcatalogue": True,
        "summary": summary,
        "transcript_source": "show_notes_then_whisper",
        "transcript_source_label": "Back catalogue digest",
    }]


# ── Delivery ───────────────────────────────────────────────────────────────────

def _deliver(digest: dict, cost_tracker: CostTracker) -> None:
    """Deliver digest to OneNote and SES in parallel."""
    errors = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(deliver_onenote, digest, cost_tracker): "OneNote",
            executor.submit(deliver_ses, digest, cost_tracker): "SES",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                errors.append(f"{name} delivery failed: {e}")
                print(f"Delivery error — {name}: {e}")

    if errors:
        print(f"Delivery warnings: {errors}")


# ── Config state update ────────────────────────────────────────────────────────

def _update_config(config: dict, digest_shows: list) -> None:
    """
    Update last_summarized and error state for each show
    based on the outcome of this run.
    """
    show_results = {s["name"]: s for s in digest_shows}

    for podcast in config.get("podcasts", []):
        result = show_results.get(podcast["name"])
        if not result:
            continue
        if result.get("error"):
            cfg.mark_error(podcast, result["error"])
        elif not result.get("no_new_episodes"):
            cfg.mark_success(podcast)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_date(d: date) -> str:
    return d.strftime("%A, %B %-d %Y")


def _fatal(message: str) -> dict:
    print(f"FATAL: {message}")
    return {"statusCode": 500, "body": message}