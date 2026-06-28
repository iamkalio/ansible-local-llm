#!/usr/bin/env python3
"""Ingest .md/.txt documents into Qdrant, embedding through LiteLLM.

Reads every file under --docs-dir, splits it into overlapping
chunks, embeds each chunk through the LiteLLM gateway (OpenAI-compatible
/v1/embeddings), and upserts the vectors into a Qdrant collection.

Idempotent by construction: point IDs are deterministic (UUIDv5 of file path
+ chunk index), so re-running over the same documents overwrites the same
points instead of duplicating them.

If LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set, the run is traced in
Langfuse (one trace per run, one span per file). Without keys it runs fine
with tracing disabled. (see ingest.env).

"""

import argparse
import hashlib
import os
import sys
import uuid
from pathlib import Path

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

LITELLM_URL = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "local-embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "ask_my_docs")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "120"))
EMBED_BATCH_SIZE = 16

# Namespace for deterministic point IDs — never change this, or re-ingestion
# will duplicate existing points instead of overwriting them.
ID_NAMESPACE = uuid.UUID("9a1c3f60-5a7e-4b9d-8a2f-1c4d5e6f7a8b")


def get_langfuse():
    """Return a Langfuse client if keys are configured, else None."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    except Exception as exc:  # tracing must never break ingestion
        print(f"warning: Langfuse disabled ({exc})", file=sys.stderr)
        return None


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of ~size chars, preferring paragraph breaks."""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Try to break on a paragraph, then a sentence, then a space.
            for sep in ("\n\n", ". ", " "):
                cut = text.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts through LiteLLM's OpenAI-compatible endpoint."""
    resp = requests.post(
        f"{LITELLM_URL}/v1/embeddings",
        headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
        json={"model": EMBED_MODEL, "input": texts},
        timeout=300,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"created collection '{COLLECTION}' (dim={vector_size})")


def ingest_file(client: QdrantClient, path: Path, rel_path: str) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        return 0
    doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    points = []
    for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
        vectors = embed(batch)
        ensure_collection(client, len(vectors[0]))
        for offset, (chunk, vector) in enumerate(zip(batch, vectors)):
            idx = batch_start + offset
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(ID_NAMESPACE, f"{rel_path}:{idx}")),
                    vector=vector,
                    payload={
                        "source": rel_path,
                        "chunk_index": idx,
                        "doc_hash": doc_hash,
                        "text": chunk,
                    },
                )
            )
    client.upsert(collection_name=COLLECTION, points=points, wait=True)
    return len(points)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-dir", required=True, help="Directory of .md/.txt files")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir).expanduser().resolve()
    files = sorted(p for p in docs_dir.rglob("*") if p.suffix.lower() in (".md", ".txt"))
    if not files:
        print(f"no .md/.txt files found under {docs_dir}", file=sys.stderr)
        return 1

    client = QdrantClient(url=QDRANT_URL)
    langfuse = get_langfuse()
    trace = langfuse.trace(name="ingest", metadata={"files": len(files)}) if langfuse else None

    total = 0
    for path in files:
        rel_path = str(path.relative_to(docs_dir))
        span = trace.span(name="ingest-file", input={"file": rel_path}) if trace else None
        count = ingest_file(client, path, rel_path)
        total += count
        if span:
            span.end(output={"chunks": count})
        print(f"  {rel_path}: {count} chunks")

    if langfuse:
        langfuse.flush()

    print(f"upserted {total} chunks from {len(files)} files into '{COLLECTION}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
