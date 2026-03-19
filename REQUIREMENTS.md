# Podcast Morning Digest — Requirements Specification

## 1. Overview

A scheduled automation job that runs each morning at **5:45 AM**, processes subscribed podcasts, and delivers a single combined digest to **OneNote** on the user's iPhone. The job is host-agnostic and runs identically on macOS (launchd), a VPS (cron), or GitHub Actions (scheduled workflow).

---

## 2. Scheduling

| Parameter | Value |
|---|---|
| Trigger | Time-based cron: 5:45 AM daily |
| Hosting | Host-agnostic (Mac / VPS / GitHub Actions) |
| Timezone | Configured via environment variable `TZ` |

---

## 3. Podcast Config File

Each podcast is defined as an entry in a **JSON config file** (`podcasts.json`). The file is the single source of truth for both user preferences and runtime state.

### 3.1 Per-Podcast Parameters (user-defined)

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name of the show |
| `rss_url` | string | RSS feed URL |
| `priority` | integer | Digest ordering (1 = top). User-assigned. |
| `verbosity` | integer | Max characters for the episode summary body |
| `quotability` | boolean | If true, append 2–3 key quotes after the summary |
| `transcript_source` | enum | `"show_notes_then_whisper"` (default) · `"whisper"` · `"show_notes"` |
| `pocket_casts_action` | enum | `"none"` (default) · `"mark_played"` · `"add_to_up_next"` · `"star"` |

### 3.2 Per-Podcast Runtime State (managed by the job)

| Field | Type | Description |
|---|---|---|
| `last_summarized` | date string or `"never"` | Date of most recently summarized episode |
| `error_consecutive_days` | integer | Days in a row the show has errored |
| `error_cumulative_days_this_year` | integer | Total error days in the current calendar year |
| `last_error_date` | date string or null | Date of last error occurrence |
| `last_error_message` | string or null | Most recent error description |

### 3.3 Example Config Entry

```json
{
  "name": "Hardcore History",
  "rss_url": "https://feeds.feedburner.com/dancarlin/history",
  "priority": 1,
  "verbosity": 800,
  "quotability": true,
  "transcript_source": "show_notes_then_whisper",
  "pocket_casts_action": "none",
  "last_summarized": "2026-03-18",
  "error_consecutive_days": 0,
  "error_cumulative_days_this_year": 0,
  "last_error_date": null,
  "last_error_message": null
}
```

---

## 4. Episode Fetching & Filtering

- Parse the RSS feed for each podcast.
- **Filter episodes** to only those published **after** `last_summarized`.
- If `last_summarized` is `"never"`, do **not** summarize all episodes individually. Instead, produce a single **back-catalogue digest** — a rolled-up summary across all available episodes — for that show.
- Episodes within scope are processed in **chronological order** (oldest first).
- After a successful run, update `last_summarized` to today's date.

---

## 5. Transcript Strategy

Default per-podcast: `show_notes_then_whisper`

| Strategy | Behaviour |
|---|---|
| `show_notes_then_whisper` | Use RSS show notes if ≥ 300 words; otherwise download audio and transcribe via OpenAI Whisper API |
| `show_notes` | Use RSS show notes only; never invoke Whisper |
| `whisper` | Always download audio and transcribe via Whisper, ignoring show notes |

Audio files are sourced from the RSS `<enclosure>` tag. Temporary audio files are deleted immediately after transcription.

---

## 6. AI Summarization (Claude API)

Each in-scope episode is summarized individually using the **Claude API**, with per-podcast parameters injected into the prompt.

### 6.1 Per-Episode Output

| Element | Condition |
|---|---|
| Episode title | Always |
| Episode type label | Always — one of: `Interview`, `Solo`, `Panel`, `Debate`, `Storytelling`, `News` |
| Auto topic tags | Always — 2–4 short tags (e.g. `#history`, `#technology`) |
| Summary body | Always — capped at `verbosity` characters |
| Key quotes | Only if `quotability: true` — 2–3 quotes with speaker attribution where available |
| People / guests named | Always — comma-separated list, or omitted if none |
| URLs & resources cited | Always — bulleted list of links mentioned, or omitted if none |
| Episode duration | Always — sourced from RSS `<itunes:duration>` tag |

### 6.2 Back-Catalogue Digest (when `last_summarized` is `"never"`)

A single rolled-up summary across all available episodes, structured as:
- Overall show description and themes
- Notable episodes list (title + one-line description each)
- Key recurring guests or people
- Top resources cited across episodes

