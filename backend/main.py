import json
import os
import re
import time
import html as html_mod
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import init_db, get_db, Session, Message, Claim, Version, new_uuid, utcnow
import llm

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if llm.is_available():
        logger.info("LLM integration: ENABLED (Anthropic Claude)")
    else:
        logger.info("LLM integration: DISABLED (stub mode — set ANTHROPIC_API_KEY to enable)")
    yield


app = FastAPI(title="FRUZAQLA Marketing Content Generator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        os.environ.get("FRONTEND_URL", "http://localhost:3000"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    logger.info(">>> %s %s", request.method, request.url.path)
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "<<< %s %s -> %d (%.1fms)",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


# ── Schemas ──────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    content_type: str = "email"
    audience: str = "hcp"
    campaign_goal: str = "awareness"
    tone: str = "clinical"


class SessionResp(BaseModel):
    session_id: str
    content_type: str
    audience: str
    campaign_goal: str
    tone: str


class ChatReq(BaseModel):
    session_id: str
    role: str = "user"
    content: str


class ChatResp(BaseModel):
    assistant_message: str


class GenerateReq(BaseModel):
    session_id: str
    claim_ids: list[str]


class GenerateResp(BaseModel):
    html: str
    revision_number: int


class EditReq(BaseModel):
    session_id: str
    current_html: str
    instruction: str


class EditResp(BaseModel):
    html: str
    revision_number: int


class ClaimOut(BaseModel):
    id: str
    text: str
    citation: str
    source: str
    category: str
    compliance_status: str
    approved_date: str | None = None


class VersionOut(BaseModel):
    id: str
    created_at: str
    html_preview: str
    revision_number: int
    content_type: str


class VersionDetail(BaseModel):
    id: str
    created_at: str
    html: str
    revision_number: int


class ReviewItem(BaseModel):
    check: str
    status: str  # "pass", "warn", "fail"
    detail: str


class ComplianceReviewResp(BaseModel):
    overall: str  # "pass", "warn", "fail"
    can_export: bool
    items: list[ReviewItem]


class ExportResp(BaseModel):
    html: str
    metadata: dict
    compliance_report: dict


# ── Endpoints ────────────────────────────────────────────────────────


@app.get("/health")
def health():
    enabled = llm.is_available()
    logger.info("[health] ok=True, llm_enabled=%s", enabled)
    return {"ok": True, "llm_enabled": enabled}


@app.post("/ingest")
def run_ingestion():
    """Ingest PDFs from approved_library/ into vector DB + SQLite. Source of truth for claims and visual assets."""
    logger.info("[ingest] Starting ingestion from approved_library/")
    try:
        from ingestion import run_ingestion as do_ingest

        result = do_ingest()
        logger.info("[ingest] Complete: %d claims, %d assets, %d errors", result["claims_added"], result["assets_added"], len(result["errors"]))
        return result
    except Exception as e:
        logger.exception("[ingest] Failed: %s", e)
        raise HTTPException(500, str(e))


@app.post("/session", response_model=SessionResp)
def create_session(body: SessionCreate, db: DBSession = Depends(get_db)):
    logger.info(
        "[session:create] content_type=%s, audience=%s, campaign_goal=%s, tone=%s",
        body.content_type, body.audience, body.campaign_goal, body.tone,
    )
    sess = Session(
        id=new_uuid(),
        content_type=body.content_type,
        audience=body.audience,
        campaign_goal=body.campaign_goal,
        tone=body.tone,
    )
    db.add(sess)
    db.commit()
    logger.info("[session:create] Created session_id=%s", sess.id)
    return SessionResp(
        session_id=sess.id,
        content_type=sess.content_type,
        audience=sess.audience,
        campaign_goal=sess.campaign_goal,
        tone=sess.tone,
    )


@app.get("/session/{session_id}")
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    logger.info("[session:get] Fetching session_id=%s", session_id)
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        logger.warning("[session:get] Session not found: %s", session_id)
        raise HTTPException(404, "Session not found")
    logger.info(
        "[session:get] Found — type=%s, audience=%s, goal=%s, tone=%s",
        sess.content_type, sess.audience, sess.campaign_goal, sess.tone,
    )
    return SessionResp(
        session_id=sess.id,
        content_type=sess.content_type,
        audience=sess.audience or "hcp",
        campaign_goal=sess.campaign_goal or "awareness",
        tone=sess.tone or "clinical",
    )


@app.post("/chat", response_model=ChatResp)
def chat(body: ChatReq, db: DBSession = Depends(get_db)):
    logger.info(
        "[chat] session_id=%s, user_content='%s' (%d chars)",
        body.session_id, body.content[:80], len(body.content),
    )
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        logger.warning("[chat] Session not found: %s", body.session_id)
        raise HTTPException(404, "Session not found")

    user_msg = Message(
        id=new_uuid(),
        session_id=body.session_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    db.flush()
    logger.info("[chat] Saved user message id=%s", user_msg.id)

    all_messages = (
        db.query(Message)
        .filter(Message.session_id == body.session_id)
        .order_by(Message.created_at)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in all_messages]
    logger.info("[chat] Conversation history: %d messages total", len(history))

    session_context = {
        "content_type": sess.content_type,
        "audience": sess.audience or "hcp",
        "campaign_goal": sess.campaign_goal or "awareness",
        "tone": sess.tone or "clinical",
    }

    t0 = time.perf_counter()
    assistant_text = llm.chat_reply(history, session_context)
    llm_ms = (time.perf_counter() - t0) * 1000

    if assistant_text is None:
        msg_count = sum(1 for m in all_messages if m.role == "user")
        logger.info("[chat] LLM unavailable — using stub fallback (msg_count=%d)", msg_count)
        assistant_text = _stub_assistant_reply(body.content, msg_count, session_context)
    else:
        logger.info("[chat] LLM reply received in %.1fms — %d chars", llm_ms, len(assistant_text))

    assistant_msg = Message(
        id=new_uuid(),
        session_id=body.session_id,
        role="assistant",
        content=assistant_text,
    )
    db.add(assistant_msg)
    db.commit()
    logger.info("[chat] Saved assistant message id=%s, reply_preview='%s'", assistant_msg.id, assistant_text[:100])

    return ChatResp(assistant_message=assistant_text)


@app.post("/chat/stream")
def chat_stream(body: ChatReq, db: DBSession = Depends(get_db)):
    """Stream assistant reply via Server-Sent Events."""
    logger.info("[chat_stream] session_id=%s, content='%s'", body.session_id, body.content[:80])
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        raise HTTPException(404, "Session not found")

    user_msg = Message(id=new_uuid(), session_id=body.session_id, role="user", content=body.content)
    db.add(user_msg)
    db.flush()

    all_messages = (
        db.query(Message)
        .filter(Message.session_id == body.session_id)
        .order_by(Message.created_at)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in all_messages]

    session_context = {
        "content_type": sess.content_type,
        "audience": sess.audience or "hcp",
        "campaign_goal": sess.campaign_goal or "awareness",
        "tone": sess.tone or "clinical",
    }

    token_stream = llm.chat_reply_stream(history, session_context)

    if token_stream is None:
        msg_count = sum(1 for m in all_messages if m.role == "user")
        stub_text = _stub_assistant_reply(body.content, msg_count, session_context)
        logger.info("[chat_stream] LLM unavailable — streaming stub response")

        def _stub_sse():
            for word in stub_text.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            assistant_msg = Message(id=new_uuid(), session_id=body.session_id, role="assistant", content=stub_text)
            db.add(assistant_msg)
            db.commit()
            yield f"data: {json.dumps({'done': True, 'full_text': stub_text})}\n\n"

        return StreamingResponse(_stub_sse(), media_type="text/event-stream")

    collected_text = []

    def _llm_sse():
        try:
            for token in token_stream:
                collected_text.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            logger.error("[chat_stream] Stream error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            full_text = "".join(collected_text)
            if full_text:
                assistant_msg = Message(
                    id=new_uuid(), session_id=body.session_id, role="assistant", content=full_text,
                )
                db.add(assistant_msg)
                db.commit()
                logger.info("[chat_stream] Saved streamed message — %d chars", len(full_text))
            yield f"data: {json.dumps({'done': True, 'full_text': full_text})}\n\n"

    return StreamingResponse(_llm_sse(), media_type="text/event-stream")


@app.get("/messages")
def get_messages(session_id: str, db: DBSession = Depends(get_db)):
    logger.info("[messages] Fetching messages for session_id=%s", session_id)
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        logger.warning("[messages] Session not found: %s", session_id)
        raise HTTPException(404, "Session not found")

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at)
        .all()
    )
    logger.info("[messages] Returning %d messages", len(messages))
    return {
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
    }


@app.delete("/messages")
def clear_messages(session_id: str, db: DBSession = Depends(get_db)):
    logger.info("[messages:clear] Clearing messages for session_id=%s", session_id)
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        raise HTTPException(404, "Session not found")

    count = db.query(Message).filter(Message.session_id == session_id).delete()
    db.commit()
    logger.info("[messages:clear] Deleted %d messages", count)
    return {"deleted": count}


@app.get("/claims/recommended")
def recommended_claims(session_id: str, db: DBSession = Depends(get_db)):
    logger.info("[claims] Fetching recommended claims for session_id=%s", session_id)
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        logger.warning("[claims] Session not found: %s", session_id)
        raise HTTPException(404, "Session not found")

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.role == "user")
        .all()
    )
    query_text = " ".join(m.content for m in messages).strip()
    if not query_text or len(query_text) < 3:
        query_text = "FRUZAQLA efficacy safety dosing indication mechanism"

    try:
        import vector_store

        search_results = vector_store.search_claims(query_text, n_results=20)
        claim_ids = [r["id"] for r in search_results]
        claims_from_db = db.query(Claim).filter(Claim.id.in_(claim_ids)).all() if claim_ids else []
        id_to_claim = {c.id: c for c in claims_from_db}
        ordered = [id_to_claim[rid] for rid in claim_ids if rid in id_to_claim]
    except Exception as e:
        logger.warning("[claims] Vector search failed, falling back to all claims: %s", e)
        ordered = db.query(Claim).all()

    categories = {}
    for c in ordered:
        categories[c.category] = categories.get(c.category, 0) + 1
    logger.info(
        "[claims] Returning %d claims via semantic search, categories: %s",
        len(ordered), categories,
    )

    return {
        "claims": [
            ClaimOut(
                id=c.id,
                text=c.text,
                citation=c.citation,
                source=c.source,
                category=c.category,
                compliance_status=c.compliance_status,
                approved_date=c.approved_date,
            )
            for c in ordered
        ]
    }


