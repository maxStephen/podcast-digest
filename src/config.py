"""
config.py
Reads and writes podcasts.json from S3.
Validates schema and provides typed access to podcast parameters.
"""

import json
import os
import boto3
from datetime import date

s3 = boto3.client("s3")

BUCKET = os.environ["S3_BUCKET"]
CONFIG_KEY = os.environ["CONFIG_KEY"]
MANIFEST_KEY = os.environ["MANIFEST_KEY"]

PODCAST_DEFAULTS = {
    "verbosity": 600,
    "quotability": False,
    "transcript_source": "show_notes_then_whisper",
    "max_episode_duration_minutes": None,
    "pocket_casts_action": "none",
    "last_summarized": "never",
    "error_consecutive_days": 0,
    "error_cumulative_days_this_year": 0,
    "last_error_date": None,
    "last_error_message": None,
}

VALID_TRANSCRIPT_SOURCES = {"show_notes", "whisper", "show_notes_then_whisper"}
VALID_POCKET_CASTS_ACTIONS = {"none", "mark_played", "add_to_up_next", "star"}


def load_config() -> dict:
    """Fetch podcasts.json from S3 and return parsed dict."""
    response = s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)
    raw = response["Body"].read().decode("utf-8")
    config = json.loads(raw)
    _validate(config)
    return config


def save_config(config: dict) -> None:
    """Write updated podcasts.json back to S3."""
    s3.put_object(
        Bucket=BUCKET,
        Key=CONFIG_KEY,
        Body=json.dumps(config, indent=2),
        ContentType="application/json",
    )


def get_podcasts(config: dict) -> list:
    """Return podcasts sorted ascending by priority."""
    podcasts = config.get("podcasts", [])
    return sorted(podcasts, key=lambda p: p.get("priority", 999))


def mark_success(podcast: dict) -> None:
    """Update state fields after a successful run for a show."""
    podcast["last_summarized"] = date.today().isoformat()
    podcast["error_consecutive_days"] = 0
    podcast["last_error_date"] = None
    podcast["last_error_message"] = None


def mark_error(podcast: dict, message: str) -> None:
    """Update error tracking fields after a failed run for a show."""
    today = date.today().isoformat()
    last = podcast.get("last_error_date")
    if last != today:
        podcast["error_consecutive_days"] = podcast.get("error_consecutive_days", 0) + 1
        podcast["error_cumulative_days_this_year"] = podcast.get("error_cumulative_days_this_year", 0) + 1
    podcast["last_error_date"] = today
    podcast["last_error_message"] = message


def reset_annual_error_counts(config: dict) -> None:
    """Call once on Jan 1 to reset cumulative error counts for the new year."""
    for podcast in config.get("podcasts", []):
        podcast["error_cumulative_days_this_year"] = 0


def write_manifest(config: dict, episodes_by_show: dict) -> None:
    """Write a lightweight manifest to S3 for the Apple Shortcut feedback menus."""
    manifest = {
        "generated": date.today().isoformat(),
        "shows": [
            {
                "name": p["name"],
                "episodes": episodes_by_show.get(p["name"], []),
            }
            for p in get_podcasts(config)
        ],
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )


def _validate(config: dict) -> None:
    """Raise ValueError if config structure is invalid."""
    if "podcasts" not in config:
        raise ValueError("Config missing podcasts key")
    for i, p in enumerate(config["podcasts"]):
        _require(p, "name", i)
        _require(p, "rss_url", i)
        _require(p, "priority", i)
        src = p.get("transcript_source", PODCAST_DEFAULTS["transcript_source"])
        if src not in VALID_TRANSCRIPT_SOURCES:
            raise ValueError(f"Podcast {i} invalid transcript_source: {src}")
        action = p.get("pocket_casts_action", PODCAST_DEFAULTS["pocket_casts_action"])
        if action not in VALID_POCKET_CASTS_ACTIONS:
            raise ValueError(f"Podcast {i} invalid pocket_casts_action: {action}")
        for key, default in PODCAST_DEFAULTS.items():
            p.setdefault(key, default)


def _require(podcast: dict, field: str, index: int) -> None:
    if field not in podcast or podcast[field] is None:
        raise ValueError(f"Podcast at index {index} missing required field: {field}")
