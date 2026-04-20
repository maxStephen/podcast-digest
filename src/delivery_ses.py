"""
delivery_ses.py
Builds and sends the condensed morning digest email via AWS SES.
Includes a Notable Moments section at the top across all shows.
"""

import boto3
import re
from datetime import date
from utils import get_ses_addresses
from transcriber import source_label

ses = boto3.client("ses")


# ── Main entry point ───────────────────────────────────────────────────────────

def deliver(digest: dict, cost_tracker) -> None:
    """
    Build a condensed HTML email and send via SES.
    Structure:
        1. Header (date, cost)
        2. Notable Moments across all shows (if any)
        3. Per-show sections (title + first 2 sentences + Overcast link)
        4. Errors section (if any)
    """
    addresses = get_ses_addresses()
    from_address = addresses["from_address"]
    to_address = addresses["to_address"]

    subject = _build_subject(digest)
    html = _build_email_html(digest, cost_tracker)

    ses.send_email(
        Source=from_address,
        Destination={"ToAddresses": [to_address]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )


# ── Subject line ───────────────────────────────────────────────────────────────

def _build_subject(digest: dict) -> str:
    total_episodes = sum(
        len(s["episodes"])
        for s in digest["shows"]
        if not s.get("error") and not s.get("no_new_episodes")
    )
    show_count = len([s for s in digest["shows"] if not s.get("error")])
    notable_count = len(digest.get("notable_moments", []))
    notable_str = f" · {notable_count} notable moment(s)" if notable_count else ""
    return (
        f"Podcast Digest — {digest['date']} "
        f"· {total_episodes} episode(s) across {show_count} show(s){notable_str}"
    )


# ── Email HTML builder ─────────────────────────────────────────────────────────

def _build_email_html(digest: dict, cost_tracker) -> str:
    today = digest["date"]
    shows = digest["shows"]
    cost_line = cost_tracker.format_for_digest()
    notable_moments = digest.get("notable_moments", [])
    errors = [s for s in shows if s.get("error")]
    active_shows = [s for s in shows if not s.get("error")]

    notable_section = _build_notable_moments_section(notable_moments)
    sections = "".join(_build_show_section(show) for show in active_shows)
    error_section = _build_error_section(errors) if errors else ""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">

  <h1 style="font-size:22px;margin-bottom:4px;">Podcast Digest</h1>
  <p style="color:#666;font-size:13px;margin-top:0;">
    {today} &nbsp;·&nbsp; {cost_line}
  </p>
  <hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0;"/>

  {notable_section}
  {sections}
  {error_section}

  <p style="color:#aaa;font-size:11px;margin-top:32px;">
    Full digest available in OneNote.
  </p>

</body>
</html>"""


# ── Notable Moments section ────────────────────────────────────────────────────

def _build_notable_moments_section(moments: list) -> str:
    if not moments:
        return ""

    moment_blocks = "".join(_build_moment_block(m) for m in moments)

    return f"""
<div style="margin-bottom:24px;">
  <h2 style="font-size:17px;margin-bottom:4px;color:#1a1a1a;">
    &#9733; Notable Moments
  </h2>
  <p style="color:#888;font-size:12px;margin-top:0;margin-bottom:12px;">
    AI-identified moments worth your attention across today's episodes
  </p>
  {moment_blocks}
</div>
<hr style="border:none;border-top:2px solid #e5e5e5;margin:16px 0;"/>"""


def _build_moment_block(moment: dict) -> str:
    quote   = moment.get("quote", "")
    mtype   = moment.get("type", "")
    speaker = moment.get("speaker", "")
    show    = moment.get("show", "")
    episode = moment.get("episode", "")

    type_colors = {
        "Surprising claim or statistic":    ("#fff3cd", "#856404"),
        "Strong disagreement or debate moment": ("#fde8e8", "#9b1c1c"),
        "Memorable analogy or metaphor":    ("#e8f4fd", "#1e40af"),
        "Unusual personal admission":       ("#f0fdf4", "#166534"),
        "Counterintuitive insight":         ("#f3e8ff", "#6b21a8"),
    }
    bg, fg = type_colors.get(mtype, ("#f5f5f5", "#333333"))

    speaker_html = f" — <em>{speaker}</em>" if speaker and speaker.lower() != "host" else ""

    return f"""
<div style="margin-bottom:12px;padding:10px 14px;
            background:{bg};border-radius:6px;">
  <div style="margin-bottom:6px;">
    <span style="background:{fg};color:#fff;font-size:11px;
                 padding:2px 7px;border-radius:4px;font-weight:500;">
      {mtype}
    </span>
  </div>
  <p style="margin:0 0 4px 0;font-size:13px;line-height:1.5;font-style:italic;">
    &ldquo;{quote}&rdquo;{speaker_html}
  </p>
  <p style="margin:0;font-size:11px;color:#888;">
    {show} &nbsp;·&nbsp; {episode}
  </p>
</div>"""


# ── Show section ───────────────────────────────────────────────────────────────

def _build_show_section(show: dict) -> str:
    name           = show["name"]
    cover_art      = show.get("cover_art")
    episodes       = show.get("episodes", [])
    no_new         = show.get("no_new_episodes", False)
    last_summarized = show.get("last_summarized", "")

    cover_html = ""
    if cover_art:
        cover_html = (
            f'<img src="{cover_art}" width="48" height="48" '
            f'style="float:left;margin:0 10px 6px 0;border-radius:6px;"/>'
        )

    if no_new:
        return f"""
<div style="margin-bottom:24px;">
  <h2 style="font-size:16px;margin-bottom:4px;">{cover_html}{name}</h2>
  <div style="clear:both;"></div>
  <p style="color:#999;font-style:italic;font-size:13px;">
    No new episodes since {last_summarized}.
  </p>
</div>
<hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0;"/>"""

    episode_blocks = "".join(_build_episode_block(ep) for ep in episodes)

    return f"""
<div style="margin-bottom:24px;">
  <h2 style="font-size:16px;margin-bottom:8px;">{cover_html}{name}</h2>
  <div style="clear:both;"></div>
  {episode_blocks}
</div>
<hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0;"/>"""


def _build_episode_block(ep: dict) -> str:
    title           = ep.get("title", "Untitled")
    duration        = ep.get("duration_display", "")
    summary_text    = ep.get("summary", {}).get("summary", "")
    overcast_url    = ep.get("overcast_url")
    is_backcatalogue = ep.get("is_backcatalogue", False)

    condensed = _first_two_sentences(summary_text)

    duration_html = ""
    if duration:
        duration_html = (
            f'<span style="color:#999;font-size:12px;margin-left:6px;">[{duration}]</span>'
        )

    backcatalogue_badge = ""
    if is_backcatalogue:
        backcatalogue_badge = (
            '<span style="background:#f0e6ff;color:#6b21a8;border-radius:4px;'
            'padding:1px 6px;font-size:11px;margin-left:6px;">Back catalogue</span>'
        )

    overcast_html = ""
    if overcast_url:
        overcast_html = (
            f'<a href="{overcast_url}" style="font-size:12px;color:#0066cc;'
            f'text-decoration:none;">&#9654; Open in Overcast</a>'
        )

    return f"""
<div style="margin-bottom:14px;padding-left:8px;border-left:3px solid #e5e5e5;">
  <p style="margin:0 0 4px 0;font-weight:500;font-size:14px;">
    {title}{duration_html}{backcatalogue_badge}
  </p>
  <p style="margin:0 0 6px 0;font-size:13px;color:#444;line-height:1.5;">
    {condensed}
  </p>
  {overcast_html}
</div>"""


# ── Error section ──────────────────────────────────────────────────────────────

def _build_error_section(errors: list) -> str:
    if not errors:
        return ""

    rows = "".join(
        f"""<tr>
          <td style="padding:5px 10px;"><strong>{s['name']}</strong></td>
          <td style="padding:5px 10px;color:#b91c1c;">{s.get('error','Unknown error')}</td>
          <td style="padding:5px 10px;">{s.get('error_consecutive_days',0)}d in a row</td>
          <td style="padding:5px 10px;">{s.get('error_cumulative_days_this_year',0)}d this year</td>
        </tr>"""
        for s in errors
    )

    return f"""
<h2 style="font-size:15px;color:#b91c1c;">Errors</h2>
<table style="width:100%;border-collapse:collapse;font-size:12px;">
  <tr style="background:#fef2f2;font-weight:500;">
    <td style="padding:5px 10px;">Show</td>
    <td style="padding:5px 10px;">Error</td>
    <td style="padding:5px 10px;">Consecutive</td>
    <td style="padding:5px 10px;">This year</td>
  </tr>
  {rows}
</table>"""


# ── Text helpers ───────────────────────────────────────────────────────────────

def _first_two_sentences(text: str) -> str:
    """Extract the first two sentences from a summary for the condensed email."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:2])