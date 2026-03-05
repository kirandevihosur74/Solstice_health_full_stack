# Solistic Health — FRUZAQLA Content Generator

A proof-of-concept system enabling pharmaceutical marketers to generate FDA-compliant promotional content for **FRUZAQLA** (fruquintinib) through a conversational interface powered by **Anthropic Claude**.

## The Problem

Pharma companies need marketing content (emails, banner ads, social posts) where every statement must come from clinical literature or prior approved claims (FDA regulations). Content requires 5–10+ revision cycles and compliance checks before approval. This tool streamlines that workflow.

## Architecture

| Layer    | Stack                            | Port  |
|----------|----------------------------------|-------|
| Frontend | Next.js 15 (App Router, TS, TW)  | 3000  |
| Backend  | FastAPI + SQLite + Anthropic Claude | 8000  |
| LLM      | Claude (claude-sonnet-4-20250514) via Anthropic SDK | — |

## Quick Start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and fill in your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

## Environment Variables

| Variable                   | Default                  | Where    | Required |
|----------------------------|--------------------------|----------|----------|
| `ANTHROPIC_API_KEY`        | —                        | backend  | No*      |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000`  | frontend | No       |

\* Without `ANTHROPIC_API_KEY`, the app falls back to deterministic stub responses for chat, generate, and edit. All other functionality (claims, compliance checks, versioning) works without it.

## LLM Integration

The system uses Anthropic Claude for three capabilities:

| Feature | Endpoint | What Claude Does |
|---------|----------|------------------|
| **Conversational briefing** | `POST /chat` | Guides the user through audience, messaging, and content requirements with FRUZAQLA domain knowledge |
| **Content generation** | `POST /generate` | Generates complete HTML (email/banner/social) using only the approved claims provided, respecting FDA fair-balance rules |
| **Natural-language editing** | `POST /edit` | Applies arbitrary edits to HTML while preserving ISI, references, and compliance constraints |

Each function has a specialized system prompt that enforces:
- Only approved claim text may appear (no fabricated data)
- FDA fair balance (efficacy must be accompanied by safety)
- ISI and references sections are preserved
- Content is format-appropriate (email 640px, banner 728×90, social card)

If the LLM call fails or no API key is set, every endpoint gracefully falls back to deterministic stub logic.

## Workflow

1. **Landing** (`/`) — Choose content format (HCP email, banner ad, social post) and start a session.
2. **Briefing** (`/chat`) — Describe audience, key message, clinical focus. Claude asks targeted follow-ups.
3. **Preview** (`/preview`) — Select approved claims (grouped by category), run compliance checks, generate HTML via Claude, iterate with natural-language revisions, and manage version history.

## Claim Categories

Claims are seeded from FRUZAQLA clinical data:

| Category        | Source                | Example                                      |
|-----------------|-----------------------|----------------------------------------------|
| Efficacy        | FRESCO-2 (Lancet)     | OS 7.4 vs 4.8 months, HR 0.66               |
| Safety          | Prescribing Info §6.1 | Common ARs: hypertension, diarrhea, fatigue  |
| Indication      | Prescribing Info §1   | mCRC after prior chemo/biologic therapy      |
| Dosing          | Prescribing Info §2.1 | 5 mg QD, 3 weeks on / 1 week off            |
| Mechanism       | Prescribing Info §12  | Selective VEGFR-1/2/3 inhibitor              |
| Quality of Life | J Clin Oncol 2024     | TTD in QoL: 2.0 vs 1.2 months               |

## API Endpoints

| Method | Path                     | Description                                  | LLM? |
|--------|--------------------------|----------------------------------------------|------|
| GET    | `/health`                | Health check (includes `llm_enabled` flag)   | —    |
| POST   | `/session`               | Create session with content_type             | —    |
| POST   | `/chat`                  | Send message, get Claude reply               | Yes  |
| GET    | `/claims/recommended`    | Get claims ranked by conversation context    | —    |
| POST   | `/generate`              | Generate HTML from selected claims           | Yes  |
| POST   | `/edit`                  | Apply a natural-language revision            | Yes  |
| POST   | `/compliance-check`      | Run FDA fair-balance checks on claim set     | —    |
| GET    | `/versions`              | List versions for a session                  | —    |
| GET    | `/versions/{version_id}` | Get full HTML for a version                  | —    |

## Tech Stack

- **Frontend**: Next.js 15, TypeScript, Tailwind CSS v4
- **Backend**: FastAPI, SQLAlchemy, SQLite
- **LLM**: Anthropic Claude (via `anthropic` Python SDK)
- **No auth** — single anonymous user for prototype