---

## 7. Error Handling

If a podcast fails at any stage (feed fetch, transcription, or summarization):

- Log the error with timestamp and message to the **run log file**.
- Skip that show for this run.
- Include the show in the digest under an **Errors** section with:
  - Show name
  - Error description
  - Consecutive error days (e.g. "3 days in a row")
  - Cumulative error days this calendar year (e.g. "7 days this year")
- Update `error_consecutive_days`, `error_cumulative_days_this_year`, and `last_error_message` in the config.
- On a **successful** run for a show, reset `error_consecutive_days` to `0` (cumulative days this year are never reset mid-year).

---

## 8. Digest Format & Delivery

### 8.1 Structure

A **single combined OneNote page** is created per run, titled:  
`Podcast Digest — [Day, Month Date Year]` (e.g. `Podcast Digest — Thursday, March 19 2026`)

Page sections in order:

1. **Header** — date, total shows processed, total new episodes, total run cost (Whisper + Claude)
2. **Show sections** — ordered by `priority` (ascending). Each show section contains:
   - Show name + cover art thumbnail (sourced from RSS `<itunes:image>`)
   - For each episode: all elements listed in §6.1
   - If no new episodes: a single line — *"No new episodes since [last summarized date]."*
3. **Errors section** — only present if one or more shows errored (see §7)

### 8.2 Formatting

- Markdown rendered as formatted HTML in OneNote
- Cover art thumbnails embedded inline at the show heading level
- Episode duration displayed as `[HH:MM:SS]` next to each episode title

### 8.3 Delivery

- Posted to a designated OneNote notebook and section via the **Microsoft Graph API**
- No push notification — user opens OneNote manually each morning

---

## 9. Pocket Casts Integration

Pocket Casts actions are **per-podcast** and **opt-in** via the `pocket_casts_action` config field.

| Value | Behaviour |
|---|---|
| `"none"` | No changes made to Pocket Casts (default) |
| `"mark_played"` | Mark each summarized episode as played |
| `"add_to_up_next"` | Add each summarized episode to the Up Next queue |
| `"star"` | Star / bookmark each summarized episode |

Integration uses the **Pocket Casts unofficial API** (authenticated via account credentials stored in environment variables).

---

## 10. Operational Visibility

### 10.1 Run Log (`run_log.jsonl`)

One JSON line appended per run, containing:
- Run timestamp
- Shows processed (with episode counts)
- Shows skipped (no new episodes)
- Shows errored (with error messages)
- Total duration (seconds)
- Total API cost (USD)

### 10.2 Cost Report (included in digest header and log)

| Cost Item | Source |
|---|---|
| Whisper transcription | OpenAI usage API — $0.006/min of audio |
| Claude summarization | Anthropic usage API — token counts × model rate |
| **Total run cost** | Sum of above, reported in USD to 4 decimal places |

---

## 11. Hosting Architecture

### 11.1 Platform

| Component | AWS Service | Notes |
|---|---|---|
| Job execution | **Lambda** | Python 3.12 runtime, up to 15 min timeout |
| Scheduler | **EventBridge Scheduler** | Timezone-aware cron, replaces local crontab |
| Config & state | **S3** (private bucket) | `podcasts.json` read at job start, written back on completion |
| Run logs | **S3** (same bucket) | `run_log.jsonl` appended each run |
| Secrets | **AWS Secrets Manager** | All API keys — never stored in S3 or Lambda env vars in plaintext |

### 11.2 S3 Bucket Structure

```
s3://your-podcast-digest-bucket/
├── config/
│   └── podcasts.json          # Source of truth for all podcast config + runtime state
└── logs/
    └── run_log.jsonl          # Appended each run
```

Bucket is **private**, no public access, encrypted at rest (SSE-S3). Access granted exclusively to the Lambda execution role via IAM policy.

### 11.3 Lambda Configuration

| Setting | Value |
|---|---|
| Runtime | Python 3.12 |
| Memory | 512 MB (headroom for audio buffering) |
| Timeout | 900 seconds (15 min — Lambda maximum) |
| Ephemeral storage (`/tmp`) | 1024 MB (for temporary audio file downloads) |
| Trigger | EventBridge Scheduler rule |

Audio files are downloaded to `/tmp`, transcribed, then immediately deleted — Lambda ephemeral storage is wiped between invocations automatically.

### 11.4 Timeout Safety — Episode Duration Filter

