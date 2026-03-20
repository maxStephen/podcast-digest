"""
delivery_onenote.py
Builds and posts the morning digest page to OneNote via Microsoft Graph API.
"""

import requests
from datetime import date
from utils import get_ms_graph_credentials
from transcriber import source_label


# ── Graph API constants ────────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


# ── Main entry point ───────────────────────────────────────────────────────────

def deliver(digest: dict, cost_tracker) -> None:
    """
    def deliver(digest: dict, cost_tracker) -> None:
    creds = get_ms_graph_credentials()
    if creds.get("tenant_id") == "REPLACE_ME":
        print("OneNote delivery skipped — MS Graph credentials not yet configured")
        return
        Build the digest HTML page and POST it to OneNote.

    digest structure:
        {
            "date": "Thursday, March 19 2026",
            "shows": [
                {
                    "name": str,
                    "cover_art": str | None,
                    "episodes": [ { episode + summary dicts } ],
                    "no_new_episodes": bool,
                    "last_summarized": str,
                    "error": str | None,
                    "error_consecutive_days": int,
                    "error_cumulative_days_this_year": int,
                }
            ]
        }
    """
    token = _get_access_token()
    html = _build_page_html(digest, cost_tracker)
    _post_page(token, html, digest["date"])


# ── Access token ───────────────────────────────────────────────────────────────

def _get_access_token() -> str:
    """Obtain a Microsoft Graph access token via client credentials flow."""
    creds = get_ms_graph_credentials()
    url = TOKEN_URL.format(tenant_id=creds["tenant_id"])

    response = requests.post(url, data={
        "grant_type":    "client_credentials",
        "client_id":     creds["client_id"],
        "client_secret": creds["client_secret"],
        "scope":         "https://graph.microsoft.com/.default",
    })
    response.raise_for_status()
    return response.json()["access_token"]


# ── Page construction ──────────────────────────────────────────────────────────

def _build_page_html(digest: dict, cost_tracker) -> str:
    today = digest["date"]
    shows = digest["shows"]

    total_episodes = sum(
        len(s["episodes"]) for s in shows if not s.get("error") and not s.get("no_new_episodes")
    )
    total_shows = len(shows)
    cost_line = cost_tracker.format_for_digest()

    errors = [s for s in shows if s.get("error")]
    active_shows = [s for s in shows if not s.get("error")]

    sections = []
    for show in active_shows:
        sections.append(_build_show_section(show))

    error_section = _build_error_section(errors) if errors else ""

    return f"""<!DOCTYPE html>
<html>
<head>
  <title>Podcast Digest — {today}</title>
  <meta charset="utf-8"/>
</head>
<body>

<h1>Podcast Digest — {today}</h1>
<p style="color:#666;font-size:13px;">
  {total_shows} shows &nbsp;·&nbsp; {total_episodes} new episodes
  &nbsp;·&nbsp; {cost_line}
</p>
<hr/>

{"".join(sections)}
{error_section}

</body>
</html>"""


def _build_show_section(show: dict) -> str:
    name = show["name"]
    cover_art = show.get("cover_art")
    episodes = show.get("episodes", [])
    no_new = show.get("no_new_episodes", False)
    last_summarized = show.get("last_summarized", "")

    cover_html = ""
    if cover_art:
        cover_html = f'<img src="{cover_art}" width="80" height="80" style="float:left;margin:0 12px 8px 0;border-radius:8px;"/>'

    if no_new:
        return f"""
<h2>{cover_html}{name}</h2>
<div style="clear:both"></div>
<p style="color:#888;font-style:italic;">No new episodes since {last_summarized}.</p>
<hr/>"""

    episode_html = "".join(_build_episode_block(ep) for ep in episodes)

    return f"""
<h2>{cover_html}{name}</h2>
<div style="clear:both"></div>
{episode_html}
<hr/>"""


