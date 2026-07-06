import asyncio

from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.plan_status_metadata import get_plan_status_metadata
from plan_manager.scoring import embedding


def test_info_identity_section_does_not_build_runtime(monkeypatch) -> None:
    def fail_runtime():
        raise AssertionError("runtime summary should not be built for identity")

    monkeypatch.setattr(InfoCommand, "_runtime_summary", staticmethod(fail_runtime))

    result = asyncio.run(InfoCommand().execute(section="identity"))

    assert isinstance(result, SuccessResult)
    assert result.data["section"] == "identity"
    assert result.data["identity"]["product"] == "plan_manager"


def test_info_capabilities_section_does_not_build_runtime(monkeypatch) -> None:
    def fail_runtime():
        raise AssertionError("runtime summary should not be built for capabilities")

    monkeypatch.setattr(InfoCommand, "_runtime_summary", staticmethod(fail_runtime))

    result = asyncio.run(InfoCommand().execute(section="capabilities"))

    assert isinstance(result, SuccessResult)
    assert result.data["section"] == "capabilities"
    assert "step_lifecycle" in result.data["capabilities"]


def test_plan_status_metadata_defers_semantic_scoring() -> None:
    class Fake:
        name = "plan_status"
        version = "1.0.0"
        descr = "status"
        category = "plan"
        author = "a"
        email = "e"

    metadata = get_plan_status_metadata(Fake)

    scoring = metadata["return_value"]["success"]["example"]["scoring"]
    assert scoring["deferred"] == "plan_score"
    assert "embedding-backed scores inline" in metadata["best_practices"][2]
    assert "EMBEDDINGS_UNAVAILABLE" not in metadata["error_cases"]


def test_fetch_vector_forwards_timeout(monkeypatch) -> None:
    calls = {}

    class FakeEmbeddingClient:
        def __init__(self, **kwargs):
            calls["client_timeout"] = kwargs["timeout"]

        async def embed(self, texts, wait, wait_timeout):
            calls["wait_timeout"] = wait_timeout
            return {"results": [{"embedding": [0.1]}]}

    monkeypatch.setattr(embedding, "EmbeddingClient", FakeEmbeddingClient)

    assert embedding.fetch_vector("https://127.0.0.1:8001", "probe", timeout=2.5) == [0.1]
    assert calls == {"client_timeout": 2.5, "wait_timeout": 2.5}