To prevent Lambda timeout on long-form shows, each podcast config entry accepts an optional `max_episode_duration_minutes` field.

| Condition | Behaviour |
|---|---|
| Episode duration ≤ `max_episode_duration_minutes` | Normal processing (Whisper if needed) |
| Episode duration > `max_episode_duration_minutes` | Force `transcript_source` to `show_notes` for that episode; note the override in the digest and run log |
| Field absent or `null` | No duration filter applied |

Episode duration is sourced from the RSS `<itunes:duration>` tag before any audio is downloaded. If duration is absent from the feed, the filter is skipped and a warning is logged.

### 11.4 EventBridge Scheduler

```
Schedule expression: cron(45 5 * * ? *)
Timezone: Your local timezone (e.g. America/New_York)
Target: Lambda function ARN
```

### 11.5 IAM Permissions (Lambda Execution Role)

The Lambda role needs only:
- `s3:GetObject` / `s3:PutObject` on the config bucket
- `secretsmanager:GetSecretValue` for API keys
- `logs:CreateLogGroup` / `logs:PutLogEvents` for CloudWatch

### 11.6 Estimated Monthly Cost

| Component | Est. Cost |
|---|---|
| EventBridge Scheduler | Free |
| Lambda (31 invocations/mo) | < $0.01 |
| S3 (< 1 MB storage + minimal requests) | < $0.01 |
| Whisper API (audio transcription) | ~$0.50–$3.00 |
| Claude API (summarization) | ~$0.20–$1.00 |
| **Total** | **~$1–4/month** |

---

## 12. Environment Variables / Secrets

All secrets stored in **AWS Secrets Manager**. Lambda retrieves them at cold start.

| Secret Name | Purpose |
|---|---|
| `podcast/anthropic_api_key` | Claude API authentication |
| `podcast/openai_api_key` | Whisper API authentication |
| `podcast/ms_graph_token` | OneNote delivery via Microsoft Graph |
| `podcast/pocket_casts_email` | Pocket Casts account (if any show uses integration) |
| `podcast/pocket_casts_password` | Pocket Casts account (if any show uses integration) |

Lambda environment variables (non-secret):

| Variable | Purpose |
|---|---|
| `TZ` | Timezone (e.g. `America/New_York`) |
| `S3_BUCKET` | Name of the private S3 bucket |
| `CONFIG_KEY` | S3 key for config file (default: `config/podcasts.json`) |
| `LOG_KEY` | S3 key for log file (default: `logs/run_log.jsonl`) |

---

## 13. Infrastructure & Deployment

### 13.1 Tooling

**AWS SAM (Serverless Application Model)** — single `template.yaml` defines all infrastructure. Deployed with:

```bash
sam build && sam deploy --guided
```

Subsequent deploys (e.g. after updating the Lambda code):

```bash
sam build && sam deploy
```

### 13.2 SAM-Managed Resources

| Resource | SAM Type |
|---|---|
| Lambda function | `AWS::Serverless::Function` |
| EventBridge Scheduler rule | `AWS::Scheduler::Schedule` |
| S3 bucket (private) | `AWS::S3::Bucket` |
| Lambda execution IAM role | Auto-generated by SAM with least-privilege policy |
| Secrets Manager secrets | `AWS::SecretsManager::Secret` (placeholder values; filled manually post-deploy) |

### 13.3 Repository Structure

```
podcast-digest/
├── template.yaml               # SAM infrastructure definition
├── src/
│   └── handler.py              # Lambda entry point
│   └── fetcher.py              # RSS feed parsing + audio download
│   └── transcriber.py          # Whisper API integration
│   └── summarizer.py           # Claude API + prompt templates
│   └── delivery.py             # OneNote via Microsoft Graph
│   └── pocket_casts.py         # Pocket Casts integration
│   └── config.py               # S3 config read/write
│   └── logger.py               # Run log + cost reporting
├── requirements.txt
├── podcasts.json               # Local dev copy of config (never committed)
└── .env.example                # Example environment variables for local testing
```

### 13.4 Local Development & Testing

SAM supports local invocation via Docker:

```bash
sam local invoke PodcastDigestFunction --event events/test_event.json
```

A `--profile` flag targets a named AWS CLI profile so local runs use the same S3 bucket and Secrets Manager as production without hardcoding credentials.

---

## 14. Feedback Loop