def _build_episode_block(ep: dict) -> str:
    title = ep["title"]
    published = ep.get("published", "")
    duration = ep.get("duration_display", "")
    episode_type = ep.get("summary", {}).get("episode_type", "")
    tags = ep.get("summary", {}).get("tags", [])
    summary = ep.get("summary", {}).get("summary", "")
    quotes = ep.get("summary", {}).get("quotes", [])
    people = ep.get("summary", {}).get("people", [])
    urls = ep.get("summary", {}).get("urls", [])
    transcript_src = ep.get("transcript_source", "")
    overcast_url = ep.get("overcast_url")
    is_backcatalogue = ep.get("is_backcatalogue", False)

    tag_html = ""
    if tags:
        tag_pills = "".join(
            f'<span style="background:#eee;border-radius:4px;padding:2px 7px;'
            f'margin-right:4px;font-size:12px;">#{t}</span>'
            for t in tags
        )
        tag_html = f'<p style="margin:4px 0;">{tag_pills}</p>'

    meta_parts = []
    if published:
        meta_parts.append(published)
    if duration:
        meta_parts.append(f"[{duration}]")
    if episode_type:
        meta_parts.append(episode_type)
    if transcript_src:
        meta_parts.append(source_label(transcript_src))
    meta_line = " &nbsp;·&nbsp; ".join(meta_parts)

    quotes_html = ""
    if quotes:
        quote_items = "".join(f"<li><em>{q}</em></li>" for q in quotes)
        quotes_html = f"<p><strong>Key quotes</strong></p><ul>{quote_items}</ul>"

    people_html = ""
    if people:
        people_html = f'<p><strong>People:</strong> {", ".join(people)}</p>'

    urls_html = ""
    if urls:
        url_items = "".join(
            f'<li><a href="{u}">{u}</a></li>' for u in urls
        )
        urls_html = f"<p><strong>Resources</strong></p><ul>{url_items}</ul>"

    backcatalogue_badge = ""
    if is_backcatalogue:
        backcatalogue_badge = (
            '<span style="background:#f0e6ff;color:#6b21a8;border-radius:4px;'
            'padding:2px 7px;font-size:12px;margin-left:8px;">Back catalogue</span>'
        )

    overcast_html = ""
    if overcast_url:
        overcast_html = (
            f'<p><a href="{overcast_url}" style="font-size:13px;">&#9654; Open in Overcast</a></p>'
        )

    return f"""
<h3>{title}{backcatalogue_badge}</h3>
<p style="color:#888;font-size:13px;">{meta_line}</p>
{tag_html}
<p>{summary}</p>
{quotes_html}
{people_html}
{urls_html}
{overcast_html}
<br/>"""


def _build_error_section(errors: list) -> str:
    if not errors:
        return ""

    rows = ""
    for show in errors:
        consecutive = show.get("error_consecutive_days", 0)
        cumulative = show.get("error_cumulative_days_this_year", 0)
        rows += f"""
<tr>
  <td style="padding:6px 12px;"><strong>{show['name']}</strong></td>
  <td style="padding:6px 12px;color:#b91c1c;">{show.get('error','Unknown error')}</td>
  <td style="padding:6px 12px;">{consecutive} day(s) in a row</td>
  <td style="padding:6px 12px;">{cumulative} day(s) this year</td>
</tr>"""

    return f"""
<h2 style="color:#b91c1c;">Errors</h2>
<table border="1" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;width:100%;font-size:13px;">
  <tr style="background:#fef2f2;">
    <th style="padding:6px 12px;text-align:left;">Show</th>
    <th style="padding:6px 12px;text-align:left;">Error</th>
    <th style="padding:6px 12px;text-align:left;">Consecutive</th>
    <th style="padding:6px 12px;text-align:left;">This year</th>
  </tr>
  {rows}
</table>"""


# ── Post to OneNote ────────────────────────────────────────────────────────────

def _post_page(token: str, html: str, title: str) -> None:
    """POST the digest page to the configured OneNote section."""
    creds = get_ms_graph_credentials()
    notebook_id = creds.get("notebook_id", "")
    section_id = creds.get("section_id", "")

    url = (
        f"{GRAPH_BASE}/me/onenote/notebooks/{notebook_id}"
        f"/sections/{section_id}/pages"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/xhtml+xml",
    }

    response = requests.post(url, headers=headers, data=html.encode("utf-8"))
    response.raise_for_status()