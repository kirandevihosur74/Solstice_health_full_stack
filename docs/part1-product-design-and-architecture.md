# Part 1: Product Design & System Architecture

## 1.1 User Flow Design

### High-Level User Journey Map

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│  1. REQUEST  │────▶│  2. BRIEF (Chat) │────▶│  3. PREVIEW & GENERATE   │────▶│  4. EXPORT   │
│  CREATION    │     │                  │     │                          │     │              │
│  Landing (/) │     │  /chat           │     │  /preview                │     │  Download    │
└─────────────┘     └──────────────────┘     └──────────────────────────┘     └──────────────┘
```

#### Step 1: Request Creation (`/`)
```
User lands on homepage
    │
    ├── Selects Content Format (email / banner / social)
    ├── Selects Target Audience (HCP / patients / caregivers / payers)
    ├── Selects Campaign Goal (awareness / education / CTA / launch)
    ├── Selects Tone (clinical / empathetic / urgent / informative)
    │
    └── Clicks "Start Briefing"
            │
            ├── POST /session → creates session with all parameters
            ├── Stores session_id in localStorage
            └── Navigates to /chat
```

#### Step 2: Conversational Alignment (`/chat`)
```
User enters chat interface
    │
    ├── Suggestion chips shown for quick start
    ├── User describes content needs in natural language
    │       │
    │       └── POST /chat/stream → SSE streaming response
    │               │
    │               ├── "Thinking (Xs)..." indicator with timer
    │               ├── "Thought for X seconds" label appears
    │               └── Assistant streams character-by-character
    │
    ├── Assistant asks clarifying questions (2-3 rounds)
    ├── Assistant suggests specific approved claims with citations
    ├── User can Clear Chat to restart briefing
    │
    └── User clicks "Continue to Preview →"
            │
            └── Navigates to /preview (session context carries over)
```

#### Step 3: Claim Selection, Generation & Compliance (`/preview`)
```
Claims Library loads (GET /claims/recommended)
    │
    ├── Claims displayed grouped by category:
    │       Indication → Efficacy → Mechanism → Dosing → QoL → Safety
    │       Each shows: source badge, citation, approval date
    │
    ├── User selects claims (checkboxes, Select All / Clear)
    │       DECISION POINT: User explicitly approves each claim
    │
    ├── "Generate Content" → POST /generate
    │       │
    │       ├── LLM generates HTML (or stub fallback)
    │       ├── Saved as new Version in DB
    │       ├── Rendered in sandboxed iframe
    │       └── Auto-triggers compliance review
    │
    ├── Compliance Review Panel (12-point check):
    │       ├── ✅ Green = pass
    │       ├── ⚠️ Yellow = warning (non-blocking)
    │       └── ❌ Red = fail (blocks export)
    │
    ├── Iterative Editing Loop:
    │       ├── User types natural language instruction
    │       │       e.g., "Move safety above efficacy"
    │       ├── POST /edit → LLM or stub applies edit
    │       ├── New Version saved, compliance auto-rechecks
    │       └── Repeat until satisfied
    │
    ├── Version History:
    │       ├── All revisions listed with timestamps
    │       └── "Load" to restore any previous version
    │
    └── DECISION POINT: Export gate
            ├── If any ❌ red flags → export blocked
            └── If all pass/warn → "Export Package" enabled
```

#### Step 4: Export & Distribution
```
User clicks "Export Package"
    │
    ├── POST /export
    │       ├── Runs final compliance review
    │       ├── Blocks if any failures remain
    │       └── Returns package
    │
    └── Downloads 2 files:
            ├── fruzaqla-content-revN.html (self-contained HTML)
            └── fruzaqla-export-revN.json
                    ├── html: full HTML content
                    ├── metadata:
                    │       ├── session parameters
                    │       ├── claims_used (with sources, citations, approval dates)
                    │       ├── revision_number
                    │       └── asset_manifest
                    └── compliance_report:
                            ├── overall status
                            ├── reviewed_at timestamp
                            └── all check results
