from api.app.ai.retrieval.ingest import Source, chunk_source, window_text


def test_window_text_has_bounded_overlap() -> None:
    text = " ".join(f"word-{index}" for index in range(500))
    chunks = list(window_text(text, target=300, overlap=40))
    assert len(chunks) > 2
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_chunk_ids_are_deterministic() -> None:
    source = Source("source", "file", "x.md", "Publisher", "Title", "OGL")
    content = "# Heading\n\nThis is stable source content."
    first = chunk_source(source, content, "file:///x.md", "v1", "2026-06-13")
    second = chunk_source(source, content, "file:///x.md", "v1", "2026-06-13")
    assert first == second
    assert len(first[0].id) == 64