### 14.1 Mechanism
User submits feedback via an **Apple Shortcut** on iPhone. The Shortcut calls a private **API Gateway** endpoint (POST), which writes a feedback record to S3. No auto-adjustment of config — all feedback is stored for the user's manual review and application.

### 14.2 Feedback Granularity
Two independent rating types per digest run:

| Type | Scope | Triggered by |
|---|---|---|
| Episode rating | A specific episode | User selects show → episode in Shortcut |
| Show quality rating | A show's summary quality that day | User selects show in Shortcut |

### 14.3 Feedback Dimensions
Each rating captures two independent axes:

| Dimension | Options |
|---|---|
| Verbosity | `too_long` · `just_right` · `too_short` |
| Tone | `too_dry` · `just_right` · `too_detailed` |

### 14.4 S3 Feedback Storage

```
s3://your-podcast-digest-bucket/
└── feedback/
    └── feedback_log.jsonl     # One JSON line appended per submission
```

Each feedback record:
```json
{
  "submitted_at": "2026-03-19T07:12:00Z",
  "type": "episode",
  "show_name": "Hardcore History",
  "episode_title": "Supernova in the East VI",
  "verbosity": "too_long",
  "tone": "just_right"
}
```

### 14.5 Apple Shortcut Flow
1. Shortcut fetches today's digest manifest from S3 (a lightweight JSON list of show + episode names written by each run)
2. User selects rating type (episode or show)
3. User selects show (and episode, if episode rating)
4. User selects verbosity and tone values from menus
5. Shortcut POSTs the feedback record to API Gateway
6. API Gateway invokes a small Lambda that appends the record to `feedback_log.jsonl`

### 14.6 Additional AWS Resources Required

| Resource | Purpose |
|---|---|
| API Gateway (HTTP API) | Private endpoint receiving Shortcut POST |
| Feedback Lambda | Validates and writes feedback record to S3 |
| Digest manifest (`s3://.../feedback/manifest.json`) | Written by main job each run; consumed by Shortcut to populate show/episode menus |

---

## 15. Overcast Deep Links

Each episode section in both the OneNote page and the SES email includes a dedicated **"Open in Overcast"** link at the end of the section.

### 15.1 Link Format
Overcast deep links use the scheme `overcast://x-callback-url/add?url={enclosure_url}` or the shareable web URL `overcast.fm/+{episode_id}`. Since episode IDs require prior subscription lookup, the reliable fallback is the **RSS enclosure URL** passed to Overcast's add handler:

```
overcast://x-callback-url/add?url=https://feed.example.com/episode.mp3
```

If the episode is already in the user's Overcast library, this opens it directly. If not, it offers to add it.

### 15.2 Placement
A single line at the end of each episode section, after quotes and resources:

```
▶ Open in Overcast
```

Rendered as a tappable hyperlink in both OneNote and the HTML email.

---

## 16. Email Delivery (SES)

A **condensed HTML email** is sent in parallel with the OneNote page after each run.

### 16.1 Content
The email is a condensed version of the digest — not a duplicate. For each show:
- Show name and cover art thumbnail
- For each new episode: episode title + first 2 sentences of the summary only
- "Open in Overcast" deep link per episode
- If no new episodes: the standard *"No new episodes since [date]"* line
- Errors section (if any), identical to the OneNote digest

The full summary, quotes, action items, tags, and resources are **OneNote-only** — the email serves as a scannable morning glance.

### 16.2 Format
- HTML email mirroring the visual layout of the OneNote page
- Inline CSS only (no external stylesheets — email client compatibility)
- Cover art thumbnails embedded as `<img>` tags pointing to RSS image URLs
- Plain text fallback not included (HTML only, per user preference)

### 16.3 Email Header
Matches the OneNote digest header:
- Date, total shows, total new episodes, total run cost

### 16.4 Additional AWS Resources Required

| Resource | Purpose |
|---|---|
| SES verified sender identity | Authorised sending address |
| SES sending via Lambda | Called from `delivery.py` after OneNote POST |
| `podcast/ses_from_address` secret | Verified sender email |
| `podcast/ses_to_address` secret | Recipient email (user's iPhone address) |

### 16.5 Email Subject Line
```
Podcast Digest — Thursday, March 19 2026 · 4 episodes across 3 shows
```

---

## 17. Out of Scope (for this version)

- Feedback loop / thumbs up-down on summaries
- Weekly meta-digest
- Listening queue integration beyond Pocket Casts
- Apple Notes or Notion delivery (OneNote only for v1)