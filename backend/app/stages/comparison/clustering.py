"""Clustering (phase 4 A.1): group analyzed sources by approach/school of thought.

Embeddings give the candidate grouping (greedy centroid clustering — the
cluster count falls out of the data, it is never fixed in advance); an LLM
pass names and characterizes each cluster. A paper is primary in exactly one
cluster (`sources.cluster_id`) but can be noted as bridging others.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, update

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import AuditActionType
from app.db.models import Cluster, Source
from app.orchestrator.handler import StageContext
from app.schemas.comparison import ClusterNaming
from app.stages.comparison.roster import AnalyzedSource, valid_indexes
from app.stages.search.saturation import cosine_similarity

PROMPT_VERSION = "cluster_v1"


def greedy_clusters(roster: list[AnalyzedSource]) -> list[list[AnalyzedSource]]:
    """Centroid-threshold grouping; deterministic for a given roster order."""
    threshold = get_settings().cluster_similarity_threshold
    centroids: list[list[float]] = []
    groups: list[list[AnalyzedSource]] = []
    for item in roster:
        vector = item.source.embedding
        if vector is None:
            groups.append([item])  # un-embedded papers stand alone
            centroids.append([])
            continue
        vector = list(vector)
        best_index, best_similarity = -1, 0.0
        for i, centroid in enumerate(centroids):
            if not centroid:
                continue
            similarity = cosine_similarity(vector, centroid)
            if similarity > best_similarity:
                best_index, best_similarity = i, similarity
        if best_index >= 0 and best_similarity >= threshold:
            members = groups[best_index]
            members.append(item)
            old = centroids[best_index]
            n = len(members)
            centroids[best_index] = [
                (o * (n - 1) + v) / n for o, v in zip(old, vector, strict=True)
            ]
        else:
            groups.append([item])
            centroids.append(vector)
    return groups


def _render_groups(groups: list[list[AnalyzedSource]]) -> str:
    blocks = []
    for i, members in enumerate(groups):
        lines = "\n".join(
            f"  [{m.index}] {m.source.title} — Claim: {m.analysis.core_claim or '(none)'}"
            for m in members
        )
        blocks.append(f"Cluster {i}:\n{lines}")
    return "\n\n".join(blocks)


async def cluster_sources(
    ctx: StageContext, research_question: str, roster: list[AnalyzedSource]
) -> list[Cluster]:
    """(Re)build clusters from scratch: wipe prior rows, group, name, assign,
    audit. Rebuilding keeps re-entry simple when new analyses arrived."""
    await ctx.session.execute(
        update(Source).where(Source.project_id == ctx.project.id).values(cluster_id=None)
    )
    await ctx.session.execute(delete(Cluster).where(Cluster.project_id == ctx.project.id))
    await ctx.session.flush()

    groups = greedy_clusters(roster)
    naming = await ctx.llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    PROMPT_VERSION,
                    research_question=research_question,
                    clusters=_render_groups(groups),
                ),
            }
        ],
        ClusterNaming,
        prompt_version=PROMPT_VERSION,
        note="cluster naming",
    )
    by_index = {c.cluster_index: c for c in naming.clusters}

    clusters: list[Cluster] = []
    for i, members in enumerate(groups):
        named = by_index.get(i)
        bridging = valid_indexes(named.bridging_source_indexes, roster) if named else []
        characteristics: dict[str, Any] = {
            "characteristics": list(named.defining_characteristics) if named else [],
            "bridging_source_ids": [b.source.id for b in bridging],
        }
        cluster = Cluster(
            project_id=ctx.project.id,
            label=named.label if named else f"Cluster {i + 1}",
            description=named.description if named else None,
            defining_characteristics=characteristics,
        )
        ctx.session.add(cluster)
        await ctx.session.flush()
        for member in members:
            member.source.cluster_id = cluster.id
        clusters.append(cluster)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.cluster_assigned,
            description=f"Cluster '{cluster.label}': {len(members)} paper(s)",
            reasoning=cluster.description or "Grouped by embedding similarity.",
            payload={
                "cluster_id": cluster.id,
                "source_ids": [m.source.id for m in members],
                "bridging_source_ids": characteristics["bridging_source_ids"],
            },
            run_id=ctx.run.id,
            stage=ctx.stage.value,
        )
    await ctx.session.flush()
    return clusters
