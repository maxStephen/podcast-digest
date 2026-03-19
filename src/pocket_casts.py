"""
pocket_casts.py
Per-podcast Pocket Casts actions via the unofficial Pocket Casts API.
All actions are opt-in via pocket_casts_action in podcast config.
"""

import requests
from utils import get_pocket_casts_credentials


# ── API constants ──────────────────────────────────────────────────────────────

PC_BASE = "https://api.pocketcasts.com"
LOGIN_URL = f"{PC_BASE}/user/login"
MARK_PLAYED_URL = f"{PC_BASE}/sync/update_episode"
UP_NEXT_URL = f"{PC_BASE}/up_next/add"
STAR_URL = f"{PC_BASE}/sync/update_episode"


# ── Main entry point ───────────────────────────────────────────────────────────

def apply_action(episode: dict, podcast: dict) -> None:
    """
    Apply the configured Pocket Casts action for a summarized episode.
    Does nothing if pocket_casts_action is 'none' or episode has no enclosure URL.

    Actions:
        none          — no change (default)
        mark_played   — mark episode as played
        add_to_up_next — add episode to Up Next queue
        star          — star / bookmark the episode
    """
    action = podcast.get("pocket_casts_action", "none")
    if action == "none":
        return

    enclosure_url = episode.get("enclosure_url")
    if not enclosure_url:
        return

    token = _get_token()
    podcast_uuid = _resolve_podcast_uuid(token, podcast["rss_url"])
    episode_uuid = _resolve_episode_uuid(token, podcast_uuid, enclosure_url)

    if not episode_uuid:
        raise ValueError(
            f"Could not resolve Pocket Casts episode UUID for: {episode['title']}"
        )

    if action == "mark_played":
        _mark_played(token, podcast_uuid, episode_uuid)
    elif action == "add_to_up_next":
        _add_to_up_next(token, podcast_uuid, episode_uuid)
    elif action == "star":
        _star_episode(token, podcast_uuid, episode_uuid)
    else:
        raise ValueError(f"Unknown pocket_casts_action: {action}")


# ── Authentication ─────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Authenticate with Pocket Casts and return a session token."""
    creds = get_pocket_casts_credentials()
    response = requests.post(LOGIN_URL, json={
        "email": creds["email"],
        "password": creds["password"],
        "scope": "webplayer",
    })
    response.raise_for_status()
    return response.json()["token"]


# ── UUID resolution ────────────────────────────────────────────────────────────

def _resolve_podcast_uuid(token: str, rss_url: str) -> str:
    """
    Look up the Pocket Casts podcast UUID by matching the RSS URL
    against the user's subscribed podcasts.
    """
    headers = _auth_headers(token)
    response = requests.post(
        f"{PC_BASE}/user/podcast/list",
        headers=headers,
        json={"v": 1},
    )
    response.raise_for_status()

    podcasts = response.json().get("podcasts", [])
    for p in podcasts:
        if p.get("url", "").rstrip("/") == rss_url.rstrip("/"):
            return p["uuid"]

    raise ValueError(f"Podcast not found in Pocket Casts subscriptions: {rss_url}")


def _resolve_episode_uuid(token: str, podcast_uuid: str, enclosure_url: str) -> str | None:
    """
    Look up the Pocket Casts episode UUID by matching the enclosure URL
    against recent episodes of the podcast.
    """
    headers = _auth_headers(token)
    response = requests.post(
        f"{PC_BASE}/user/podcast/episodes",
        headers=headers,
        json={"uuid": podcast_uuid},
    )
    response.raise_for_status()

    episodes = response.json().get("episodes", [])
    for ep in episodes:
        if ep.get("url", "").rstrip("/") == enclosure_url.rstrip("/"):
            return ep["uuid"]

    return None


# ── Actions ────────────────────────────────────────────────────────────────────

def _mark_played(token: str, podcast_uuid: str, episode_uuid: str) -> None:
    """Mark an episode as played in Pocket Casts."""
    _update_episode(token, podcast_uuid, episode_uuid, {"playing_status": 3})


def _star_episode(token: str, podcast_uuid: str, episode_uuid: str) -> None:
    """Star / bookmark an episode in Pocket Casts."""
    _update_episode(token, podcast_uuid, episode_uuid, {"starred": True})


def _update_episode(token: str, podcast_uuid: str, episode_uuid: str, fields: dict) -> None:
    """Generic episode field update via Pocket Casts sync API."""
    headers = _auth_headers(token)
    payload = {
        "episodes": [{
            "uuid": episode_uuid,
            "podcast": podcast_uuid,
            **fields,
        }]
    }
    response = requests.post(MARK_PLAYED_URL, headers=headers, json=payload)
    response.raise_for_status()


def _add_to_up_next(token: str, podcast_uuid: str, episode_uuid: str) -> None:
    """Add an episode to the Pocket Casts Up Next queue."""
    headers = _auth_headers(token)
    payload = {
        "episode": {
            "uuid": episode_uuid,
            "podcast": podcast_uuid,
        }
    }
    response = requests.post(UP_NEXT_URL, headers=headers, json=payload)
    response.raise_for_status()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }