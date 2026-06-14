from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from bs4 import BeautifulSoup

from api.app.core.config import Settings

ROOT = Path(__file__).resolve().parents[4]
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    kind: str
    location: str
    publisher: str
    title: str
    licence: str


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    chunk_text: str
    source_url: str
    publisher: str
    title: str
    section: str
    licence: str
    retrieval_date: str
    source_hash: str
    corpus_version: str


def read_sources(path: Path) -> list[Source]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Source(**item) for item in document["sources"]]


def fetch_source(source: Source, client: httpx.Client) -> tuple[str, str]:
    if source.kind == "file":
        path = ROOT / source.location
        return path.read_text(encoding="utf-8"), path.as_uri()
    if source.kind != "url":
        raise ValueError(f"unsupported source kind: {source.kind}")
    response = client.get(source.location, follow_redirects=True)
    response.raise_for_status()
    return response.text, str(response.url)


def html_to_markdown_sections(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    main = soup.find("main") or soup.find("article") or soup.body or soup
    lines: list[str] = []
    for element in main.find_all(["h1", "h2", "h3", "p", "li"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"}:
            lines.append(f"{'#' * int(element.name[1])} {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def split_sections(content: str, default_title: str) -> Iterator[tuple[str, str]]:
    heading = default_title
    body: list[str] = []
    for line in content.splitlines():
        match = HEADING.match(line)
        if match:
            if body and " ".join(body).strip():
                yield heading, "\n".join(body).strip()
            heading = match.group(2).strip()
            body = []
        else:
            body.append(line)
    if body and " ".join(body).strip():
        yield heading, "\n".join(body).strip()


def window_text(text: str, *, target: int = 1_500, overlap: int = 200) -> Iterator[str]:
    text = " ".join(text.split())
    if not text:
        return
    start = 0
    while start < len(text):
        end = min(start + target, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + target // 2, end)
            if boundary > start:
                end = boundary
        yield text[start:end].strip()
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)


def chunk_source(
    source: Source,
    content: str,
    source_url: str,
    corpus_version: str,
    retrieval_date: str,
) -> list[Chunk]:
    if source.kind == "url":
        content = html_to_markdown_sections(content)
    source_hash = hashlib.sha256(content.encode()).hexdigest()
    chunks: list[Chunk] = []
    for section, text in split_sections(content, source.title):
        for window in window_text(text):
            identifier = hashlib.sha256(f"{source_hash}\0{section}\0{window}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    id=identifier,
                    chunk_text=window,
                    source_url=source_url,
                    publisher=source.publisher,
                    title=source.title,
                    section=section,
                    licence=source.licence,
                    retrieval_date=retrieval_date,
                    source_hash=source_hash,
                    corpus_version=corpus_version,
                )
            )
    return chunks


def batches(values: list[Chunk], size: int = 96) -> Iterable[list[Chunk]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def ensure_index(settings: Settings) -> Any:
    from pinecone import IndexEmbed, Pinecone

    client = Pinecone(api_key=settings.pinecone_api_key)
    names = {
        item["name"] if isinstance(item, dict) else item.name for item in client.list_indexes()
    }
    if settings.pinecone_index not in names:
        client.create_index_for_model(
            name=settings.pinecone_index,
            cloud="aws",
            region="us-east-1",
            embed=IndexEmbed(
                model=settings.pinecone_embed_model,
                field_map={"text": "chunk_text"},
            ),
        )
    return client.Index(settings.pinecone_index)


def atomic_promote_env(path: Path, namespace: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"PINECONE_NAMESPACE={namespace}"
    updated = False
    output: list[str] = []
    for line in lines:
        if line.startswith("PINECONE_NAMESPACE="):
            output.append(replacement)
            updated = True
        else:
            output.append(line)
    if not updated:
        output.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write("\n".join(output) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_namespace(
    *,
    settings: Settings,
    sources_path: Path,
    corpus_version: str,
    manifest_path: Path,
) -> dict[str, Any]:
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required")
    retrieval_date = date.today().isoformat()
    all_chunks: list[Chunk] = []
    with httpx.Client(timeout=30, headers={"User-Agent": "lpe-knowledge-indexer/1.0"}) as client:
        for source in read_sources(sources_path):
            content, final_url = fetch_source(source, client)
            all_chunks.extend(
                chunk_source(source, content, final_url, corpus_version, retrieval_date)
            )
    index = ensure_index(settings)
    for batch in batches(all_chunks):
        records = [{"_id": chunk.id, **asdict(chunk)} for chunk in batch]
        for record in records:
            record.pop("id", None)
        index.upsert_records(corpus_version, records)
    manifest = {
        "corpus_version": corpus_version,
        "created_at": datetime.now(UTC).isoformat(),
        "index": settings.pinecone_index,
        "namespace": corpus_version,
        "embedding_model": settings.pinecone_embed_model,
        "rerank_model": settings.pinecone_rerank_model,
        "chunk_count": len(all_chunks),
        "chunk_ids_hash": hashlib.sha256(
            "\n".join(sorted(chunk.id for chunk in all_chunks)).encode()
        ).hexdigest(),
        "promoted": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a versioned Pinecone knowledge namespace")
    parser.add_argument("--sources", type=Path, default=ROOT / "knowledge/sources.yaml")
    parser.add_argument("--version", required=True)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--eval-report", type=Path)
    args = parser.parse_args()
    settings = Settings()
    manifest_path = ROOT / "knowledge/manifests" / f"{args.version}.json"
    manifest = build_namespace(
        settings=settings,
        sources_path=args.sources,
        corpus_version=args.version,
        manifest_path=manifest_path,
    )
    if args.promote:
        eval_path = args.eval_report or ROOT / "evals/results" / f"{args.version}.json"
        if not eval_path.is_file():
            raise RuntimeError(f"promotion requires an evaluation report: {eval_path}")
        evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
        if evaluation.get("release_passed") is not True:
            raise RuntimeError("promotion requires a passing complete evaluation report")
        atomic_promote_env(args.env_file, args.version)
        manifest["promoted"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
