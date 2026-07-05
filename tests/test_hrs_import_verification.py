from plan_manager.domain.paragraph import parse
from plan_manager.domain.labeling import assign_missing_labels


def test_hrs_import_verification_model_ignores_non_stored_markdown() -> None:
    text = "# HRS\n\n{a1b2} Stored paragraph.\n\n<!-- non-binding -->\n\nDraft note.\n\n<!-- /non-binding -->\n"
    labeled, _new_labels = assign_missing_labels(parse(text))
    written = [
        {"label": paragraph.label, "text": paragraph.text, "position": paragraph.position}
        for paragraph in labeled
    ]

    assert written == [
        {"label": "a1b2", "text": "Stored paragraph.", "position": 0}
    ]
