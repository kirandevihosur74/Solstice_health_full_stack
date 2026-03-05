"""
Ingest PDFs from approved_library/ as source of truth for prior approved claims and visual assets.
Populates Chroma vector DB + SQLite for semantic search and compliance.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

APPROVED_LIBRARY = Path(__file__).parent.parent / "approved_library"
PRESCRIBING_INFO_PATTERN = "*prescribing*"
STYLE_GUIDE_PATTERN = "*style*guide*"


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    text_parts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text()
        if t:
            text_parts.append(f"[Page {i + 1}]\n{t}")
    return "\n\n".join(text_parts)


def extract_claims_via_llm(pdf_text: str, source_name: str) -> list[dict]:
    """Use Claude to extract structured claims from prescribing info text."""
    import llm

    if not llm.is_available():
        logger.warning("LLM unavailable — cannot extract claims from PDF. Add ANTHROPIC_API_KEY.")
        return []

    client = llm.get_client()
    if not client:
        return []

    prompt = f"""Extract prior approved pharmaceutical claims from this FDA prescribing information text.
Source document: {source_name}

For each discrete claim (efficacy, safety, indication, dosing, mechanism, quality_of_life), output a JSON object with:
- text: exact claim text as it appears (do not paraphrase)
- citation: source reference (e.g., "FRUZAQLA Prescribing Information, Section X")
- category: one of efficacy, safety, indication, dosing, mechanism, quality_of_life
- approved_date: if mentioned, else null

Output a JSON array of objects. No other text. Example:
[{{"text": "...", "citation": "...", "category": "efficacy", "approved_date": "2023-11-08"}}]

TEXT TO ANALYZE:
{pdf_text[:12000]}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        claims = json.loads(raw)
        for c in claims:
            c["source"] = "prior_approved"
            c["compliance_status"] = "approved"
        return claims
    except Exception as e:
        logger.error("LLM claim extraction failed: %s", e)
        return []


def extract_visual_assets_via_llm(pdf_text: str, source_name: str) -> list[dict]:
    """Use Claude to extract visual asset guidelines from style guide text."""
    import llm

    if not llm.is_available():
        logger.warning("LLM unavailable — cannot extract visual assets from PDF.")
        return []

    client = llm.get_client()
    if not client:
        return []

    prompt = f"""Extract visual asset and brand guidelines from this style guide text.
Source document: {source_name}

For each guideline (logo usage, approved images, colors, typography, icon usage), output a JSON object with:
- description: the guideline or asset description
- asset_type: one of logo, image, icon, color, guideline
- page_ref: page number if known
- metadata_json: optional JSON string with colors, dimensions, usage_rules (e.g. {{"primary_color": "#0f4c75"}})

Output a JSON array of objects. No other text.

TEXT TO ANALYZE:
{pdf_text[:8000]}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        assets = json.loads(raw)
        for a in assets:
            a["source_pdf"] = source_name
        return assets
    except Exception as e:
        logger.error("LLM visual asset extraction failed: %s", e)
        return []


def run_ingestion() -> dict:
    """
    Ingest all PDFs from approved_library/.
    Returns {claims_added, assets_added, errors}.
    """
    import uuid

    from database import SessionLocal, Claim, VisualAsset, init_db
    import vector_store

    init_db()
    claims_added = 0
    assets_added = 0
    errors = []

    if not APPROVED_LIBRARY.exists():
        logger.warning("approved_library folder not found at %s", APPROVED_LIBRARY)
        return {"claims_added": 0, "assets_added": 0, "errors": ["approved_library folder not found"]}

    pdfs = list(APPROVED_LIBRARY.glob("*.pdf"))
    if not pdfs:
        logger.warning("No PDFs found in %s", APPROVED_LIBRARY)
        return {"claims_added": 0, "assets_added": 0, "errors": ["No PDFs in approved_library"]}

    db = SessionLocal()

    try:
        db.query(Claim).delete()
        db.query(VisualAsset).delete()
        db.commit()
        vector_store.clear_claims()
        vector_store.clear_visual_assets()
        logger.info("Cleared existing claims and visual assets")

        all_claims_for_vector = []
        all_assets_for_vector = []

        for pdf_path in pdfs:
            name = pdf_path.name.lower()
            source_name = pdf_path.stem

            try:
                text = extract_text_from_pdf(pdf_path)
                if not text or len(text) < 100:
                    errors.append(f"{source_name}: insufficient text extracted")
                    continue

                if "prescribing" in name or "prescribing-information" in name or "prescribing_information" in name:
                    raw_claims = extract_claims_via_llm(text, source_name)
                    for c in raw_claims:
                        cid = str(uuid.uuid4())
                        c["id"] = cid
                        claim = Claim(
                            id=cid,
                            text=c["text"],
                            citation=c.get("citation", source_name),
                            source="prior_approved",
                            category=c.get("category", "efficacy"),
                            compliance_status="approved",
                            approved_date=c.get("approved_date"),
                        )
                        db.add(claim)
                        all_claims_for_vector.append(
                            {
                                "id": cid,
                                "text": c["text"],
                                "citation": c.get("citation", source_name),
                                "source": "prior_approved",
                                "category": c.get("category", "efficacy"),
                                "compliance_status": "approved",
                                "approved_date": c.get("approved_date"),
                            }
                        )
                        claims_added += 1
                    db.commit()

                if "style" in name or "style-guide" in name or "styleguide" in name:
                    raw_assets = extract_visual_assets_via_llm(text, source_name)
                    for a in raw_assets:
                        aid = str(uuid.uuid4())
                        asset = VisualAsset(
                            id=aid,
                            asset_type=a.get("asset_type", "guideline"),
                            description=a.get("description", ""),
                            source_pdf=source_name,
                            page_ref=a.get("page_ref"),
                            metadata_json=a.get("metadata_json"),
                        )
                        db.add(asset)
                        all_assets_for_vector.append(
                            {
                                "id": aid,
                                "description": a.get("description", ""),
                                "asset_type": a.get("asset_type", "guideline"),
                                "source_pdf": source_name,
                                "page_ref": a.get("page_ref"),
                                "metadata_json": a.get("metadata_json"),
                            }
                        )
                        assets_added += 1
                    db.commit()

            except Exception as e:
                errors.append(f"{source_name}: {str(e)}")
                logger.exception("Ingestion failed for %s", pdf_path)

        if all_claims_for_vector:
            vector_store.add_claims(all_claims_for_vector)
        if all_assets_for_vector:
            vector_store.add_visual_assets(all_assets_for_vector)

    finally:
        db.close()

    return {
        "claims_added": claims_added,
        "assets_added": assets_added,
        "errors": errors,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_ingestion()
    print(json.dumps(result, indent=2))