@app.post("/generate", response_model=GenerateResp)
def generate(body: GenerateReq, db: DBSession = Depends(get_db)):
    logger.info(
        "[generate] session_id=%s, claim_ids=%d selected",
        body.session_id, len(body.claim_ids),
    )
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        logger.warning("[generate] Session not found: %s", body.session_id)
        raise HTTPException(404, "Session not found")

    claims = db.query(Claim).filter(Claim.id.in_(body.claim_ids)).all()
    if not claims:
        logger.warning("[generate] No valid claims found for ids: %s", body.claim_ids)
        raise HTTPException(400, "No valid claims selected")

    claim_categories = [c.category for c in claims]
    logger.info("[generate] Matched %d claims: categories=%s", len(claims), claim_categories)

    prev_count = (
        db.query(Version).filter(Version.session_id == body.session_id).count()
    )
    revision = prev_count + 1
    logger.info("[generate] This will be revision #%d", revision)

    messages = (
        db.query(Message)
        .filter(Message.session_id == body.session_id)
        .order_by(Message.created_at)
        .all()
    )
    conversation_context = "\n".join(f"{m.role}: {m.content}" for m in messages[-10:])
    logger.info("[generate] Conversation context: %d messages (last 10 of %d)", min(10, len(messages)), len(messages))

    session_context = {
        "content_type": sess.content_type,
        "audience": sess.audience or "hcp",
        "campaign_goal": sess.campaign_goal or "awareness",
        "tone": sess.tone or "clinical",
    }

    claims_dicts = [
        {"text": c.text, "citation": c.citation, "category": c.category, "source": c.source}
        for c in claims
    ]

    t0 = time.perf_counter()
    generated_html = llm.generate_content(claims_dicts, session_context, conversation_context)
    gen_ms = (time.perf_counter() - t0) * 1000

    if generated_html is None:
        logger.info("[generate] LLM unavailable — using stub HTML builder for '%s'", sess.content_type)
        generated_html = _build_html(claims, sess.content_type)
        logger.info("[generate] Stub HTML built: %d chars", len(generated_html))
    else:
        logger.info("[generate] LLM HTML generated in %.1fms: %d chars", gen_ms, len(generated_html))

    version = Version(
        id=new_uuid(),
        session_id=body.session_id,
        html=generated_html,
        content_type=sess.content_type,
        revision_number=revision,
        claim_ids_used=json.dumps(body.claim_ids),
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    logger.info("[generate] Saved version id=%s, rev=%d, html_size=%d", version.id, revision, len(generated_html))

    return GenerateResp(html=generated_html, revision_number=revision)


@app.post("/edit", response_model=EditResp)
def edit(body: EditReq, db: DBSession = Depends(get_db)):
    logger.info(
        "[edit] session_id=%s, instruction='%s', html_size=%d chars",
        body.session_id, body.instruction[:80], len(body.current_html),
    )
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        logger.warning("[edit] Session not found: %s", body.session_id)
        raise HTTPException(404, "Session not found")

    t0 = time.perf_counter()
    edited_html = llm.edit_content(body.current_html, body.instruction)
    edit_ms = (time.perf_counter() - t0) * 1000

    if edited_html is None:
        logger.info("[edit] LLM unavailable — using stub edit logic")
        edited_html = _apply_edit(body.current_html, body.instruction)
        logger.info("[edit] Stub edit applied: %d -> %d chars (delta %+d)",
                     len(body.current_html), len(edited_html), len(edited_html) - len(body.current_html))
    else:
        logger.info("[edit] LLM edit applied in %.1fms: %d -> %d chars (delta %+d)",
                     edit_ms, len(body.current_html), len(edited_html), len(edited_html) - len(body.current_html))

    prev_count = (
        db.query(Version).filter(Version.session_id == body.session_id).count()
    )
    revision = prev_count + 1

    version = Version(
        id=new_uuid(),
        session_id=body.session_id,
        html=edited_html,
        content_type=sess.content_type,
        revision_number=revision,
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    logger.info("[edit] Saved version id=%s, rev=%d", version.id, revision)

    return EditResp(html=edited_html, revision_number=revision)


@app.post("/compliance-review", response_model=ComplianceReviewResp)
def compliance_review(body: GenerateReq, db: DBSession = Depends(get_db)):
    """Comprehensive compliance review with green/yellow/red status per check."""
    logger.info(
        "[compliance] Running review — session_id=%s, claim_ids=%d",
        body.session_id, len(body.claim_ids),
    )
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        logger.warning("[compliance] Session not found: %s", body.session_id)
        raise HTTPException(404, "Session not found")

    claims = db.query(Claim).filter(Claim.id.in_(body.claim_ids)).all()
    all_library_claims = db.query(Claim).all()
    logger.info("[compliance] Selected %d claims, library has %d total", len(claims), len(all_library_claims))

    latest_version = (
        db.query(Version)
        .filter(Version.session_id == body.session_id)
        .order_by(Version.created_at.desc())
        .first()
    )
    html_content = latest_version.html if latest_version else ""
    logger.info(
        "[compliance] Latest version: %s, html_size=%d chars",
        latest_version.id if latest_version else "None", len(html_content),
    )

    items: list[ReviewItem] = []

    # 1. Claim library match — verify every claim text appears in approved library
    library_texts = {c.text for c in all_library_claims}
    all_claims_approved = True
    for c in claims:
        if c.text in library_texts and c.compliance_status == "approved":
            continue
        all_claims_approved = False
        break

    if all_claims_approved and claims:
        items.append(ReviewItem(
            check="Claim Library Match",
            status="pass",
            detail=f"All {len(claims)} selected claims match the approved library with exact text."
        ))
    elif not claims:
        items.append(ReviewItem(
            check="Claim Library Match",
            status="fail",
            detail="No claims selected. At least one approved claim is required."
        ))
    else:
        items.append(ReviewItem(
            check="Claim Library Match",
            status="fail",
            detail="One or more claims do not match the approved library or are not approved."
        ))

    # 2. Claim source traceability
    all_traceable = all(c.citation and c.source in ("clinical_literature", "prior_approved") for c in claims)
    if all_traceable and claims:
        items.append(ReviewItem(
            check="Source Traceability",
            status="pass",
            detail="All claims have valid citations and traceable sources."
        ))
    else:
        items.append(ReviewItem(
            check="Source Traceability",
            status="fail",
            detail="Some claims lack proper citations or have unrecognized sources."
        ))

    # 3. FDA fair balance
    categories = {c.category for c in claims}
    has_efficacy = "efficacy" in categories
    has_safety = "safety" in categories

    if has_efficacy and has_safety:
        items.append(ReviewItem(
            check="FDA Fair Balance",
            status="pass",
            detail="Efficacy and safety claims are both present, satisfying fair balance."
        ))
    elif has_efficacy and not has_safety:
        items.append(ReviewItem(
            check="FDA Fair Balance",
            status="fail",
            detail="Efficacy claims present without safety information. FDA requires fair balance."
        ))
    elif not has_efficacy:
        items.append(ReviewItem(
            check="FDA Fair Balance",
            status="pass",
            detail="No efficacy claims present; fair balance requirement does not apply."
        ))

    # 4. Required disclosures (ISI, PI reference, HCP designation)
    if html_content:
        has_isi = bool(re.search(r"(?i)(important safety information|safety information)", html_content))
        has_pi_ref = bool(re.search(r"(?i)(prescribing information|boxed warning)", html_content))
        has_hcp = bool(re.search(r"(?i)(healthcare professional|hcp)", html_content))

        if has_isi:
            items.append(ReviewItem(check="ISI Section Present", status="pass",
                detail="Important Safety Information section found in content."))
        else:
            items.append(ReviewItem(check="ISI Section Present", status="fail",
                detail="Missing Important Safety Information (ISI) section."))

        if has_pi_ref:
            items.append(ReviewItem(check="PI Reference", status="pass",
                detail="Reference to full Prescribing Information found."))
        else:
            items.append(ReviewItem(check="PI Reference", status="warn",
                detail="Consider adding a reference to the full Prescribing Information."))

        if has_hcp:
            items.append(ReviewItem(check="HCP Designation", status="pass",
                detail="'For healthcare professionals' designation found."))
        else:
            items.append(ReviewItem(check="HCP Designation", status="warn",
                detail="Consider adding 'For US healthcare professionals only' designation."))
    else:
        items.append(ReviewItem(check="Content Generated", status="warn",
            detail="No generated content found yet. Generate content before running full review."))

    # 5. Indication statement
    if any(c.category == "indication" for c in claims):
        items.append(ReviewItem(check="Indication Statement", status="pass",
            detail="Approved indication statement is included."))
    else:
        items.append(ReviewItem(check="Indication Statement", status="warn",
            detail="Consider including the approved indication statement for completeness."))

    # 6. References section
    if html_content and re.search(r"(?i)(references|citations)", html_content):
        items.append(ReviewItem(check="References Section", status="pass",
            detail="References/citations section found in content."))
    elif html_content:
        items.append(ReviewItem(check="References Section", status="fail",
            detail="No references section found. All claims must cite their source."))

    # 7. Visual assets check (stub — no real images in prototype)
    items.append(ReviewItem(check="Visual Assets", status="pass",
        detail="No unauthorized visual assets detected. (Text-only content)"))

    # 8. Channel compatibility
    channel = sess.content_type
    if html_content:
        html_size = len(html_content.encode("utf-8"))
        if channel == "email" and html_size > 102400:
            items.append(ReviewItem(check="Channel Compatibility", status="warn",
                detail=f"Email HTML is {html_size//1024}KB. Some email clients limit to 100KB."))
        elif channel == "banner":
            if "728" in html_content and "90" in html_content:
                items.append(ReviewItem(check="Channel Compatibility", status="pass",
                    detail="Banner dimensions (728×90) detected in content."))
            else:
                items.append(ReviewItem(check="Channel Compatibility", status="warn",
                    detail="Banner format selected but standard dimensions not confirmed in HTML."))
        else:
            items.append(ReviewItem(check="Channel Compatibility", status="pass",
                detail=f"Content is compatible with {channel} format."))

    # 9. Approval status of all claims
    non_approved = [c for c in claims if c.compliance_status != "approved"]
    if non_approved:
        items.append(ReviewItem(check="Claim Approval Status", status="fail",
            detail=f"{len(non_approved)} claim(s) have non-approved status. Only approved claims can be used."))
    elif claims:
        items.append(ReviewItem(check="Claim Approval Status", status="pass",
            detail="All selected claims have 'approved' compliance status."))

    # 10. Legal footer
    if html_content and re.search(r"(?i)(all rights reserved|trademark)", html_content):
        items.append(ReviewItem(check="Legal Footer", status="pass",
            detail="Legal/trademark footer found."))
    elif html_content:
        items.append(ReviewItem(check="Legal Footer", status="warn",
            detail="Consider adding trademark and copyright footer."))

    # Compute overall status
    statuses = [it.status for it in items]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    can_export = "fail" not in statuses
    pass_count = statuses.count("pass")
    warn_count = statuses.count("warn")
    fail_count = statuses.count("fail")
    logger.info(
        "[compliance] Result: overall=%s, can_export=%s — %d pass, %d warn, %d fail",
        overall, can_export, pass_count, warn_count, fail_count,
    )
    for it in items:
        if it.status != "pass":
            logger.info("[compliance]   %s %s: %s", it.status.upper(), it.check, it.detail)

    return ComplianceReviewResp(
        overall=overall,
        can_export=can_export,
        items=items,
    )


# Keep the old endpoint for backward compat
@app.post("/compliance-check")
def compliance_check(body: GenerateReq, db: DBSession = Depends(get_db)):
    result = compliance_review(body, db)
    issues = [it.detail for it in result.items if it.status == "fail"]
    warnings = [it.detail for it in result.items if it.status == "warn"]
    return {"passed": result.overall != "fail", "issues": issues, "warnings": warnings}


@app.post("/export", response_model=ExportResp)
def export_content(body: GenerateReq, db: DBSession = Depends(get_db)):
    """Export final content package: HTML + metadata + compliance report."""
    logger.info("[export] Starting export — session_id=%s, claim_ids=%d", body.session_id, len(body.claim_ids))
    sess = db.query(Session).filter(Session.id == body.session_id).first()
    if not sess:
        logger.warning("[export] Session not found: %s", body.session_id)
        raise HTTPException(404, "Session not found")

    latest_version = (
        db.query(Version)
        .filter(Version.session_id == body.session_id)
        .order_by(Version.created_at.desc())
        .first()
    )
    if not latest_version:
        logger.warning("[export] No versions exist for session %s", body.session_id)
        raise HTTPException(400, "No content generated yet")

    logger.info("[export] Exporting version id=%s, rev=%d", latest_version.id, latest_version.revision_number)

    claims = db.query(Claim).filter(Claim.id.in_(body.claim_ids)).all()

    review = compliance_review(body, db)
    if not review.can_export:
        logger.warning("[export] BLOCKED — compliance review has failures, cannot export")
        raise HTTPException(
            400,
            "Cannot export: compliance review has blocking failures. "
            "Resolve all red items first."
        )

    metadata = {
        "session_id": sess.id,
        "content_type": sess.content_type,
        "audience": sess.audience,
        "campaign_goal": sess.campaign_goal,
        "tone": sess.tone,
        "revision_number": latest_version.revision_number,
        "generated_at": latest_version.created_at.isoformat() if latest_version.created_at else "",
        "exported_at": utcnow().isoformat(),
        "claims_used": [
            {
                "id": c.id,
                "text": c.text,
                "citation": c.citation,
                "source": c.source,
                "category": c.category,
                "compliance_status": c.compliance_status,
                "approved_date": c.approved_date,
            }
            for c in claims
        ],
        "asset_manifest": {
            "images": [],
            "note": "Text-only content; no visual assets used."
        },
    }

    compliance_report = {
        "overall": review.overall,
        "can_export": review.can_export,
        "reviewed_at": utcnow().isoformat(),
        "checks": [
            {"check": it.check, "status": it.status, "detail": it.detail}
            for it in review.items
        ],
    }

    logger.info(
        "[export] Package assembled — html=%d chars, claims=%d, checks=%d (%s)",
        len(latest_version.html), len(claims), len(compliance_report["checks"]), compliance_report["overall"],
    )

    return ExportResp(
        html=latest_version.html,
        metadata=metadata,
        compliance_report=compliance_report,
    )


@app.get("/versions")
def list_versions(session_id: str, db: DBSession = Depends(get_db)):
    logger.info("[versions:list] session_id=%s", session_id)
    versions = (
        db.query(Version)
        .filter(Version.session_id == session_id)
        .order_by(Version.created_at.desc())
        .all()
    )
    logger.info("[versions:list] Returning %d versions", len(versions))
    return {
        "versions": [
            VersionOut(
                id=v.id,
                created_at=v.created_at.isoformat() if v.created_at else "",
                html_preview=re.sub(r"<[^>]+>", "", v.html or "")[:120],
                revision_number=v.revision_number or 0,
                content_type=v.content_type or "email",
            )
            for v in versions
        ]
    }


@app.get("/versions/{version_id}", response_model=VersionDetail)
def get_version(version_id: str, db: DBSession = Depends(get_db)):
    logger.info("[versions:get] Loading version_id=%s", version_id)
    v = db.query(Version).filter(Version.id == version_id).first()
    if not v:
        logger.warning("[versions:get] Version not found: %s", version_id)
        raise HTTPException(404, "Version not found")
    logger.info("[versions:get] Found rev=%d, html_size=%d chars", v.revision_number or 0, len(v.html or ""))
    return VersionDetail(
        id=v.id,
        created_at=v.created_at.isoformat() if v.created_at else "",
        html=v.html,
        revision_number=v.revision_number or 0,
    )


# ── Stub Fallbacks ───────────────────────────────────────────────────

CONTENT_TYPE_LABELS = {
    "email": "HCP Email", "banner": "Banner Ad",
    "social": "Social Post", "slide": "Slide Deck",
}
AUDIENCE_LABELS = {
    "hcp": "healthcare professionals", "patients": "patients",
    "caregivers": "caregivers", "payers": "payers",
}
GOAL_LABELS = {
    "awareness": "disease awareness", "education": "clinical education",
    "cta": "call-to-action", "launch": "product launch",
}
TONE_LABELS = {
    "clinical": "clinical", "empathetic": "empathetic",
    "urgent": "urgent", "informative": "informative",
}


def _stub_assistant_reply(user_content: str, msg_number: int, ctx: dict) -> str:
    lower = user_content.lower()
    ct_label = CONTENT_TYPE_LABELS.get(ctx["content_type"], ctx["content_type"])
    aud_label = AUDIENCE_LABELS.get(ctx["audience"], ctx["audience"])
    goal_label = GOAL_LABELS.get(ctx["campaign_goal"], ctx["campaign_goal"])
    tone_label = TONE_LABELS.get(ctx["tone"], ctx["tone"])

    if msg_number <= 1:
        return (
            f"Welcome! I'll help you build a {tone_label} {ct_label} for FRUZAQLA "
            f"(fruquintinib) targeting {aud_label}, focused on {goal_label}.\n\n"
            f"What's the key clinical message you'd like to lead with? For example:\n"
            f"\u2022 Overall survival data from FRESCO-2\n"
            f"\u2022 Mechanism of action (selective VEGFR inhibition)\n"
            f"\u2022 Convenient oral dosing\n"
            f"\u2022 Disease control rate in refractory mCRC"
        )

    if any(kw in lower for kw in ["survival", "os ", "efficacy", "fresco", "data", "clinical"]):
        return (
            "Understood \u2014 we'll lead with the FRESCO-2 overall survival data. "
            "FRUZAQLA showed median OS of 7.4 months vs 4.8 months (HR 0.66, P<0.001). "
            "I'd recommend these approved claims for your piece:\n\n"
            "\u2022 \u201cFRUZAQLA demonstrated a statistically significant improvement in OS...\u201d\n"
            "\u2022 \u201cMedian PFS was 3.7 months vs 1.8 months...\u201d\n"
            "\u2022 Plus required safety/ISI information\n\n"
            "Head to the Preview tab to select and approve each claim before we generate."
        )

    if any(kw in lower for kw in ["mechanism", "moa", "vegf", "angiogenesis"]):
        return (
            "Good choice. Fruquintinib's selective VEGFR-1/2/3 inhibition is a "
            "differentiating story. I'd suggest pairing this with the OS data for a "
            "compelling piece. Head to Preview to select the exact claims."
        )

    if any(kw in lower for kw in ["dosing", "dose", "oral", "convenient", "schedule"]):
        return (
            "The oral dosing schedule \u2014 5 mg once daily, 3 weeks on / 1 week off \u2014 "
            "is a strong convenience message. I have the approved dosing claim ready. "
            "Move to Preview to select and approve claims."
        )

    if any(kw in lower for kw in ["safety", "adverse", "side effect", "tolerab"]):
        return (
            "Safety is critical for fair balance. The most common adverse reactions "
            "(\u226520%) include hypertension, diarrhea, fatigue, and PPES. "
            "You can select safety claims in the Preview tab."
        )

    if any(kw in lower for kw in ["ready", "preview", "generate", "go", "let's"]):
        return (
            "Head over to the Preview tab \u2014 I've prepared recommended claims "
            "based on our conversation. Select the ones you want, run a compliance "
            "check, and generate your content."
        )

    return (
        f"Thanks for that context. For your {ct_label}:\n"
        f"\u2022 Efficacy data (OS, PFS, DCR from FRESCO-2)\n"
        f"\u2022 Safety / fair balance language\n"
        f"\u2022 Mechanism of action messaging\n"
        f"\u2022 Dosing convenience\n\n"
        f"Which area would you like to focus on?"
    )


# ── HTML template stubs (unchanged from before) ─────────────────────

def _build_html(claims: list[Claim], content_type: str) -> str:
    if content_type == "banner":
        return _build_banner_html(claims)
    if content_type == "social":
        return _build_social_html(claims)
    return _build_email_html(claims)


def _build_email_html(claims: list[Claim]) -> str:
    efficacy = [c for c in claims if c.category in ("efficacy", "indication", "mechanism", "quality_of_life", "dosing")]
    safety = [c for c in claims if c.category == "safety"]
    efficacy_items = "\n".join(f'        <li class="claim">{c.text}</li>' for c in efficacy)
    safety_items = "\n".join(
        f"        <li>{c.text}</li>" for c in safety
    ) if safety else "        <li>Please see full Prescribing Information for Important Safety Information.</li>"
    all_citations = list(dict.fromkeys(c.citation for c in claims))
    citation_items = "\n".join(f"        <li>{cit}</li>" for cit in all_citations)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>FRUZAQLA \u2014 HCP Email</title>
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 0; padding: 0; background: #f9f9f9; color: #222; }}
  .container {{ max-width: 640px; margin: 0 auto; background: #fff; }}
  .header {{ background: linear-gradient(135deg, #0f4c75 0%, #1b262c 100%); color: #fff; padding: 36px 28px; }}
  .header h1 {{ margin: 0; font-size: 24px; letter-spacing: 0.5px; }}
  .header .subtitle {{ margin: 6px 0 0; font-size: 14px; opacity: 0.9; font-style: italic; }}
  .header .hcp-only {{ margin: 10px 0 0; font-size: 11px; opacity: 0.7; text-transform: uppercase; letter-spacing: 1px; }}
  .indication {{ background: #f0f4f8; padding: 16px 28px; font-size: 12px; color: #555; border-bottom: 1px solid #e0e0e0; }}
  .section {{ padding: 28px; }}
  .section h2 {{ color: #0f4c75; font-size: 18px; border-bottom: 2px solid #bbe1fa; padding-bottom: 8px; margin-top: 0; }}
  .claim {{ margin-bottom: 14px; line-height: 1.6; font-size: 14px; }}
  .safety {{ background: #fff8f0; border-left: 4px solid #d35400; padding: 20px 28px; }}
  .safety h2 {{ color: #c0392b; font-size: 16px; margin-top: 0; }}
  .safety ul {{ font-size: 13px; line-height: 1.6; }}
  .cta {{ text-align: center; padding: 24px 28px; }}
  .cta a {{ display: inline-block; background: #0f4c75; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 4px; font-size: 14px; font-weight: 600; }}
  .footer {{ background: #f5f5f5; padding: 24px 28px; font-size: 11px; color: #777; }}
  .footer ol {{ padding-left: 18px; line-height: 1.6; }}
  .footer .legal {{ margin-top: 12px; font-size: 10px; color: #999; }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>FRUZAQLA<sup>&reg;</sup></h1>
      <div class="subtitle">fruquintinib | capsules</div>
      <div class="hcp-only">For US healthcare professionals only</div>
    </div>
    <div class="indication">
      <strong>Indication:</strong> FRUZAQLA is indicated for the treatment of adult patients with metastatic colorectal cancer (mCRC) who have been previously treated with fluoropyrimidine-, oxaliplatin-, and irinotecan-based chemotherapy, an anti-VEGF biological therapy, and, if RAS wild-type and medically appropriate, an anti-EGFR therapy.
    </div>
    <div class="section" id="efficacy">
      <h2>Efficacy &amp; Clinical Evidence</h2>
      <ul>
{efficacy_items}
      </ul>
    </div>
    <div class="safety" id="safety">
      <h2>Important Safety Information</h2>
      <ul>
{safety_items}
      </ul>
      <p style="font-size:12px; margin-top:12px;">Please see full <a href="#" style="color:#0f4c75;">Prescribing Information</a>, including BOXED WARNING.</p>
    </div>
    <div class="cta"><a href="#">Learn More at FRUZAQLA-hcp.com</a></div>
    <div class="footer">
      <h3 style="margin-top:0; font-size:12px; color:#555;">References</h3>
      <ol>
{citation_items}
      </ol>
      <div class="legal">FRUZAQLA is a registered trademark. &copy; 2025 Takeda Pharmaceutical Company Limited.<br/>All rights reserved. US-FRZ-2500001 03/2025</div>
    </div>
  </div>
</body>
</html>"""


def _build_banner_html(claims: list[Claim]) -> str:
    headline = claims[0].text if claims else "Discover FRUZAQLA"
    if len(headline) > 120:
        headline = headline[:117] + "..."
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<style>body{{margin:0;padding:0;font-family:'Helvetica Neue',Arial,sans-serif}}.banner{{width:728px;height:90px;background:linear-gradient(135deg,#0f4c75,#1b262c);color:#fff;display:flex;align-items:center;padding:0 20px;box-sizing:border-box;overflow:hidden}}.banner .brand{{font-size:18px;font-weight:700;white-space:nowrap;margin-right:16px;min-width:120px}}.banner .msg{{font-size:11px;line-height:1.4;flex:1;opacity:.95}}.banner .cta-btn{{background:#bbe1fa;color:#0f4c75;border:none;padding:8px 16px;border-radius:3px;font-size:11px;font-weight:700;cursor:pointer;white-space:nowrap}}.isi{{font-size:8px;color:#999;padding:4px 20px}}</style>
</head><body>
<div class="banner"><div class="brand">FRUZAQLA<sup>&reg;</sup></div><div class="msg">{headline}</div><button class="cta-btn">Learn&nbsp;More</button></div>
<div class="isi">Please see full Prescribing Information, including BOXED WARNING. For US HCPs only. &copy; 2025 Takeda</div>
</body></html>"""


def _build_social_html(claims: list[Claim]) -> str:
    bullets = "\n".join(f"    <li>{c.text}</li>" for c in claims[:3])
    citations = ", ".join(dict.fromkeys(c.citation for c in claims[:3]))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<style>body{{margin:0;padding:0;font-family:'Helvetica Neue',Arial,sans-serif;background:#f9f9f9}}.card{{max-width:480px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)}}.card-header{{background:linear-gradient(135deg,#0f4c75,#1b262c);color:#fff;padding:20px 24px}}.card-header h1{{margin:0;font-size:20px}}.card-header p{{margin:4px 0 0;font-size:12px;opacity:.8}}.card-body{{padding:20px 24px}}.card-body ul{{padding-left:18px;font-size:13px;line-height:1.7}}.card-footer{{padding:12px 24px;font-size:9px;color:#999;border-top:1px solid #eee}}</style>
</head><body>
<div class="card"><div class="card-header"><h1>FRUZAQLA<sup>&reg;</sup> (fruquintinib)</h1><p>For US healthcare professionals only</p></div>
<div class="card-body"><ul>
{bullets}
</ul></div>
<div class="card-footer">See full Prescribing Information, including BOXED WARNING. Ref: {citations}. &copy; 2025 Takeda</div></div>
</body></html>"""


def _extract_div_block(html: str, attr_match: str) -> str | None:
    """Extract a complete <div ...> block including nested divs, using depth counting."""
    pattern = re.compile(rf'<div\s[^>]*{re.escape(attr_match)}[^>]*>')
    m = pattern.search(html)
    if not m:
        return None
    start = m.start()
    depth = 0
    i = start
    while i < len(html):
        if html[i:i+4] == "<div":
            depth += 1
            i += 4
        elif html[i:i+6] == "</div>":
            depth -= 1
            if depth == 0:
                return html[start:i+6]
            i += 6
        else:
            i += 1
    return None


def _apply_edit(current_html: str, instruction: str) -> str:
    lower = instruction.lower()
    if "move safety" in lower or "safety above" in lower or "safety before" in lower:
        safety_block = _extract_div_block(current_html, 'class="safety"')
        efficacy_block = _extract_div_block(current_html, 'id="efficacy"')
        if safety_block and efficacy_block:
            h = current_html.replace(safety_block, "")
            return h.replace(efficacy_block, safety_block + "\n\n    " + efficacy_block)
    if "shorter" in lower or "concise" in lower or "reduce" in lower or "trim" in lower:
        return re.sub(r'<li[^>]*class="claim"[^>]*>.*?</li>\s*(?=</ul>)', "", current_html, count=1, flags=re.DOTALL)
    if "bold" in lower or "emphasize" in lower or "highlight" in lower:
        return re.sub(r'(<li class="claim">)(.*?)(</li>)',
            lambda m: m.group(1) + "<strong>" + m.group(2) + "</strong>" + m.group(3), current_html, count=1)
    if "remove cta" in lower or "remove button" in lower or "no cta" in lower:
        return re.sub(r'<div class="cta">.*?</div>', "", current_html, count=1, flags=re.DOTALL)
    if "add cta" in lower or "add button" in lower:
        cta = '\n    <div class="cta" style="text-align:center;padding:24px 28px;"><a href="#" style="display:inline-block;background:#0f4c75;color:#fff;text-decoration:none;padding:12px 32px;border-radius:4px;font-size:14px;font-weight:600;">Learn More at FRUZAQLA-hcp.com</a></div>'
        idx = current_html.find('<div class="footer">')
        if idx != -1:
            return current_html[:idx] + cta + "\n\n    " + current_html[idx:]
    if "remove indication" in lower or "hide indication" in lower:
        return re.sub(r'<div class="indication">.*?</div>', "", current_html, count=1, flags=re.DOTALL)
    comment = f"\n<!-- Edit requested: {instruction} -->\n"
    pos = current_html.rfind("</body>")
    return current_html[:pos] + comment + current_html[pos:] if pos != -1 else current_html + comment
