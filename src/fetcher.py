"""
fetcher.py
RSS feed parsing, episode filtering, and audio download.
"""

import os
import time
import feedparser
import requests
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from utils import parse_duration_seconds, format_duration, duration_exceeds_limit


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_episodes(podcast: dict) -> list[dict]:
    """
    Parse the RSS feed for a podcast and return a list of episodes
    that are new since last_summarized, in chronological order.

    Each returned episode dict contains:
        title, published, published_date, description, enclosure_url,
        duration_seconds, duration_display, overcast_url, is_backcatalogue
    """
    feed = feedparser.parse(podcast["rss_url"])

    if feed.bozo and not feed.entries:
        raise ValueError(f"Failed to parse RSS feed: {feed.bozo_exception}")

    last_summarized = podcast.get("last_summarized", "never")
    is_backcatalogue = last_summarized == "never"

    episodes = []
    for entry in feed.entries:
        episode = _parse_entry(entry)
        if episode is None:
            continue
        if not is_backcatalogue and not _is_new(episode, last_summarized):
            continue
        episode["is_backcatalogue"] = is_backcatalogue
        episodes.append(episode)

    episodes.sort(key=lambda e: e["published_date"])
    return episodes


def get_feed_image(podcast: dict) -> str | None:
    """Return the podcast cover art URL from the RSS feed, or None."""
    feed = feedparser.parse(podcast["rss_url"])
    image = feed.feed.get("image", {})
    return image.get("href") or feed.feed.get("itunes_image", {}).get("href")


# ── Audio download ─────────────────────────────────────────────────────────────

def download_audio(episode: dict, podcast_name: str) -> str:
    """
    Download episode audio to Lambda /tmp.
    Returns the local file path.
    Raises ValueError if no enclosure URL is available.
    """
    url = episode.get("enclosure_url")
    if not url:
        raise ValueError(f"No audio enclosure URL for episode: {episode['title']}")

    safe_name = "".join(c if c.isalnum() else "_" for c in podcast_name)[:40]
    local_path = f"/tmp/{safe_name}_{int(time.time())}.mp3"

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    with open(local_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return local_path


def delete_audio(local_path: str) -> None:
    """Remove downloaded audio file from /tmp."""
    try:
        os.remove(local_path)
    except FileNotFoundError:
        pass


# ── Entry parsing ──────────────────────────────────────────────────────────────

def _parse_entry(entry: dict) -> dict | None:
    """
    Extract fields from a feedparser entry.
    Returns None if the entry lacks a title or publication date.
    """
    title = entry.get("title", "").strip()
    if not title:
        return None

    published_date = _parse_date(entry)
    if published_date is None:
        return None

    description = (
        entry.get("summary")
        or entry.get("content", [{}])[0].get("value", "")
        or ""
    ).strip()

    enclosure_url = _get_enclosure_url(entry)
    duration_raw = entry.get("itunes_duration", "")
    duration_seconds = parse_duration_seconds(duration_raw)
    duration_display = format_duration(duration_seconds) if duration_seconds else "unknown"

    overcast_url = _build_overcast_url(enclosure_url)

    return {
        "title": title,
        "published": published_date.strftime("%B %d, %Y"),
        "published_date": published_date,
        "description": description,
        "enclosure_url": enclosure_url,
        "duration_seconds": duration_seconds,
        "duration_display": duration_display,
        "overcast_url": overcast_url,
    }


def _parse_date(entry: dict) -> datetime | None:
    """Parse publication date from feedparser entry. Returns timezone-aware datetime or None."""
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    return None


def _is_new(episode: dict, last_summarized: str) -> bool:
    """Return True if episode was published after last_summarized date."""
    try:
        cutoff = datetime.strptime(last_summarized, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return episode["published_date"] > cutoff
    except ValueError:
        return True


def _get_enclosure_url(entry: dict) -> str | None:
    """Extract audio enclosure URL from feedparser entry."""
    for enclosure in entry.get("enclosures", []):
        if "audio" in enclosure.get("type", ""):
            return enclosure.get("href") or enclosure.get("url")
    links = entry.get("links", [])
    for link in links:
        if "audio" in link.get("type", ""):
            return link.get("href")
    return None


def _build_overcast_url(enclosure_url: str | None) -> str | None:
    """Build an Overcast deep link from the episode enclosure URL."""
    if not enclosure_url:
        return None
    from urllib.parse import quote
    encoded = quote(enclosure_url, safe="")
    return f"overcast://x-callback-url/add?url={encoded}"


# ── Show notes quality check ───────────────────────────────────────────────────

def show_notes_sufficient(episode: dict, min_words: int = 300) -> bool:
    """
    Return True if show notes contain enough content to use
    instead of Whisper transcription.
    """
    description = episode.get("description", "")
    word_count = len(description.split())
    return word_count >= min_words
