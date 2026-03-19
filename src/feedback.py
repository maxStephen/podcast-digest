"""
feedback.py
Two Lambda handlers:
    lambda_handler  — receives feedback POST from Apple Shortcut via API Gateway
    auth_handler    — validates x-api-key header for the API Gateway authorizer
"""

import json
import os
import boto3
from datetime import datetime, timezone
from utils import get_feedback_api_key

s3 = boto3.client("s3")

BUCKET = os.environ["S3_BUCKET"]
FEEDBACK_KEY = os.environ["FEEDBACK_KEY"]


# ── Feedback handler ───────────────────────────────────────────────────────────

def lambda_handler(event: dict, context) -> dict:
    """
    Receives a feedback submission from the Apple Shortcut.

    Expected JSON body:
    {
        "type":          "episode" | "show",
        "show_name":     "Hardcore History",
        "episode_title": "Supernova in the East VI",  // required if type == episode
        "verbosity":     "too_long" | "just_right" | "too_short",
        "tone":          "too_dry"  | "just_right" | "too_detailed"
    }
    """
    try:
        body = _parse_body(event)
        _validate_feedback(body)
        record = _build_record(body)
        _append_to_s3(record)

        return _response(200, {"message": "Feedback recorded", "record": record})

    except ValueError as e:
        return _response(400, {"error": str(e)})
    except Exception as e:
        return _response(500, {"error": "Internal error", "detail": str(e)})


# ── API key authorizer ─────────────────────────────────────────────────────────

def auth_handler(event: dict, context) -> bool:
    """
    Lambda authorizer for API Gateway HTTP API (simple response mode).
    Returns True if the x-api-key header matches the stored secret, False otherwise.
    """
    try:
        provided_key = (
            event.get("headers", {}).get("x-api-key")
            or event.get("headers", {}).get("X-Api-Key")
            or ""
        )
        expected_key = get_feedback_api_key()
        return provided_key == expected_key
    except Exception:
        return False


# ── Validation ─────────────────────────────────────────────────────────────────

VALID_TYPES = {"episode", "show"}
VALID_VERBOSITY = {"too_long", "just_right", "too_short"}
VALID_TONE = {"too_dry", "just_right", "too_detailed"}


def _validate_feedback(body: dict) -> None:
    feedback_type = body.get("type")
    if feedback_type not in VALID_TYPES:
        raise ValueError(f"Invalid type '{feedback_type}'. Must be: {VALID_TYPES}")

    if not body.get("show_name"):
        raise ValueError("show_name is required")

    if feedback_type == "episode" and not body.get("episode_title"):
        raise ValueError("episode_title is required when type is 'episode'")

    verbosity = body.get("verbosity")
    if verbosity and verbosity not in VALID_VERBOSITY:
        raise ValueError(f"Invalid verbosity '{verbosity}'. Must be: {VALID_VERBOSITY}")

    tone = body.get("tone")
    if tone and tone not in VALID_TONE:
        raise ValueError(f"Invalid tone '{tone}'. Must be: {VALID_TONE}")

    if not verbosity and not tone:
        raise ValueError("At least one of verbosity or tone must be provided")


# ── Record builder ─────────────────────────────────────────────────────────────

def _build_record(body: dict) -> dict:
    record = {
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "type":         body["type"],
        "show_name":    body["show_name"],
        "verbosity":    body.get("verbosity"),
        "tone":         body.get("tone"),
    }
    if body["type"] == "episode":
        record["episode_title"] = body.get("episode_title")
    return record


# ── S3 append ─────────────────────────────────────────────────────────────────

def _append_to_s3(record: dict) -> None:
    """Append a feedback record as a new line to feedback_log.jsonl in S3."""
    try:
        existing = s3.get_object(Bucket=BUCKET, Key=FEEDBACK_KEY)
        current = existing["Body"].read().decode("utf-8")
    except s3.exceptions.NoSuchKey:
        current = ""

    updated = current + json.dumps(record) + "\n"
    s3.put_object(
        Bucket=BUCKET,
        Key=FEEDBACK_KEY,
        Body=updated.encode("utf-8"),
        ContentType="application/json",
    )


# ── Body parser ────────────────────────────────────────────────────────────────

def _parse_body(event: dict) -> dict:
    """Parse JSON body from API Gateway event."""
    body = event.get("body", "{}")
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, dict):
        return body
    raise ValueError("Could not parse request body")


# ── Response helper ────────────────────────────────────────────────────────────

def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }