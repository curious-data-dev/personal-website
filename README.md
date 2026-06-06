# RSS Digest — Personal News Aggregator

A personal news aggregation and summarization engine that transforms high-volume RSS feeds into concise, daily digestible summaries — accessible from any device via a web interface.

## Problem It Solves

Information overload. Hundreds of news articles published daily, most of them long but low-substance. RSS Digest scrapes your chosen feeds, extracts article text, summarizes each article via LLM (Gemini/Groq), and produces a daily digest you can read in 5 minutes.

## Architecture

```
Single VPS ($5-6/mo) → Docker Container → One Python Process
├── APScheduler  — daily scrape + summarize at 8 PM IST
├── FastAPI      — web server (Jinja2 templates)
├── Scraper      — feedparser + trafilatura + Playwright fallback
├── Summarizer   — Map-Reduce LLM chunking (Gemini / Groq)
└── SQLite       — single-file database (zero config)
```

## Quick Start

### 1. Clone & configure

```bash
git clone <repo-url>
cd rss-aggregator
cp .env.example .env
# Edit .env with your API keys (at least GEMINI_API_KEY or GROQ_API_KEY)
```

### 2. Run with Docker

```bash
docker compose up -d --build
curl http://localhost:8000/health
# → {"status": "ok"}
```

### 3. Open in browser

Navigate to `http://localhost:8000`

### 4. Manual trigger (first run)

Go to `/admin`, log in (credentials from `.env`), and click "Run Scrape Now" → "Run Summarization Now".

The scheduler will automatically run daily at 8:00 PM IST after that.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Gemini API key (free tier: 1500 req/day) |
| `GROQ_API_KEY` | — | Groq API key (fallback provider) |
| `LLM_PROVIDER` | `gemini` | Which LLM to use: `gemini` or `groq` |
| `OPML_PATH` | `RSS Feeds main.xml` | Path to OPML export |
| `SCRAPE_CRON_HOUR` | `20` | Hour for daily scrape (0-23, IST) |
| `SCRAPE_CRON_MINUTE` | `0` | Minute for daily scrape |
| `WEB_USERNAME` | `admin` | Admin panel username |
| `WEB_PASSWORD` | `changeme` | Admin panel password |

## Directory Structure

```
├── app/
│   ├── main.py              # FastAPI + Scheduler entry point
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLite init + CRUD
│   ├── models.py            # Dataclasses
│   ├── scraper/             # Data acquisition
│   │   ├── feed_reader.py   # OPML parser + RSS fetcher
│   │   ├── article_extractor.py  # trafilatura + Playwright
│   │   └── service.py       # Orchestration
│   ├── summarizer/          # LLM summarization
│   │   ├── chunker.py       # Text splitting
│   │   ├── llm.py           # Gemini/Groq with retry
│   │   └── service.py       # Map-Reduce pipeline
│   ├── web/                 # Web interface
│   │   ├── routes.py        # FastAPI routes
│   │   ├── templates/       # Jinja2 HTML
│   │   └── static/          # CSS
│   └── notifier/            # Optional email
│       └── emailer.py       # Gmail SMTP
├── data/                    # SQLite DB (Docker volume)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Deployment (5 minutes)

```bash
ssh root@your-vps-ip
curl -fsSL https://get.docker.com | sh
git clone <repo-url> && cd rss-aggregator
cp .env.example .env && nano .env    # Fill in API keys
docker compose up -d --build
```

For secure access from all devices, use **Tailscale** (free mesh VPN) — install on VPS and your devices. No ports exposed to the internet.

## How It Works

1. **Scrape** (daily at 8 PM IST): Reads OPML → fetches RSS feeds → extracts article text (trafilatura, Playwright fallback) → stores in SQLite
2. **Summarize** (after scrape): For each article, chunks text at paragraph boundaries → sends chunks to LLM in parallel (Map) → synthesizes into one summary (Reduce)
3. **Digest** (after summarization): Synthesizes all article summaries into a structured daily digest
4. **Browse** (anytime): FastAPI serves digest pages from SQLite — instant, no LLM calls

## Why This Architecture

- **Single process**: No Redis, no Celery, no PostgreSQL. One Python process, one SQLite file.
- **Docker parity**: Playwright runs identically on dev machine and VPS.
- **Map-Reduce chunking**: Handles articles of any length without token limit issues.
- **Exponential backoff**: Up to 5 retries on LLM rate-limit/500 errors.
- **Cost**: $0 in LLM costs (free tiers), $5-6/mo VPS, zero other costs.

## License

MIT — built for one person, for life.
