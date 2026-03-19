# podcast-digest

A personal morning podcast digest — summarizes new episodes from subscribed
shows each day at 5:45 AM and delivers a combined report to OneNote and email.

## Features

- Per-podcast verbosity, quotability, and transcript strategy
- Claude API summarization with topic tagging, guest extraction, and URL harvesting
- Overcast deep links per episode
- Error tracking with consecutive and cumulative day counters
- Condensed SES HTML email digest in parallel with OneNote
- Apple Shortcuts feedback loop (verbosity + tone per episode and show)
- Full cost reporting per run (Whisper + Claude API)

## Architecture

AWS Lambda · EventBridge Scheduler · S3 · Secrets Manager · SES · API Gateway  
Deployed via AWS SAM.

## Setup

See [SETUP.md](SETUP.md) for:
1. AWS prerequisites and IAM setup
2. SAM deployment walkthrough
3. Secrets Manager configuration
4. Uploading your podcasts.json to S3
5. Microsoft Graph / OneNote app registration
6. SES sender verification
7. Apple Shortcut installation

## Config Schema

See [config/podcasts.example.json](config/podcasts.example.json) for the full
per-podcast parameter reference.

## Local Development
```bash
pip install -r requirements-dev.txt
cp .env.example .env          # fill in your values
sam local invoke PodcastDigestFunction --event events/test_event.json
```

## Running Tests
```bash
pytest tests/
```
