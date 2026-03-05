"""
Vector store for approved claims and visual assets.
Uses ChromaDB with sentence-transformers for embeddings.
Source of truth: approved_library/ PDFs (FRUZAQLA Style Guide, fruzaqla-prescribing-information).
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHROMA_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_CLAIMS = "claims"
COLLECTION_VISUAL_ASSETS = "visual_assets"

_client = None
_claims_collection = None
_assets_collection = None


def _get_client():
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings

        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH), settings=Settings(anonymized_telemetry=False))
        logger.info("ChromaDB client initialized at %s", CHROMA_PATH)
    return _client


def _get_embedding_function():
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode
    except Exception as e:
        logger.warning("sentence-transformers not available, using default: %s", e)
        return None


def get_claims_collection():
    global _claims_collection
    if _claims_collection is None:
        client = _get_client()
        emb_fn = _get_embedding_function()
        if emb_fn:
            from chromadb.utils import embedding_functions

            ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
            _claims_collection = client.get_or_create_collection(
                name=COLLECTION_CLAIMS,
                embedding_function=ef,
                metadata={"description": "Prior approved claims from prescribing info and style guide"},
            )
        else:
            _claims_collection = client.get_or_create_collection(name=COLLECTION_CLAIMS)
        logger.info("Claims collection ready")
    return _claims_collection


def get_assets_collection():
    global _assets_collection
    if _assets_collection is None:
        client = _get_client()
        emb_fn = _get_embedding_function()
        if emb_fn:
            from chromadb.utils import embedding_functions

            ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
            _assets_collection = client.get_or_create_collection(
                name=COLLECTION_VISUAL_ASSETS,
                embedding_function=ef,
                metadata={"description": "Visual assets and brand guidelines from style guide"},
            )
        else:
            _assets_collection = client.get_or_create_collection(name=COLLECTION_VISUAL_ASSETS)
        logger.info("Visual assets collection ready")
    return _assets_collection


def add_claims(claims: list[dict]) -> None:
    """Add claims to vector store. Each claim: {id, text, citation, source, category, compliance_status, approved_date}."""
    if not claims:
        return
    coll = get_claims_collection()
    ids = [c["id"] for c in claims]
    documents = [c["text"] for c in claims]
    metadatas = [
        {
            "citation": c.get("citation", ""),
            "source": c.get("source", "prior_approved"),
            "category": c.get("category", "efficacy"),
            "compliance_status": c.get("compliance_status", "approved"),
            "approved_date": c.get("approved_date", "") or "",
        }
        for c in claims
    ]
    coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Added %d claims to vector store", len(claims))


def add_visual_assets(assets: list[dict]) -> None:
    """Add visual assets to vector store. Each asset: {id, description, asset_type, source_pdf, page_ref, metadata_json}."""
    if not assets:
        return
    coll = get_assets_collection()
    ids = [a["id"] for a in assets]
    documents = [a["description"] for a in assets]
    metadatas = [
        {
            "asset_type": a.get("asset_type", "guideline"),
            "source_pdf": a.get("source_pdf", ""),
            "page_ref": a.get("page_ref", "") or "",
            "metadata_json": a.get("metadata_json", "") or "",
        }
        for a in assets
    ]
    coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Added %d visual assets to vector store", len(assets))


def search_claims(query: str, n_results: int = 20) -> list[dict]:
    """Semantic search for claims. Returns list of {id, text, citation, source, category, compliance_status, approved_date}."""
    coll = get_claims_collection()
    count = coll.count()
    if count == 0:
        return []
    results = coll.query(query_texts=[query], n_results=min(n_results, count))
    if not results or not results["ids"] or not results["ids"][0]:
        return []

    out = []
    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i] if results.get("metadatas") else {}
        doc = results["documents"][0][i] if results.get("documents") else ""
        out.append(
            {
                "id": doc_id,
                "text": doc,
                "citation": meta.get("citation", ""),
                "source": meta.get("source", "prior_approved"),
                "category": meta.get("category", "efficacy"),
                "compliance_status": meta.get("compliance_status", "approved"),
                "approved_date": meta.get("approved_date") or None,
            }
        )
    return out


def search_visual_assets(query: str, n_results: int = 10) -> list[dict]:
    """Semantic search for visual assets. Returns list of {id, description, asset_type, source_pdf, page_ref, metadata_json}."""
    coll = get_assets_collection()
    count = coll.count()
    if count == 0:
        return []
    results = coll.query(query_texts=[query], n_results=min(n_results, count))
    if not results or not results["ids"] or not results["ids"][0]:
        return []

    out = []
    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i] if results.get("metadatas") else {}
        doc = results["documents"][0][i] if results.get("documents") else ""
        out.append(
            {
                "id": doc_id,
                "description": doc,
                "asset_type": meta.get("asset_type", "guideline"),
                "source_pdf": meta.get("source_pdf", ""),
                "page_ref": meta.get("page_ref", "") or None,
                "metadata_json": meta.get("metadata_json", "") or None,
            }
        )
    return out


def clear_claims() -> None:
    """Clear all claims from vector store (for re-ingestion)."""
    client = _get_client()
    try:
        client.delete_collection(COLLECTION_CLAIMS)
        logger.info("Cleared claims collection")
    except Exception as e:
        logger.warning("Could not clear claims: %s", e)


def clear_visual_assets() -> None:
    """Clear all visual assets from vector store (for re-ingestion)."""
    client = _get_client()
    try:
        client.delete_collection(COLLECTION_VISUAL_ASSETS)
        logger.info("Cleared visual assets collection")
    except Exception as e:
        logger.warning("Could not clear visual assets: %s", e)
