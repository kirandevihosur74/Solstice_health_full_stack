"""
Anthropic Claude integration for pharma marketing content generation.

Falls back to stub responses when ANTHROPIC_API_KEY is not set,
so the app remains functional without an API key.
"""

import os
import logging
from typing import Optional, Generator

logger = logging.getLogger(__name__)

_client = None
_available = False

MODEL = "claude-sonnet-4-20250514"


def _get_client():
    global _client, _available
    if _client is not None:
        return _client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — LLM features disabled, using stubs")
        _available = False
        return None

    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        _available = True
        logger.info("Anthropic client initialized successfully")
        return _client
    except Exception as e:
        logger.error("Failed to initialize Anthropic client: %s", e)
        _available = False
        return None


def is_available() -> bool:
    _get_client()
    return _available


def get_client():
    """Return Anthropic client for use by ingestion and other modules."""
    return _get_client()


# ── System Prompts ───────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """You are an expert pharmaceutical marketing assistant specializing in FRUZAQLA (fruquintinib), a selective VEGFR-1/2/3 inhibitor indicated for metastatic colorectal cancer (mCRC).

Your role is to help marketing managers create FDA-compliant promotional content through a guided conversation. You must:

1. GATHER REQUIREMENTS by asking about:
   - Key messaging focus (efficacy/OS data, mechanism of action, dosing convenience, safety profile)
   - Specific clinical data points they want to highlight
   - Content structure preferences
   - Any specific claims they want to prioritize

2. SUGGEST relevant approved claims during the conversation. When the user describes what they want, mention specific claims they should consider, using the format: "I'd recommend including the claim: '[exact claim text]' sourced from [citation]"

3. GUIDE the user toward the Preview tab when you have enough context (typically after 2-3 exchanges).

4. ALWAYS stay within approved clinical data:
   - FRESCO-2 trial: Median OS 7.4 vs 4.8 months (HR 0.66, P<0.001), PFS 3.7 vs 1.8 months
   - DCR 55.5% vs 16.1%, OS benefit consistent across subgroups
   - QoL: TTD 2.0 vs 1.2 months (HR 0.67)
   - Common adverse reactions (≥20%): hypertension, diarrhea, fatigue, PPES, decreased appetite, stomatitis
   - Serious ARs in 40%: hepatotoxicity, infection, hemorrhage
   - Dosing: 5 mg QD, 3 weeks on / 1 week off, oral with or without food
   - Selective VEGFR-1/2/3 inhibitor targeting tumor angiogenesis

5. NEVER fabricate clinical data, statistics, or claims not in the approved set.

6. Keep responses concise (2-4 sentences typically). Be professional but approachable — your users are marketing managers, not clinicians.

7. Remind users that every claim must be explicitly approved before generation, and that compliance checks will run before export.

SESSION CONTEXT:
- Content format: {content_type}
- Target audience: {audience}
- Campaign goal: {campaign_goal}
- Tone: {tone}"""

GENERATE_SYSTEM_PROMPT = """You are an expert pharmaceutical HTML content generator. You create FDA-compliant promotional materials for FRUZAQLA (fruquintinib).

STRICT RULES:
1. Output ONLY valid HTML — no markdown, no explanation, no preamble. Your entire response must be a single HTML document starting with <!DOCTYPE html>.
2. ONLY use the exact claim text provided — never paraphrase, summarize, or invent clinical data.
3. Every piece must include an Important Safety Information (ISI) section if efficacy claims are present (FDA fair balance).
4. Include a References section citing the source of each claim used. Format: "This claim sourced from: [citation]"
5. Include the legal footer: "FRUZAQLA is a registered trademark. © 2025 Takeda Pharmaceutical Company Limited. All rights reserved. US-FRZ-2500001 03/2025"
6. Add "For US healthcare professionals only" where appropriate.
7. Use inline CSS only (no external stylesheets) so the HTML is fully self-contained.
8. Apply brand guidelines with visual hierarchy:
   - Primary: #0f4c75 (dark blue)
   - Secondary: #1b262c (very dark blue)
   - Accent: #bbe1fa (light blue)
   - Safety warning: #d35400 (orange) / #c0392b (red)
9. Maintain compliance metadata as data attributes on claim elements: data-claim-source="clinical_literature|prior_approved"

SESSION CONTEXT:
- Content format: {content_type}
- Target audience: {audience}
- Campaign goal: {campaign_goal}
- Tone: {tone}

FORMAT-SPECIFIC GUIDANCE:
- email: Max-width 640px container, header with brand, indication bar, efficacy section, safety section, CTA button, references footer. Professional HCP email layout.
- banner: 728×90px leaderboard format. Brand name, single headline claim, CTA button. ISI in tiny text below.
- social: Card-style layout, max-width 480px. Header, 2-3 key bullet points, ISI footer.

CONVERSATION CONTEXT (use to inform tone/emphasis, but ONLY use approved claim text):
{conversation_context}"""

EDIT_SYSTEM_PROMPT = """You are an expert pharmaceutical HTML editor. You modify FDA-compliant marketing content for FRUZAQLA (fruquintinib).

STRICT RULES:
1. Output ONLY the complete modified HTML document — no explanation, no markdown wrapping, no preamble.
2. NEVER remove or alter the Important Safety Information section unless explicitly asked.
3. NEVER remove the References section or legal footer.
4. NEVER fabricate or add clinical data that wasn't in the original HTML.
5. NEVER remove the "For US healthcare professionals only" designation.
6. Maintain FDA fair balance — if efficacy claims are present, safety information must also be present.
7. Preserve all inline CSS styling unless the edit specifically requests style changes.
8. If the user's request would violate FDA compliance rules, make the closest compliant change and add an HTML comment noting the constraint.

