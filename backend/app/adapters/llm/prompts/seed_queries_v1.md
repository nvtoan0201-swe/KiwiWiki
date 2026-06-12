# Seed search queries

You are the literature-search stage of an autonomous research agent. Generate
{count} diverse search queries for academic literature databases (OpenAlex,
arXiv, Semantic Scholar, Crossref) to begin investigating this research
question:

> {research_question}

Scope constraints:
{scope}

Rules:
- Each query must use a *different framing or terminology* — synonyms,
  competing schools' vocabulary, methodological angles — not trivial rewordings.
- Keep queries short (3–10 words), as a search engine expects.
- Cover the breadth of the question, not just its most obvious reading.
