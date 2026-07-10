"""Regression (F2): embedding resolution must return the cache representation.

The embedding service returns float64 vectors; the pgvector cache stores and
returns float4. A first run that returned the service-fresh vector and a later
run that returned the cache-read vector therefore differed at ~1e-9 — enough to
change a Semantic Reproduction Tree hash so the first snapshot never
deduplicated against later, identical ones. Both the single-text path
(``embed_text``) and the batch path (``embed_texts``) now write, then read the
stored vector back, so every path returns the float4 cache representation.
"""

from plan_manager.scoring import embedding, embedding_batch


def test_embed_text_returns_read_back_cache_vector(monkeypatch) -> None:
    service_fresh = [0.123456789012345]  # float64 from the service
    cache_repr = [0.12345679]            # float4 as re-read from pgvector
    store: dict[str, list[float]] = {}
    get_calls = {"n": 0}

    def fake_get(conn, text):
        get_calls["n"] += 1
        return store.get("v")

    def fake_fetch(base_url, text, timeout=60.0):
        return list(service_fresh)

    def fake_store(conn, text, vector):
        # The cache truncates the stored vector to its float4 representation.
        store["v"] = list(cache_repr)

    monkeypatch.setattr(embedding, "get_cached_vector", fake_get)
    monkeypatch.setattr(embedding, "fetch_vector", fake_fetch)
    monkeypatch.setattr(embedding, "store_vector", fake_store)

    result = embedding.embed_text(object(), "https://embed.example:8001", "text")

    # The returned vector is the read-back cache representation, not the
    # service-fresh vector, and the read-back is a second cache probe.
    assert result == cache_repr
    assert result != service_fresh
    assert get_calls["n"] == 2


def test_embed_text_falls_back_to_fetched_when_reread_missing(monkeypatch) -> None:
    service_fresh = [0.9, 0.1]

    monkeypatch.setattr(embedding, "get_cached_vector", lambda conn, text: None)
    monkeypatch.setattr(
        embedding, "fetch_vector", lambda base_url, text, timeout=60.0: list(service_fresh)
    )
    monkeypatch.setattr(embedding, "store_vector", lambda conn, text, vector: None)

    # Read-back still misses (store is a no-op), so the fetched vector is used.
    result = embedding.embed_text(object(), "https://embed.example:8001", "text")
    assert result == service_fresh


def test_embed_texts_batch_returns_read_back_cache_vectors(monkeypatch) -> None:
    service_fresh = {"t": [0.111111111]}
    cache_repr = {"t": [0.11111111]}
    state = {"stored": False}

    def fake_get(conn, texts):
        return dict(cache_repr) if state["stored"] else {}

    def fake_fetch(base_url, texts, timeout=60.0):
        return [list(service_fresh[t]) for t in texts]

    def fake_store(conn, mapping):
        state["stored"] = True

    monkeypatch.setattr(embedding_batch, "get_cached_vectors", fake_get)
    monkeypatch.setattr(embedding_batch, "fetch_vectors", fake_fetch)
    monkeypatch.setattr(embedding_batch, "store_vectors", fake_store)

    out = embedding_batch.embed_texts(object(), "https://embed.example:8001", ["t"])

    assert out["t"] == cache_repr["t"]
    assert out["t"] != service_fresh["t"]


def test_embed_texts_batch_falls_back_to_fetched_when_reread_missing(monkeypatch) -> None:
    service_fresh = {"t": [0.5, 0.25]}

    monkeypatch.setattr(embedding_batch, "get_cached_vectors", lambda conn, texts: {})
    monkeypatch.setattr(
        embedding_batch,
        "fetch_vectors",
        lambda base_url, texts, timeout=60.0: [list(service_fresh[t]) for t in texts],
    )
    monkeypatch.setattr(embedding_batch, "store_vectors", lambda conn, mapping: None)

    out = embedding_batch.embed_texts(object(), "https://embed.example:8001", ["t"])
    assert out["t"] == service_fresh["t"]
