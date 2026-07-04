"""Trust estimate: confidence in the semantic measurement itself (C-014).

Computes the geometry of the concept embedding basis (pairwise cosines, Gram
determinant, eigenvalue spectrum) and maps it to a monotone 0..1 trust value,
falling back to a declared floor when the embedding service is unavailable.
"""

from dataclasses import dataclass

import numpy as np
import psycopg

from plan_manager.scoring.embedding import EmbeddingUnavailable, embed_text


@dataclass
class TrustReport:
    """Confidence report for the semantic measurement."""

    trust: float
    available: bool
    pairwise_cosines: list[list[float]]
    gram_determinant: float
    spectrum: list[float]


def normalize_rows(vectors: list[list[float]]) -> np.ndarray:
    """Row-normalize a list of vectors to unit L2 norm."""
    array = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    safe_norms = np.where(norms == 0.0, 1.0, norms)
    return array / safe_norms


def basis_geometry(
    vectors: list[list[float]],
) -> tuple[list[list[float]], float, list[float]]:
    """Compute pairwise cosines, Gram determinant, and eigenvalue spectrum."""
    if not vectors:
        raise ValueError("basis_geometry requires a non-empty vector list")
    lengths = {len(row) for row in vectors}
    if len(lengths) != 1:
        raise ValueError("basis_geometry requires all rows to have equal length")
    normalized = normalize_rows(vectors)
    gram = normalized @ normalized.T
    determinant = float(np.linalg.det(gram))
    spectrum = sorted(np.linalg.eigvalsh(gram).tolist(), reverse=True)
    cosines = gram.tolist()
    return cosines, determinant, spectrum


def trust_from_geometry(gram_determinant: float, n: int) -> float:
    """Map Gram determinant and basis size to a 0..1 trust value."""
    if n == 0:
        return 0.0
    base = max(gram_determinant, 0.0)
    value = base ** (1.0 / n)
    return min(max(value, 0.0), 1.0)


def compute_trust(
    conn: psycopg.Connection,
    base_url: str,
    concept_definitions: list[str],
    trust_floor: float,
) -> TrustReport:
    """Compute the TrustEstimate for a set of concept definitions."""
    vectors: list[list[float]] = []
    for definition in concept_definitions:
        try:
            vectors.append(embed_text(conn, base_url, definition))
        except EmbeddingUnavailable:
            return TrustReport(
                trust=trust_floor,
                available=False,
                pairwise_cosines=[],
                gram_determinant=0.0,
                spectrum=[],
            )
    cosines, determinant, spectrum = basis_geometry(vectors)
    trust = trust_from_geometry(determinant, len(vectors))
    return TrustReport(
        trust=trust,
        available=True,
        pairwise_cosines=cosines,
        gram_determinant=determinant,
        spectrum=spectrum,
    )