```

### Key Decision Points & Interaction Patterns

| Decision Point | User Control | System Control |
|---|---|---|
| Content parameters | User selects format, audience, goal, tone | System constrains to valid options |
| Briefing conversation | User describes needs freely | AI guides with questions, suggests claims |
| Claim selection | User explicitly checks each claim | System scores & ranks by relevance |
| Content generation | User triggers generation | LLM/stub assembles HTML with compliance rules |
| Editing | User describes edits in natural language | System applies while preserving compliance |
| Compliance review | User reviews results | System blocks export on failures |
| Export | User initiates export | System gates on compliance pass |

### Balance: User Autonomy vs. Guided Experience

```
MORE GUIDED ◄──────────────────────────────────────────────► MORE AUTONOMOUS
    │                                                              │
    ├── Landing page: constrained selectors           ├── Free-text chat input
    ├── Suggestion chips for first message             ├── Any claims can be selected
    ├── AI-suggested claims during chat                ├── Natural language editing
    ├── Compliance blocks on red flags                 ├── User chooses when to generate
    └── Mandatory fair balance (safety + efficacy)     └── User decides final export timing
```

**Philosophy:** Guide users through compliance guardrails while giving them full creative control over messaging priorities and content structure.

### Where AI/Automation Fits vs. Human Control

| Layer | AI/Automated | Human-Controlled |
|---|---|---|
| **Requirements gathering** | AI asks clarifying questions, suggests claims | User provides creative direction |
| **Claim scoring** | System scores claims by conversation keywords | User makes final selection |
| **HTML generation** | LLM assembles compliant HTML from claims | User reviews output |
| **Editing** | LLM interprets NL instructions | User decides what to change |
| **Compliance** | Deterministic rules engine (no LLM) | User resolves flagged issues |
| **Export** | Automated packaging | User triggers download |

### Discussion: Why This Flow Over Alternatives?

**Alternative 1: Form-based wizard (no chat)**
- Rejected because: marketing managers need flexibility to express priorities that checkboxes can't capture. Chat captures nuance like "lead with survival data, but make dosing the secondary hook."

**Alternative 2: Free-form editor with AI sidebar**
- Rejected because: too much autonomy risks non-compliant content. Our flow ensures claims are pre-approved before generation, and compliance is checked before export.

**Alternative 3: Fully automated (input brief → output HTML)**
- Rejected because: FDA compliance requires human-in-the-loop for claim approval. Every claim must be explicitly selected, and the user must review compliance results.

### Critical UX Decisions & Trade-offs

1. **Explicit claim approval before generation**
   - *Trade-off:* Adds friction (user must check boxes) vs. could auto-select based on chat
   - *Why:* FDA traceability requires each claim to be explicitly approved. This creates an audit trail. Auto-selection would be a compliance risk.

2. **Compliance blocks export, not generation**
   - *Trade-off:* User can generate non-compliant content (to see it) but can't export it
   - *Why:* Lets users iterate and fix issues rather than blocking them upfront. Faster creative cycle.

3. **Streaming chat with thinking indicator**
   - *Trade-off:* Adds complexity vs. simple request-response
   - *Why:* Marketing managers expect ChatGPT-like responsiveness. Perceived latency drops significantly.

### Edge Case Handling

| Edge Case | How It's Handled |
|---|---|
| **Unclear request** | Chat assistant asks follow-up questions; suggestion chips guide first message |
| **No claims selected** | Generate button disabled; compliance review shows "No claims selected" failure |
| **Only efficacy claims (no safety)** | Compliance review flags "FDA Fair Balance" as ❌ fail; export blocked |
| **LLM unavailable** | Graceful fallback to deterministic stub responses; app remains fully functional |
| **Edit destroys compliance** | Auto-recheck after every edit; user sees updated compliance panel immediately |
| **Invalid session** | Frontend redirects to landing page; backend returns 404 |
| **Large HTML (>100KB email)** | Channel compatibility check warns about email client limits |

---

## 1.2 System Architecture

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js 15)                       │
│                         localhost:3000                               │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────────────────┐  │
│  │ Landing   │   │ Chat         │   │ Preview                    │  │
│  │ Page (/)  │   │ Page (/chat) │   │ Page (/preview)            │  │
│  │           │   │              │   │                            │  │
│  │ • Format  │   │ • SSE stream │   │ • Claims library           │  │
│  │ • Audience│──▶│ • Markdown   │──▶│ • HTML generation          │  │
│  │ • Goal    │   │ • Thinking UI│   │ • iframe preview           │  │
│  │ • Tone    │   │ • History    │   │ • NL editing               │  │
│  │           │   │              │   │ • Compliance panel          │  │
│  │           │   │              │   │ • Version history           │  │
│  │           │   │              │   │ • Export                    │  │
│  └──────────┘   └──────────────┘   └────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  lib/api.ts — Centralized API layer                          │   │
│  │  • Logging (timestamped, color-coded)                        │   │
│  │  • SSE streaming with character-by-character rendering       │   │
│  │  • Error handling                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  State: React useState + useEffect | Session: localStorage          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP (JSON + SSE)
                                │ CORS: localhost:3000
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        BACKEND (FastAPI)                            │
│                        localhost:8000                                │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  HTTP Middleware                                              │   │
│  │  • Request/response logging with timing                      │   │
│  │  • CORS middleware                                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  API Endpoints Layer (main.py)                               │    │
│  │                                                              │    │
│  │  Session Management    Chat & Streaming    Content Pipeline  │    │
│  │  ├── POST /session     ├── POST /chat      ├── POST /generate│   │
│  │  ├── GET /session/:id  ├── POST /chat/stream├── POST /edit   │    │
│  │  │                     ├── GET /messages    ├── GET /versions │    │
│  │  │                     └── DELETE /messages └── GET /ver/:id  │    │
│  │  │                                                           │    │
│  │  Claims & Compliance          Export                         │    │
│  │  ├── GET /claims/recommended  └── POST /export               │    │
│  │  ├── POST /compliance-review                                 │    │
│  │  └── POST /compliance-check (legacy)                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────┐   ┌─────────────────────────────────────┐  │
│  │  LLM Integration   │   │  Compliance Rules Engine            │  │
│  │  (llm.py)          │   │  (Deterministic — no LLM)           │  │
│  │                    │   │                                     │  │
│  │  • chat_reply()    │   │  12 checks:                         │  │
│  │  • chat_reply_     │   │  1. Claim library match             │  │
│  │    stream()        │   │  2. Source traceability              │  │
│  │  • generate_       │   │  3. FDA fair balance                │  │
│  │    content()       │   │  4. ISI section present             │  │
│  │  • edit_content()  │   │  5. PI reference                    │  │
│  │                    │   │  6. HCP designation                 │  │
│  │  Fallback: stubs   │   │  7. Indication statement            │  │
│  │  if no API key     │   │  8. References section              │  │
│  └────────┬───────────┘   │  9. Visual assets                   │  │
│           │               │  10. Channel compatibility           │  │
│           ▼               │  11. Claim approval status           │  │
│  ┌────────────────────┐   │  12. Legal footer                   │  │
│  │  Anthropic Claude  │   └─────────────────────────────────────┘  │
│  │  API (External)    │                                            │
│  │                    │   ┌─────────────────────────────────────┐  │
│  │  Model: claude-    │   │  Stub Fallback Layer                │  │
│  │  sonnet-4-20250514 │   │                                     │  │
│  │                    │   │  • _stub_assistant_reply()           │  │
│  │  3 system prompts: │   │  • _build_html() (email/banner/     │  │
│  │  • Chat            │   │    social templates)                │  │
│  │  • Generate        │   │  • _apply_edit() (6 deterministic   │  │
│  │  • Edit            │   │    edit patterns)                   │  │
│  └────────────────────┘   └─────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Data Layer (database.py + SQLAlchemy ORM)                    │   │
│  │                                                               │   │
│  │  SQLite: pharma_marketing.db                                  │   │
│  │  ├── sessions (id, content_type, audience, campaign_goal,     │   │
│  │  │            tone, created_at)                               │   │
│  │  ├── messages (id, session_id FK, role, content, created_at)  │   │
│  │  ├── claims   (id, text, citation, source, category,          │   │
│  │  │            compliance_status, approved_date, created_at)   │   │
│  │  └── versions (id, session_id FK, html, content_type,         │   │
│  │               revision_number, claim_ids_used, created_at)    │   │
│  │                                                               │   │
│  │  Seed: 10 FRUZAQLA approved claims on first startup           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Frontend Architecture Detail

```
frontend/
├── app/
│   ├── layout.tsx          ← Root layout (nav, fonts, metadata)
│   ├── globals.css         ← Tailwind + CSS custom properties
│   ├── page.tsx            ← Landing page (session creation)
│   ├── chat/
│   │   └── page.tsx        ← Chat interface (SSE streaming, thinking UI)
│   └── preview/
│       └── page.tsx        ← Claims, generation, compliance, export
├── lib/
│   └── api.ts              ← All API calls, SSE streaming, logging
└── .env.local              ← NEXT_PUBLIC_API_BASE_URL
```

**State Management Strategy:**
- `useState` + `useEffect` for component-local state
- `localStorage` for cross-page session persistence (session_id, content_type)
- `useRef` for mutable values in closures (streaming state, timers)
- No global state store needed — data flows through API calls

**Routing:** Next.js App Router with 3 routes (`/`, `/chat`, `/preview`)

### Discussion Points

#### Scalability Considerations
- **Current:** SQLite (single-file, no concurrency) — suitable for POC
- **Production path:** PostgreSQL for multi-user concurrency; Redis for session caching; CDN for generated HTML assets
- **LLM scaling:** Anthropic API handles scaling; add request queuing for burst traffic
- **Frontend:** Next.js supports SSR/ISR for static pages; chat is fully client-side

#### Real-Time Collaboration (Multiple Users)
- **Current:** Single-user sessions; no shared editing
- **Production path:** WebSocket layer for real-time sync; operational transforms or CRDTs for concurrent edits; role-based access (editor, reviewer, approver)

#### Compliance Audit Trail
- **Current:** Every version is persisted with `claim_ids_used` and timestamps; compliance reviews are generated on-demand
- **Production path:** Immutable audit log table; store every compliance check result permanently; digital signatures on approved exports; user attribution on every action

#### Performance Optimization
- **SSE streaming** eliminates perceived latency for chat
- **Character-by-character rendering** with buffered queue prevents UI jank
- **Claim scoring** is O(n) simple keyword matching — fast even at scale
- **Compliance checks** are deterministic regex/string operations — sub-millisecond
- **Production path:** Cache claims list; pre-compute compliance on save; lazy-load version history

---

## 1.3 Data Model Design

### Entity-Relationship Diagram

```
┌──────────────────────────┐
│         SESSION           │
├──────────────────────────┤
│ id          : UUID (PK)  │
│ content_type: string     │──── "email" | "banner" | "social"
│ audience    : string     │──── "hcp" | "patients" | "caregivers" | "payers"
│ campaign_goal: string    │──── "awareness" | "education" | "cta" | "launch"
│ tone        : string     │──── "clinical" | "empathetic" | "urgent" | "informative"
│ created_at  : datetime   │
└──────────┬───────────────┘
           │ 1
           │
           │ N
