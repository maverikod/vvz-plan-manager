import pytest

from plan_manager.scoring import embedding
from plan_manager.scoring.embedding import EmbeddingUnavailable, fetch_vector


class FakeEmbeddingClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def embed(self, texts, wait, wait_timeout):
        assert texts == ["probe"]
        assert wait is True
        assert wait_timeout == 60
        return {"results": [{"body": "probe", "embedding": [0.1, 0.2, 0.3]}]}


class BadEmbeddingClient:
    def __init__(self, **kwargs):
        pass

    async def embed(self, texts, wait, wait_timeout):
        return {"results": [{"body": "probe"}]}


def test_fetch_vector_uses_embed_client(monkeypatch) -> None:
    monkeypatch.setattr(embedding, "EmbeddingClient", FakeEmbeddingClient)

    assert fetch_vector("https://192.168.254.26:8001", "probe") == [0.1, 0.2, 0.3]


def test_fetch_vector_reports_malformed_embed_client_response(monkeypatch) -> None:
    monkeypatch.setattr(embedding, "EmbeddingClient", BadEmbeddingClient)

    with pytest.raises(EmbeddingUnavailable, match="embedding list"):
        fetch_vector("https://192.168.254.26:8001", "probe")


def test_fetch_vector_rejects_url_without_supported_scheme() -> None:
    with pytest.raises(EmbeddingUnavailable, match="unsupported embedding URL scheme"):
        fetch_vector("ftp://192.168.254.26:8001", "probe")
