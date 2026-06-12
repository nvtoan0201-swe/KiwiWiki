"""Idea-saturation detection (phase 2C step 7).

Operationalization: a newly triaged-in paper is *novel* if its nearest-neighbor
cosine similarity to the already-collected embeddings is below the cutoff. An
iteration counts as saturated when the novel share falls below the floor AND
the LLM judge says the batch introduced no new ideas. N consecutive saturated
iterations (default 2) stop the search.
"""

from __future__ import annotations

import math

from app.core.config import get_settings

Vector = list[float]

STATE_SEARCHING = "still finding new ideas"
STATE_APPROACHING = "approaching saturation"
STATE_SATURATED = "saturated"


def cosine_similarity(a: Vector, b: Vector) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def max_similarity(vector: Vector, existing: list[Vector]) -> float:
    if not existing:
        return 0.0
    return max(cosine_similarity(vector, e) for e in existing)


def novelty_share(new_vectors: list[Vector], existing: list[Vector]) -> float:
    """Share of new vectors whose nearest neighbor in `existing` is below the
    similarity cutoff. With nothing collected yet, everything is novel."""
    if not new_vectors:
        return 0.0
    if not existing:
        return 1.0
    cutoff = get_settings().saturation_similarity_cutoff
    novel = sum(1 for v in new_vectors if max_similarity(v, existing) < cutoff)
    return novel / len(new_vectors)


def iteration_saturated(share: float, judge_new_ideas: bool) -> bool:
    floor = get_settings().saturation_novelty_floor
    return share < floor and not judge_new_ideas


def saturation_state(consecutive_saturated: int) -> str:
    needed = get_settings().saturation_consecutive_iterations
    if consecutive_saturated >= needed:
        return STATE_SATURATED
    if consecutive_saturated > 0:
        return STATE_APPROACHING
    return STATE_SEARCHING


def mean_pairwise_similarity(vectors: list[Vector]) -> float:
    if len(vectors) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            total += cosine_similarity(vectors[i], vectors[j])
            count += 1
    return total / count