┌──────────▼───────────────┐        ┌──────────────────────────────┐
│         MESSAGE           │        │           CLAIM              │
├──────────────────────────┤        ├──────────────────────────────┤
│ id         : UUID (PK)   │        │ id               : UUID (PK)│
│ session_id : UUID (FK)   │────┐   │ text             : text     │
│ role       : string      │    │   │ citation         : text     │
│ content    : text        │    │   │ source           : string   │──── "clinical_literature"
│ created_at : datetime    │    │   │                  :          │     | "prior_approved"
└──────────────────────────┘    │   │ category         : string   │──── "efficacy" | "safety"
                                │   │                  :          │     | "indication" | "dosing"
                                │   │                  :          │     | "mechanism"
                                │   │                  :          │     | "quality_of_life"
                                │   │ compliance_status: string   │──── "approved" | "pending"
                                │   │ approved_date    : string?  │
                                │   │ created_at       : datetime │
                                │   └──────────────────────────────┘
                                │           ▲
                                │           │ referenced by (JSON list of IDs)
           ┌────────────────────┘           │
           │ 1                              │
           │                                │
           │ N                              │
┌──────────▼───────────────┐                │
│         VERSION           │                │
├──────────────────────────┤                │
│ id             : UUID (PK)│               │
│ session_id     : UUID (FK)│               │
│ html           : text     │               │
│ content_type   : string   │               │
│ revision_number: integer  │               │
│ claim_ids_used : text?    │───────────────┘  (JSON-serialized list of claim UUIDs)
│ created_at     : datetime │
└──────────────────────────┘
```

### Relationships

| Relationship | Type | Description |
|---|---|---|
| Session → Message | 1:N | Each session has many chat messages |
| Session → Version | 1:N | Each session has many content revisions |
| Version → Claim | N:M | Each version references multiple claims via `claim_ids_used` (JSON) |
| Claim | Standalone | Seeded library, not tied to sessions |

### Schema Definitions (SQLAlchemy)

```python
class Session(Base):
    __tablename__ = "sessions"
    id              = Column(String, primary_key=True)     # UUID
    content_type    = Column(Text, nullable=False)          # "email" | "banner" | "social"
    audience        = Column(String, nullable=False)        # "hcp" | "patients" | ...
    campaign_goal   = Column(String, nullable=False)        # "awareness" | "education" | ...
    tone            = Column(String, nullable=False)        # "clinical" | "empathetic" | ...
    created_at      = Column(DateTime)

