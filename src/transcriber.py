"""
transcriber.py
Transcript acquisition — show notes, Whisper API, or fallback logic.
"""

from openai import OpenAI
from fetcher import download_audio, delete_audio, show_notes_sufficient
from utils import get_openai_key, duration_exceeds_limit


# ── Main entry point ───────────────────────────────────────────────────────────

def get_transcript(episode: dict, podcast: dict, cost_tracker) -> tuple:
    """
    Return (transcript_text, source_used) for an episode.

    source_used is one of:
        show_notes, whisper, show_notes_fallback, show_notes_duration_cap

    Strategy is determined by podcast["transcript_source"]:
        show_notes              — always use show notes
        whisper                 — always use Whisper
        show_notes_then_whisper — use show notes if sufficient, else Whisper

    If episode duration exceeds max_episode_duration_minutes,
    force show notes regardless of strategy.
    """
    strategy = podcast.get("transcript_source", "show_notes_then_whisper")
    limit = podcast.get("max_episode_duration_minutes")
    duration = episode.get("duration_seconds")

    if duration_exceeds_limit(duration, limit):
        text = _get_show_notes(episode)
        return text, "show_notes_duration_cap"

    if strategy == "show_notes":
        text = _get_show_notes(episode)
        return text, "show_notes"

    if strategy == "whisper":
        text = _transcribe(episode, cost_tracker)
        return text, "whisper"

    if strategy == "show_notes_then_whisper":
        if show_notes_sufficient(episode):
            text = _get_show_notes(episode)
            return text, "show_notes"
        text = _transcribe(episode, cost_tracker)
        return text, "whisper"

    raise ValueError(f"Unknown transcript_source strategy: {strategy}")


# ── Show notes ─────────────────────────────────────────────────────────────────

def _get_show_notes(episode: dict) -> str:
    """Return episode description/show notes as the transcript source."""
    notes = episode.get("description", "").strip()
    if not notes:
        raise ValueError(f"No show notes available for: {episode['title']}")
    return notes


# ── Whisper transcription ──────────────────────────────────────────────────────

def _transcribe(episode: dict, cost_tracker) -> str:
    """
    Download episode audio, transcribe via OpenAI Whisper API,
    delete the local file, and return the transcript text.
    Updates cost_tracker with audio duration used.
    """
    local_path = None
    try:
        local_path = download_audio(episode, episode["title"])
        transcript = _call_whisper(local_path)

        if episode.get("duration_seconds"):
            cost_tracker.add_whisper(episode["duration_seconds"])

        return transcript

    finally:
        if local_path:
            delete_audio(local_path)


def _call_whisper(audio_path: str) -> str:
    """Call OpenAI Whisper API and return transcript text."""
    client = OpenAI(api_key=get_openai_key())

    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )

    return response.strip()


# ── Source label for digest display ───────────────────────────────────────────

def source_label(source_used: str) -> str:
    """Return a human-readable label for the transcript source."""
    labels = {
        "show_notes":               "Show notes",
        "whisper":                  "Whisper transcript",
        "show_notes_fallback":      "Show notes (Whisper unavailable)",
        "show_notes_duration_cap":  "Show notes (episode exceeds duration limit)",
    }
    return labels.get(source_used, source_used)