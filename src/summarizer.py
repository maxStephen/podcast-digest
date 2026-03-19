"""
summarizer.py
Claude API integration — episode summarization with per-podcast parameters.
"""

import anthropic
from utils import get_anthropic_key


# ── Episode type labels ────────────────────────────────────────────────────────

EPISODE_TYPES = ["Interview", "Solo", "Panel", "Debate", "Storytelling", "News"]


# ── Main entry point ───────────────────────────────────────────────────────────

def summarize_episode(episode: dict, transcript: str, podcast: dict, cost_tracker) -> dict:
    """
    Summarize a single episode via the Claude API.

    Returns a dict containing:
        summary, episode_type, tags, quotes (if quotability),
        people, urls, input_tokens, output_tokens
    """
    verbosity = podcast.get("verbosity", 600)
    quotability = podcast.get("quotability", False)

    prompt = _build_prompt(episode, transcript, verbosity, quotability)
    response_text, input_tokens, output_tokens = _call_claude(prompt)
    cost_tracker.add_claude(input_tokens, output_tokens)

    return _parse_response(response_text, quotability, input_tokens, output_tokens)


def summarize_backcatalogue(episodes: list, podcast: dict, cost_tracker) -> dict:
    """
    Produce a single rolled-up summary across all back-catalogue episodes.
    Used when last_summarized is 'never'.

    Returns a dict containing:
        summary, notable_episodes, people, urls, input_tokens, output_tokens
    """
    verbosity = podcast.get("verbosity", 600)
    prompt = _build_backcatalogue_prompt(episodes, podcast["name"], verbosity)
    response_text, input_tokens, output_tokens = _call_claude(prompt)
    cost_tracker.add_claude(input_tokens, output_tokens)

    return _parse_backcatalogue_response(response_text, input_tokens, output_tokens)


# ── Prompt builders ────────────────────────────────────────────────────────────

def _build_prompt(episode: dict, transcript: str, verbosity: int, quotability: bool) -> str:
    quote_instruction = ""
    if quotability:
        quote_instruction = """
QUOTES:
Extract 2-3 short quotes that capture the unique voice or most memorable moments.
Format each as:
QUOTE: [quote text] — [speaker name or 'Host' if unknown]
"""

    return f"""You are summarizing a podcast episode for a busy listener's morning briefing.
Respond in the exact format specified. Do not add preamble or closing remarks.

Episode title: {episode['title']}
Published: {episode['published']}

Transcript/show notes:
{transcript[:6000]}

Respond in this exact format:

EPISODE_TYPE: [one of: Interview, Solo, Panel, Debate, Storytelling, News]

TAGS: [2-4 short topic tags separated by commas, e.g. history, technology, science]

SUMMARY:
[A clear engaging summary in under {verbosity} characters. Focus on what is new,
interesting, or actionable. Write for a reader who wants the key ideas fast.]
{quote_instruction}
PEOPLE: [comma-separated list of notable people or guests mentioned, or NONE]

URLS: [comma-separated list of URLs or resources mentioned, or NONE]"""


def _build_backcatalogue_prompt(episodes: list, show_name: str, verbosity: int) -> str:
    episode_list = "\n".join(
        f"- {ep['title']} ({ep['published']})"
        for ep in episodes[:50]
    )

    return f"""You are summarizing the back catalogue of a podcast for a new listener.
Respond in the exact format specified. Do not add preamble or closing remarks.

Show name: {show_name}
Total episodes available: {len(episodes)}

Episode list:
{episode_list}

Respond in this exact format:

SUMMARY:
[An overview of the show's themes, style, and what makes it distinctive.
Under {verbosity} characters.]

NOTABLE_EPISODES:
[List 3-5 standout episodes with title and one-line description each.
Format: EPISODE: [title] — [one line description]]

PEOPLE: [comma-separated list of recurring guests or notable people, or NONE]

URLS: [comma-separated list of key resources or websites associated with the show, or NONE]"""


# ── Claude API call ────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> tuple:
    """
    Call Claude API and return (response_text, input_tokens, output_tokens).
    """
    client = anthropic.Anthropic(api_key=get_anthropic_key())

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens

    return response_text, input_tokens, output_tokens


# ── Response parsers ───────────────────────────────────────────────────────────

def _parse_response(text: str, quotability: bool, input_tokens: int, output_tokens: int) -> dict:
    """Parse Claude's structured response into a clean dict."""
    result = {
        "episode_type": _extract_field(text, "EPISODE_TYPE"),
        "tags": _extract_list(text, "TAGS"),
        "summary": _extract_block(text, "SUMMARY"),
        "quotes": _extract_quotes(text) if quotability else [],
        "people": _extract_list(text, "PEOPLE"),
        "urls": _extract_list(text, "URLS"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return result


def _parse_backcatalogue_response(text: str, input_tokens: int, output_tokens: int) -> dict:
    """Parse Claude's back-catalogue response into a clean dict."""
    return {
        "summary": _extract_block(text, "SUMMARY"),
        "notable_episodes": _extract_notable_episodes(text),
        "people": _extract_list(text, "PEOPLE"),
        "urls": _extract_list(text, "URLS"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ── Field extractors ───────────────────────────────────────────────────────────

def _extract_field(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{label}:"):
            return line[len(label) + 1:].strip()
    return ""


def _extract_list(text: str, label: str) -> list:
    raw = _extract_field(text, label)
    if not raw or raw.upper() == "NONE":
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _extract_block(text: str, label: str) -> str:
    lines = text.splitlines()
    capturing = False
    block = []
    for line in lines:
        if line.startswith(f"{label}:"):
            capturing = True
            continue
        if capturing:
            if any(line.startswith(f"{l}:") for l in
                   ["EPISODE_TYPE", "TAGS", "SUMMARY", "QUOTES",
                    "PEOPLE", "URLS", "NOTABLE_EPISODES"]):
                break
            block.append(line)
    return "\n".join(block).strip()


def _extract_quotes(text: str) -> list:
    quotes = []
    for line in text.splitlines():
        if line.startswith("QUOTE:"):
            quotes.append(line[6:].strip())
    return quotes


def _extract_notable_episodes(text: str) -> list:
    episodes = []
    for line in text.splitlines():
        if line.startswith("EPISODE:"):
            episodes.append(line[8:].strip())
    return episodes