class Message(Base):
    __tablename__ = "messages"
    id              = Column(String, primary_key=True)     # UUID
    session_id      = Column(String, ForeignKey("sessions.id"))
    role            = Column(String, nullable=False)        # "user" | "assistant"
    content         = Column(Text, nullable=False)
    created_at      = Column(DateTime)

class Claim(Base):
    __tablename__ = "claims"
    id                = Column(String, primary_key=True)   # UUID
    text              = Column(Text, nullable=False)        # Exact approved claim text
    citation          = Column(Text, nullable=False)        # Source citation
    source            = Column(String, nullable=False)      # "clinical_literature" | "prior_approved"
    category          = Column(String, nullable=False)      # "efficacy" | "safety" | ...
    compliance_status = Column(String, nullable=False)      # "approved" | "pending"
    approved_date     = Column(String, nullable=True)       # ISO date string
    created_at        = Column(DateTime)

class Version(Base):
    __tablename__ = "versions"
    id              = Column(String, primary_key=True)     # UUID
    session_id      = Column(String, ForeignKey("sessions.id"))
    html            = Column(Text, nullable=False)          # Full HTML content
    content_type    = Column(String, nullable=False)
    revision_number = Column(Integer, nullable=False)
    claim_ids_used  = Column(Text, nullable=True)          # JSON list of claim UUIDs
    created_at      = Column(DateTime)
