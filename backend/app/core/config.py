"""Runtime configuration, loaded from environment / .env.

A single `Settings` object is the source of truth for every tunable: database,
Redis, the Anthropic key, embeddings, source API keys, and budget defaults.
Access it through `get_settings()` so it is parsed once and cached.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # --- Infrastructure ------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/research_agent"
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM -----------------------------------------------------------------
    anthropic_api_key: str = ""
    agent_model: str = "claude-opus-4-8"
    llm_max_retries: int = 3

    # --- Embeddings ----------------------------------------------------------
    embeddings_provider: str = "stub"  # concrete providers land in Phase 2
    embeddings_model: str = "voyage-3"
    embedding_dim: int = 1024

    # --- External source APIs (optional keys; adapters land in Phase 2) ------
    openalex_mailto: str = ""
    semantic_scholar_api_key: str = ""
    crossref_mailto: str = ""

    # --- Budget defaults (ceilings used when a project omits its own) --------
    default_budget_llm_tokens: int = 2_000_000
    default_budget_search_calls: int = 500
    default_budget_papers_read: int = 100
    default_budget_seconds: int = 3600

    # --- Orchestration (Phase 1) ----------------------------------------------
    # Max identical (from, to) loop-backs before the engine escalates instead.
    loop_back_max: int = 3
    # low | medium | high — modulates whether borderline triggers escalate or
    # proceed with a noted assumption.
    escalation_sensitivity: str = "medium"

    # --- Literature search (Phase 2) -------------------------------------------
    # Relevance bands (score >= band → status).
    relevance_deep_read_threshold: float = 0.7
    relevance_skim_threshold: float = 0.4
    relevance_set_aside_threshold: float = 0.15
    # Saturation: a new paper is "novel" if its nearest-neighbor similarity to the
    # existing set is below the cutoff; an iteration saturates when the novel
    # share drops below the floor; N consecutive saturated iterations stop search.
    saturation_similarity_cutoff: float = 0.85
    saturation_novelty_floor: float = 0.2
    saturation_consecutive_iterations: int = 2
    search_iteration_cap: int = 5
    search_seed_query_count: int = 4
    # Snowballing: 1 hop from the strongest N papers.
    snowball_top_n: int = 5
    # Echo chamber: mean pairwise similarity above this (with enough papers)
    # triggers counter-viewpoint reformulation.
    echo_chamber_similarity: float = 0.92
    echo_chamber_min_papers: int = 4
    # Reformulate when an iteration is mostly duplicates / mostly low relevance.
    reformulate_duplicate_ratio: float = 0.7
    reformulate_low_relevance_ratio: float = 0.7

    # --- Paper analysis (Phase 3) ----------------------------------------------
    # Concurrent LLM extractions per batch (DB writes stay in the handler task).
    analysis_concurrency: int = 4
    # Characters of paper text passed to extraction prompts.
    analysis_max_text_chars: int = 30_000
    # A missing seminal work/subfield must be referenced by at least this many
    # distinct papers (in one execution) before analysis loops back to search.
    analysis_missing_subfield_min_mentions: int = 2
    # Contradiction candidate pairing: only compare claims of sources whose
    # embedding similarity is at least the threshold, up to N candidates.
    contradiction_candidate_similarity: float = 0.5
    contradiction_max_candidates: int = 5

    # --- Comparative & gap analysis (Phase 4) -----------------------------------
    # Greedy clustering: a source joins a cluster when similarity to its
    # centroid reaches the threshold, else it founds a new cluster.
    cluster_similarity_threshold: float = 0.55
    # Fewer analyzed sources than this = evidence base too thin to map; loop back.
    comparison_min_analyzed_sources: int = 3
    # A single-paper cluster below this credibility makes the map lopsided.
    weak_cluster_credibility: float = 0.4
    # Consensus resting on sources with mean credibility below the floor is
    # capped at `emerging` (never `well_established`).
    consensus_credibility_floor: float = 0.6

    # --- API -----------------------------------------------------------------
    cors_origins: str = "http://localhost:5173"

    log_level: str = Field(default="INFO")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def default_budget(self) -> dict[str, int]:
        return {
            "llm_tokens": self.default_budget_llm_tokens,
            "search_calls": self.default_budget_search_calls,
            "papers_read": self.default_budget_papers_read,
            "time": self.default_budget_seconds,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
