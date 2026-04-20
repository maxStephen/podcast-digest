"""
summarizer.py
Claude via AWS Bedrock — episode summarization with per-podcast parameters.
Uses Haiku by default, Sonnet for per-podcast override.
"""

import json
import boto3

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# ── Model IDs ──────────────────────────────────────────────────────────────────

MODELS = {
    "haiku":  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}
DEFAULT_MODEL = "haiku"

# ── Notable moment types ───────────────────────────────────────────────────────

MOMENT_TYPES = [
    "Surprising claim or statistic",
    "Strong disagreement or debate moment",
    "Memorable analogy or metaphor",
    "Unusual personal admission",
    "Counterintuitive insight",
]


# ── Main entry point ───────────────────────────────────────────────────────────

def summarize_episode(episode: dict, transcript: str, podcast: dict, cost_tracker) -> dict:
    """
    Summarize a single episode via Claude on Bedrock.

    Returns a dict containing:
        summary, episode_type, tags, quotes (if quotability),
        notable_moments (if quotability), people, urls,
        input_tokens, output_tokens
    """
    verbosity = podcast.get("verbosity", 600)
    quotability = podcast.get("quotability", False)
    model_key = podcast.get("model", DEFAULT_MODEL)

    prompt = _build_prompt(episode, transcript, verbosity, quotability)
    response_text, input_tokens, output_tokens = _call_bedrock(prompt, model_key)
    cost_tracker.add_claude(input_tokens, output_tokens)

    return _parse_response(response_text, quotability, input_tokens, output_tokens)


def summarize_backcatalogue(episodes: list, podcast: dict, cost_tracker) -> dict:
    """
    Produce a single rolled-up summary across all back-catalogue episodes.
    Always uses Sonnet for deeper synthesis regardless of per-podcast model setting.
    """
    verbosity = podcast.get("verbosity", 600)
    prompt = _build_backcatalogue_prompt(episodes, podcast["name"], verbosity)
    response_text, input_tokens, output_tokens = _call_bedrock(prompt, "sonnet")
    cost_tracker.add_claude(input_tokens, output_tokens)

    return _parse_backcatalogue_response(response_text, input_tokens, output_tokens)


# ── Prompt builders ────────────────────────────────────────────────────────────

def _build_prompt(episode: dict, transcript: str, verbosity: int, quotability: bool) -> str:
    quote_instruction = ""
    notable_instruction = ""

    if quotability:
        quote_instruction = """
QUOTES:
Extract 2-3 short quotes that capture the unique voice or most memorable moments.
Format each as:
QUOTE: [quote text] — [speaker name or 'Host' if unknown]
"""
        moment_types = "\n".join(f"- {t}" for t in MOMENT_TYPES)
        notable_instruction = f"""
NOTABLE_MOMENTS:
Identify up to 5 moments that are genuinely worth a listener's attention.
For each moment, classify it as one of these types:
{moment_types}

Format each as:
MOMENT: [exact quote or close paraphrase] | TYPE: [moment type] | SPEAKER: [speaker name or 'Host' if unknown]

Only include moments that are truly striking — omit this section entirely if nothing qualifies.
"""

    return f"""You are summarizing a podcast episode for a busy listener's morning briefing.
Respond in the exact format specified. Do not add preamble or closing remarks.

Episode title: {episode['title']}
Published: {episode['published']}

Transcript/show notes:
{transcript[:3000]}

Respond in this exact format:

EPISODE_TYPE: [one of: Interview, Solo, Panel, Debate, Storytelling, News]

TAGS: [2-4 short topic tags separated by commas, e.g. history, technology, science]

SUMMARY:
[A clear engaging summary in under {verbosity} characters. Focus on what is new,
interesting, or actionable. Write for a reader who wants the key ideas fast.]
{quote_instruction}{notable_instruction}
PEOPLE: [comma-separated list of notable people or guests mentioned, or NONE]

URLS: [comma-separated list of URLs or resources mentioned, or NONE]"""


def _build_backcatalogue_prompt(episodes: list, show_name: str, verbosity: int) -> str:
    episode_list = "\n".join(
        f"- {ep['title']} ({ep['published']})"
        for ep in episodes[:10]
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


# ── Bedrock API call ───────────────────────────────────────────────────────────

def _call_bedrock(prompt: str, model_key: str) -> tuple:
    """
    Call Claude on Bedrock and return (response_text, input_tokens, output_tokens).
    """
    model_id = MODELS.get(model_key, MODELS[DEFAULT_MODEL])

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = bedrock.invoke_model(
        modelId=model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    response_text = result["content"][0]["text"]
    input_tokens = result["usage"]["input_tokens"]
    output_tokens = result["usage"]["output_tokens"]

    return response_text, input_tokens, output_tokens


# ── Response parsers ───────────────────────────────────────────────────────────

def _parse_response(text: str, quotability: bool, input_tokens: int, output_tokens: int) -> dict:
    return {
        "episode_type":     _extract_field(text, "EPISODE_TYPE"),
        "tags":             _extract_list(text, "TAGS"),
        "summary":          _extract_block(text, "SUMMARY"),
        "quotes":           _extract_quotes(text) if quotability else [],
        "notable_moments":  _extract_notable_moments(text) if quotability else [],
        "people":           _extract_list(text, "PEOPLE"),
        "urls":             _extract_list(text, "URLS"),
        "input_tokens":     input_tokens,
        "output_tokens":    output_tokens,
    }


def _parse_backcatalogue_response(text: str, input_tokens: int, output_tokens: int) -> dict:
    return {
        "summary":          _extract_block(text, "SUMMARY"),
        "notable_episodes": _extract_notable_episodes(text),
        "people":           _extract_list(text, "PEOPLE"),
        "urls":             _extract_list(text, "URLS"),
        "input_tokens":     input_tokens,
        "output_tokens":    output_tokens,
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
                    "NOTABLE_MOMENTS", "PEOPLE", "URLS", "NOTABLE_EPISODES"]):
                break
            block.append(line)
    return "\n".join(block).strip()


def _extract_quotes(text: str) -> list:
    return [
        line[6:].strip()
        for line in text.splitlines()
        if line.startswith("QUOTE:")
    ]


def _extract_notable_moments(text: str) -> list:
    """
    Parse MOMENT lines into structured dicts.
    Format: MOMENT: [quote] | TYPE: [type] | SPEAKER: [speaker]
    """
    moments = []
    for line in text.splitlines():
        if not line.startswith("MOMENT:"):
            continue
        parts = line[7:].split("|")
        if len(parts) < 3:
            continue
        quote = parts[0].strip()
        moment_type = parts[1].replace("TYPE:", "").strip()
        speaker = parts[2].replace("SPEAKER:", "").strip()
        moments.append({
            "quote":   quote,
            "type":    moment_type,
            "speaker": speaker,
        })
    return moments[:5]


def _extract_notable_episodes(text: str) -> list:
    return [
        line[8:].strip()
        for line in text.splitlines()
        if line.startswith("EPISODE:")
    ]