```

### Seed Data: Approved Claims Library (10 claims)

| # | Category | Source | Claim (truncated) | Citation |
|---|---|---|---|---|
| 1 | efficacy | clinical_literature | FRUZAQLA demonstrated statistically significant OS improvement... | Dasari A, et al. Lancet 2023 (FRESCO-2) |
| 2 | efficacy | clinical_literature | Median PFS 3.7 vs 1.8 months... | Dasari A, et al. Lancet 2023 (FRESCO-2) |
| 3 | efficacy | clinical_literature | ORR 1.8% vs 0%; DCR 55.5% vs 16.1%... | Dasari A, et al. Lancet 2023 (FRESCO-2) |
| 4 | indication | prior_approved | FRUZAQLA indicated for adult mCRC patients... | Prescribing Information, Section 1 |
| 5 | safety | prior_approved | Most common ARs (≥20%): hypertension, diarrhea... | Prescribing Information, Section 6.1 |
| 6 | safety | prior_approved | Serious ARs in 40%: hepatotoxicity, infection... | Prescribing Information, Section 6.1 |
| 7 | dosing | prior_approved | 5 mg orally once daily, 3 weeks on / 1 week off... | Prescribing Information, Section 2.1 |
| 8 | efficacy | clinical_literature | OS benefit consistent across subgroups... | Dasari A, et al. Lancet 2023 (FRESCO-2 Suppl.) |
| 9 | quality_of_life | clinical_literature | TTD in QoL: 2.0 vs 1.2 months... | Eng C, et al. J Clin Oncol 2024 |
| 10 | mechanism | prior_approved | Selective VEGFR-1/2/3 inhibitor... | Prescribing Information, Section 12.1 |

### Production Extensions (Not Yet Implemented)

```
┌──────────────────────────┐     ┌──────────────────────────┐
│     VISUAL_ASSET          │     │     USER                  │
├──────────────────────────┤     ├──────────────────────────┤
│ id         : UUID (PK)   │     │ id         : UUID (PK)   │
│ filename   : string      │     │ email      : string      │
│ asset_type : string      │     │ role       : string      │ ── "editor"|"reviewer"|"admin"
│ approval_id: string      │     │ created_at : datetime    │
│ mime_type  : string      │     └──────────┬───────────────┘
│ url        : string      │                │
│ approved_at: datetime    │     ┌──────────▼───────────────┐
│ created_at : datetime    │     │     AUDIT_LOG             │
└──────────────────────────┘     ├──────────────────────────┤
                                 │ id         : UUID (PK)   │
