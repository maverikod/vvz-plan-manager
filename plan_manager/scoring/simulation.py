"""Executor simulation detector (C-015).

Deterministically filters a cheap generative model's answer about entities
an assembled prompt (C-011) uses but does not define. The raw model output
is treated only as suspicion: every survival judgement is a deterministic
text computation against the prompt text, never a model opinion.
"""

import re

SIMULATION_QUESTION = (
    "Name every entity this prompt uses but does not define. Answer with one "
    "entity name per line and nothing else."
)


def build_simulation_input(prompt_text: str) -> str:
    r"""Build the text sent to the cheap model for executor simulation."""
    return SIMULATION_QUESTION + "\n\n" + prompt_text


def extract_candidates(model_output: str) -> list[str]:
    """Extract candidate entity names from the raw model output."""
    marker_re = re.compile(r"^(?:[-*]|\d+[.)])\s*")
    seen: set[str] = set()
    candidates: list[str] = []
    for line in model_output.split("\n"):
        stripped = line.strip()
        stripped = marker_re.sub("", stripped)
        if not stripped:
            continue
        if stripped not in seen:
            seen.add(stripped)
            candidates.append(stripped)
    return candidates


def occurs_in_prompt(candidate: str, prompt_text: str) -> bool:
    r"""Determine whether candidate occurs as a whole word in prompt_text."""
    return re.search(r"\b" + re.escape(candidate) + r"\b", prompt_text) is not None


def is_defined_in_prompt(candidate: str, prompt_text: str) -> bool:
    r"""Determine whether candidate is deterministically defined in prompt_text."""
    escaped = re.escape(candidate)
    if re.search(r"(def|class)\s+" + escaped + r"\b", prompt_text):
        return True
    if re.search(r"^\s*" + escaped + r"\s*=", prompt_text, re.MULTILINE):
        return True
    if re.search(r"^\s*" + escaped + r"\s*:", prompt_text, re.MULTILINE):
        return True
    return False


def surviving_candidates(model_output: str, prompt_text: str) -> list[str]:
    """Return candidates that occur in prompt_text but are not defined there."""
    candidates = extract_candidates(model_output)
    return [
        candidate
        for candidate in candidates
        if occurs_in_prompt(candidate, prompt_text)
        and not is_defined_in_prompt(candidate, prompt_text)
    ]


def surviving_fraction(model_output: str, prompt_text: str) -> float:
    """Return the fraction of extracted candidates that survive filtering."""
    candidates = extract_candidates(model_output)
    if not candidates:
        return 0.0
    survivors = surviving_candidates(model_output, prompt_text)
    return len(survivors) / len(candidates)


def simulation_vote(model_output: str | None, prompt_text: str) -> float | None:
    """Compute the executor simulation detector's ensemble vote."""
    if model_output is None:
        return None
    candidates = extract_candidates(model_output)
    if not candidates:
        return None
    survivors = surviving_candidates(model_output, prompt_text)
    if not survivors:
        return None
    return 1.0 - surviving_fraction(model_output, prompt_text)
