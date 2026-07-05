from plan_manager.domain.step_runtime import empty_runtime_record, merge_runtime_record


def test_runtime_merge_appends_activations_idempotently() -> None:
    record = merge_runtime_record(
        empty_runtime_record(),
        {
            "activations": [
                {
                    "activation_id": "act-1",
                    "chat_id": "chat-1",
                    "started_at": "2026-07-06T00:00:00Z",
                }
            ]
        },
    )
    record = merge_runtime_record(
        record,
        {
            "activations": [
                {
                    "activation_id": "act-1",
                    "chat_id": "chat-1",
                    "started_at": "2026-07-06T00:00:00Z",
                }
            ]
        },
    )

    assert len(record["activations"]) == 1


def test_runtime_merge_replaces_journal_aggregate_only_when_not_older() -> None:
    record = merge_runtime_record(
        empty_runtime_record(),
        {
            "journal_aggregates": {
                "direct_count": 2,
                "indirect_count": 3,
                "total_cost": 1.25,
                "last_linked_at": "2026-07-06T10:00:00Z",
            }
        },
    )
    record = merge_runtime_record(
        record,
        {
            "journal_aggregates": {
                "direct_count": 1,
                "indirect_count": 1,
                "total_cost": 0.1,
                "last_linked_at": "2026-07-06T09:00:00Z",
            }
        },
    )

    assert record["journal_aggregates"]["direct_count"] == 2


def test_runtime_merge_replaces_authoring() -> None:
    record = merge_runtime_record(
        empty_runtime_record(),
        {
            "authoring": {
                "model_type": "haiku",
                "provider": "anthropic",
                "authored_at": "2026-07-06T00:00:00Z",
            }
        },
    )
    record = merge_runtime_record(
        record,
        {
            "authoring": {
                "model_type": "gpt-nano",
                "provider": "openai",
                "authored_at": "2026-07-06T01:00:00Z",
            }
        },
    )

    assert record["authoring"]["provider"] == "openai"