┌──────────────────────────┐     │ user_id    : UUID (FK)   │
│  COMPLIANCE_RESULT        │     │ session_id : UUID (FK)   │
├──────────────────────────┤     │ action     : string      │
│ id         : UUID (PK)   │     │ detail     : JSON        │
│ version_id : UUID (FK)   │     │ created_at : datetime    │
│ overall    : string      │     └──────────────────────────┘
│ can_export : boolean     │
│ checks     : JSON        │
│ reviewed_at: datetime    │
└──────────────────────────┘
```

### Compliance Check Matrix

| # | Check | Logic | Pass | Warn | Fail |
|---|---|---|---|---|---|
| 1 | Claim Library Match | Every selected claim exists in approved library | All match | — | Any mismatch |
| 2 | Source Traceability | All claims have citations + valid source type | All traceable | — | Missing citation |
| 3 | FDA Fair Balance | Efficacy claims require safety claims | Both present | No efficacy | Efficacy without safety |
| 4 | ISI Section | HTML contains "Important Safety Information" | Found | — | Missing |
| 5 | PI Reference | HTML mentions "Prescribing Information" | Found | Not found | — |
| 6 | HCP Designation | HTML contains "healthcare professional" | Found | Not found | — |
| 7 | Indication Statement | Indication claim is selected | Selected | Not selected | — |
| 8 | References Section | HTML has "References" or "Citations" | Found | — | Missing |
| 9 | Visual Assets | No unauthorized images | Text-only (pass) | — | Unauthorized found |
| 10 | Channel Compatibility | HTML size within channel limits | Within limits | Email >100KB | — |
| 11 | Claim Approval Status | All claims have "approved" status | All approved | — | Non-approved found |
| 12 | Legal Footer | HTML has trademark/copyright | Found | Not found | — |

**Export Gate:** `can_export = true` only when zero ❌ fail results.