Apply the following edit instruction to the HTML below."""


# ── LLM Call Functions ───────────────────────────────────────────────

def chat_reply(
    conversation_history: list[dict],
    session_context: dict,
) -> Optional[str]:
    """Generate an assistant reply for the briefing chat."""
    client = _get_client()
    if not client:
        logger.info("[LLM:chat] Client unavailable — returning None for stub fallback")
        return None

    system = CHAT_SYSTEM_PROMPT.format(
        content_type=session_context.get("content_type", "email"),
        audience=session_context.get("audience", "hcp"),
        campaign_goal=session_context.get("campaign_goal", "awareness"),
        tone=session_context.get("tone", "clinical"),
    )

    messages = []
    for msg in conversation_history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    logger.info(
        "[LLM:chat] Sending %d messages to Claude (model=%s, max_tokens=512, context=%s)",
        len(messages), MODEL, session_context,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=system,
            messages=messages,
        )
        reply = response.content[0].text
        logger.info(
            "[LLM:chat] Response received — %d chars, usage: input=%s output=%s, stop_reason=%s",
            len(reply),
            getattr(response.usage, "input_tokens", "?"),
            getattr(response.usage, "output_tokens", "?"),
            response.stop_reason,
        )
        return reply
    except Exception as e:
        logger.error("[LLM:chat] Claude API call failed: %s", e, exc_info=True)
        return None


def chat_reply_stream(
    conversation_history: list[dict],
    session_context: dict,
) -> Optional[Generator[str, None, None]]:
    """Stream an assistant reply token-by-token for the briefing chat."""
    client = _get_client()
    if not client:
        logger.info("[LLM:chat_stream] Client unavailable — returning None for stub fallback")
        return None

    system = CHAT_SYSTEM_PROMPT.format(
        content_type=session_context.get("content_type", "email"),
        audience=session_context.get("audience", "hcp"),
        campaign_goal=session_context.get("campaign_goal", "awareness"),
        tone=session_context.get("tone", "clinical"),
    )

    messages = [{"role": m["role"], "content": m["content"]} for m in conversation_history]

    logger.info(
        "[LLM:chat_stream] Streaming %d messages to Claude (model=%s, max_tokens=512)",
        len(messages), MODEL,
    )

    try:
        def _generate():
            total_chars = 0
            with client.messages.stream(
                model=MODEL,
                max_tokens=512,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    total_chars += len(text)
                    yield text
            logger.info("[LLM:chat_stream] Stream complete — %d chars total", total_chars)

        return _generate()
    except Exception as e:
        logger.error("[LLM:chat_stream] Claude streaming failed: %s", e, exc_info=True)
        return None


def generate_content(
    claims: list[dict],
    session_context: dict,
    conversation_context: str,
) -> Optional[str]:
    """Generate HTML content from approved claims."""
    client = _get_client()
    if not client:
        logger.info("[LLM:generate] Client unavailable — returning None for stub fallback")
        return None

    content_type = session_context.get("content_type", "email")

    claims_block = "\n".join(
        f"- [{c['category'].upper()}] {c['text']} (Source: {c['citation']})"
        for c in claims
    )

    system = GENERATE_SYSTEM_PROMPT.format(
        content_type=content_type,
        audience=session_context.get("audience", "hcp"),
        campaign_goal=session_context.get("campaign_goal", "awareness"),
        tone=session_context.get("tone", "clinical"),
        conversation_context=conversation_context or "(No conversation context available)",
    )

    user_prompt = (
        f"Generate a {content_type} using EXACTLY these approved claims:\n\n"
        f"{claims_block}\n\n"
        f"Output only the complete HTML document."
    )

    logger.info(
        "[LLM:generate] Requesting %s HTML from Claude — %d claims, model=%s, max_tokens=4096",
        content_type, len(claims), MODEL,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        html = response.content[0].text.strip()
        if html.startswith("```"):
            html = html.split("\n", 1)[1] if "\n" in html else html
            if html.endswith("```"):
                html = html[:-3].strip()
        logger.info(
            "[LLM:generate] HTML generated — %d chars, usage: input=%s output=%s, stop_reason=%s",
            len(html),
            getattr(response.usage, "input_tokens", "?"),
            getattr(response.usage, "output_tokens", "?"),
            response.stop_reason,
        )
        return html
    except Exception as e:
        logger.error("[LLM:generate] Claude API call failed: %s", e, exc_info=True)
        return None


def edit_content(
    current_html: str,
    instruction: str,
) -> Optional[str]:
    """Apply a natural-language edit to existing HTML content."""
    client = _get_client()
    if not client:
        logger.info("[LLM:edit] Client unavailable — returning None for stub fallback")
        return None

    user_prompt = (
        f"EDIT INSTRUCTION: {instruction}\n\n"
        f"CURRENT HTML:\n{current_html}"
    )

    logger.info(
        "[LLM:edit] Sending edit request to Claude — instruction='%s', html_size=%d chars, model=%s",
        instruction[:80], len(current_html), MODEL,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=EDIT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        html = response.content[0].text.strip()
        if html.startswith("```"):
            html = html.split("\n", 1)[1] if "\n" in html else html
            if html.endswith("```"):
                html = html[:-3].strip()
        logger.info(
            "[LLM:edit] Edited HTML received — %d chars (delta %+d), usage: input=%s output=%s",
            len(html), len(html) - len(current_html),
            getattr(response.usage, "input_tokens", "?"),
            getattr(response.usage, "output_tokens", "?"),
        )
        return html
    except Exception as e:
        logger.error("[LLM:edit] Claude API call failed: %s", e, exc_info=True)
        return None
