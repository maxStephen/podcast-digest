"""
utils.py
Shared helpers: secrets retrieval, cost tracking, duration parsing, logging.
"""

import json
import os
import boto3
from datetime import date, datetime
from functools import lru_cache

secrets_client = boto3.client("secretsmanager")


# ── Secrets ────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def get_secret(secret_name: str) -> dict:
    """
    Fetch a secret from Secrets Manager and return parsed JSON dict.
    Results are cached for the lifetime of the Lambda execution context.
    """
    response = secrets_client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def get_anthropic_key() -> str:
    return get_secret("podcast/anthropic_api_key")["api_key"]


def get_openai_key() -> str:
    return get_secret("podcast/openai_api_key")["api_key"]


def get_ms_graph_credentials() -> dict:
    return get_secret("podcast/ms_graph")


def get_pocket_casts_credentials() -> dict:
    return get_secret("podcast/pocket_casts")


def get_ses_addresses() -> dict:
    return get_secret("podcast/ses")


def get_feedback_api_key() -> str:
    return get_secret("podcast/feedback_api_key")["api_key"]


# ── Duration parsing ───────────────────────────────────────────────────────────

def parse_duration_seconds(raw: str) -> int | None:
    """
    Parse iTunes duration string to total seconds.
    Accepts: HH:MM:SS, MM:SS, or plain seconds as string.
    Returns None if unparseable.
    """
    if not raw:
        return None
    parts = raw.strip().split(":")
    try:
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            return parts[0]
    except ValueError:
        return None
    return None


def format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS string for display in digest."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def duration_exceeds_limit(seconds: int | None, limit_minutes: int | None) -> bool:
    """Return True if episode duration exceeds the per-podcast limit."""
    if seconds is None or limit_minutes is None:
        return False
    return seconds > limit_minutes * 60


# ── Cost tracking ──────────────────────────────────────────────────────────────

class CostTracker:
    """
    Accumulates API costs across a run and produces a summary.
    Whisper: $0.006 per minute of audio.
    Claude: based on token counts at claude-sonnet-4-5 pricing.
    """
    WHISPER_COST_PER_MINUTE = 0.006
    CLAUDE_INPUT_COST_PER_1K = 0.003
    CLAUDE_OUTPUT_COST_PER_1K = 0.015

    def __init__(self):
        self.whisper_minutes = 0.0
        self.claude_input_tokens = 0
        self.claude_output_tokens = 0

    def add_whisper(self, audio_seconds: int) -> None:
        self.whisper_minutes += audio_seconds / 60

    def add_claude(self, input_tokens: int, output_tokens: int) -> None:
        self.claude_input_tokens += input_tokens
        self.claude_output_tokens += output_tokens

    @property
    def whisper_cost(self) -> float:
        return self.whisper_minutes * self.WHISPER_COST_PER_MINUTE

    @property
    def claude_cost(self) -> float:
        return (
            (self.claude_input_tokens / 1000) * self.CLAUDE_INPUT_COST_PER_1K +
            (self.claude_output_tokens / 1000) * self.CLAUDE_OUTPUT_COST_PER_1K
        )

    @property
    def total_cost(self) -> float:
        return self.whisper_cost + self.claude_cost

    def summary(self) -> dict:
        return {
            "whisper_minutes": round(self.whisper_minutes, 2),
            "whisper_cost_usd": round(self.whisper_cost, 4),
            "claude_input_tokens": self.claude_input_tokens,
            "claude_output_tokens": self.claude_output_tokens,
            "claude_cost_usd": round(self.claude_cost, 4),
            "total_cost_usd": round(self.total_cost, 4),
        }

    def format_for_digest(self) -> str:
        s = self.summary()
        return (
            f"Whisper: {s['whisper_minutes']} min / ${s['whisper_cost_usd']:.4f} — "
            f"Claude: {s['claude_input_tokens']:,} in / {s['claude_output_tokens']:,} out "
            f"/ ${s['claude_cost_usd']:.4f} — "
            f"Total: ${s['total_cost_usd']:.4f}"
        )


# ── Run logging ────────────────────────────────────────────────────────────────

class RunLogger:
    """
    Accumulates run metadata and appends a JSON record to S3 run_log.jsonl
    at the end of each job execution.
    """
    def __init__(self, s3_client, bucket: str, log_key: str):
        self.s3 = s3_client
        self.bucket = bucket
        self.log_key = log_key
        self.started_at = datetime.utcnow().isoformat() + "Z"
        self.shows_processed = []
        self.shows_skipped = []
        self.shows_errored = []
        self.episode_count = 0

    def log_processed(self, show_name: str, episode_count: int) -> None:
        self.shows_processed.append(show_name)
        self.episode_count += episode_count

    def log_skipped(self, show_name: str) -> None:
        self.shows_skipped.append(show_name)

    def log_error(self, show_name: str, message: str) -> None:
        self.shows_errored.append({"show": show_name, "error": message})

    def flush(self, cost_tracker: CostTracker, duration_seconds: float) -> None:
        """Append completed run record to run_log.jsonl in S3."""
        record = {
            "run_at": self.started_at,
            "duration_seconds": round(duration_seconds, 1),
            "shows_processed": self.shows_processed,
            "shows_skipped": self.shows_skipped,
            "shows_errored": self.shows_errored,
            "total_episodes": self.episode_count,
            "cost": cost_tracker.summary(),
        }

        try:
            existing = self.s3.get_object(Bucket=self.bucket, Key=self.log_key)
            current = existing["Body"].read().decode("utf-8")
        except Exception:
            current = ""

        updated = current + json.dumps(record) + "\n"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.log_key,
            Body=updated,
            ContentType="application/json",
        )
