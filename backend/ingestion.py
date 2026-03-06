"""
Ingest PDFs from approved_library/ as source of truth for prior approved claims and visual assets.
Populates SQLite for compliance and keyword-based recommendations. No embeddings.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

APPROVED_LIBRARY = Path(__file__).parent.parent / "approved_library"
ASSETS_DIR = APPROVED_LIBRARY / "assets"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
PRESCRIBING_INFO_PATTERN = "*prescribing*"
STYLE_GUIDE_PATTERN = "*style*guide*"


def _slug(filename: str) -> str:
    """Create asset_id from filename: lowercase, alphanumeric + hyphens."""
    base = Path(filename).stem
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug or "asset"


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_approved_assets() -> dict:
    """
    Scan approved_library/assets/ and upsert into approved_assets table.
    Returns {ingested, updated, errors}.
    """
    from database import SessionLocal, ApprovedAsset, init_db

    init_db()
    ingested = 0
    updated = 0
    errors = []

    if not ASSETS_DIR.exists():
        logger.warning("Assets directory not found at %s", ASSETS_DIR)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        return {"ingested": 0, "updated": 0, "errors": ["Created empty assets dir"]}

    db = SessionLocal()
    try:
        for fpath in ASSETS_DIR.iterdir():
            if not fpath.is_file() or fpath.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            try:
                sha = _compute_sha256(fpath)
                filename = fpath.name
                asset_id = _slug(filename)
                source_doc = "STYLE_GUIDE" if "style" in filename.lower() else "ASSETS"
                tags = json.dumps(["hero"] if "hero" in filename.lower() else ["logo"] if "logo" in filename.lower() else [])

                existing = db.query(ApprovedAsset).filter(ApprovedAsset.asset_id == asset_id).first()
                if existing:
                    existing.filename = filename
                    existing.sha256 = sha
                    existing.source_doc = source_doc
                    existing.tags = tags
                    updated += 1
                    logger.info("[assets] Updated %s (sha=%s)", asset_id, sha[:12])
                else:
                    db.add(ApprovedAsset(
                        asset_id=asset_id,
                        filename=filename,
                        sha256=sha,
                        source_doc=source_doc,
                        source_page=None,
                        tags=tags,
                    ))
                    ingested += 1
                    logger.info("[assets] Ingested %s -> %s", filename, asset_id)
            except Exception as e:
                errors.append(f"{fpath.name}: {e}")
                logger.exception("Asset ingestion failed for %s", fpath)
        db.commit()
    finally:
        db.close()

    return {"ingested": ingested, "updated": updated, "errors": errors}


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

    client = llm.get_client()

    prompt = f"""Extract prior approved pharmaceutical claims from this FDA prescribing information text.
Source document: {source_name}

IMPORTANT: Include efficacy claims from:
- Section 14.1 (Clinical Studies — Metastatic Colorectal Cancer): OS, PFS, hazard ratios, p-values from FRESCO-2 and FRESCO trials
- Table 7 (Efficacy Results): median OS months, median PFS, HR, p-values, DCR, ORR

For each discrete claim (efficacy, safety, indication, dosing, mechanism, quality_of_life), output a JSON object with:
- text: exact claim text as it appears (do not paraphrase)
- citation: source reference (e.g., "FRUZAQLA Prescribing Information, Section 14.1" or "Table 7")
- category: one of efficacy, safety, indication, dosing, mechanism, quality_of_life
- approved_date: if mentioned, else null

Output a JSON array of objects. No other text. Example:
[{{"text": "FRUZAQLA + BSC improved OS vs placebo + BSC (median 7.4 vs 4.8 months; HR 0.66, P<0.001).", "citation": "FRUZAQLA Prescribing Information, Section 14.1", "category": "efficacy", "approved_date": null}}]

TEXT TO ANALYZE:
{pdf_text[:40000]}
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

    client = llm.get_client()

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
        logger.info("Cleared existing claims and visual assets")

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
                        verbatim = c["text"].strip()
                        text_hash = hashlib.sha256(verbatim.encode("utf-8")).hexdigest()
                        claim_id_slug = f"cl-{text_hash[:12]}"
                        cid = str(uuid.uuid4())
                        c["id"] = cid
                        claim = Claim(
                            id=cid,
                            claim_id=claim_id_slug,
                            text=verbatim,
                            verbatim_text=verbatim,
                            text_sha256=text_hash,
                            citation=c.get("citation", source_name),
                            source="prior_approved",
                            source_doc=source_name,
                            category=c.get("category", "efficacy"),
                            compliance_status="approved",
                            approved_date=c.get("approved_date"),
                        )
                        db.add(claim)
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
                        assets_added += 1
                    db.commit()

            except Exception as e:
                errors.append(f"{source_name}: {str(e)}")
                logger.exception("Ingestion failed for %s", pdf_path)

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
