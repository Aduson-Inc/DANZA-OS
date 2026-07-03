# Paid Research Tools for DANZA — Comparison + Recommendation

**Question:** are paid research/search APIs worth a small fee if results are far better? **Short answer:
yes, for the *summarizer* role** — replacing the fragile NotebookLM automation with a reliable paid
deep-research API is the single highest-value upgrade to the research squad. For the *collector* role, a
free tier covers early use; paid lanes add breadth cheaply.

## The two roles they'd fill (they map to the ports we built)
1. **Collector lane** (`research/sources.py` → `SourceLane`): fetch newest source URLs for a topic.
2. **Summarizer** (`research/summarizer.py` → `Summarizer`): read the sources, return a distilled,
   cited result. This is where NotebookLM sits today — and where it's most fragile.

## Landscape (as of mid-2026; prices move — re-check before committing)

| Tool | Best at | Rough price | Free tier | Fit for DANZA |
|---|---|---|---|---|
| **Tavily** | Search built *for* LLMs — ranked snippets, relevance scores, citations | ~$4–8 / 1k searches | **1,000/mo, no card** | **Default collector lane** |
| **Exa** | Embeddings/semantic + research/academic recency | ~$3–5 / 1k (variable 75–750+ credits/search) | limited | Semantic recency lane for "big" features |
| **Perplexity Sonar** | Cited, synthesized *answers* (deep research) via API | $5 / 1k searches + token costs | limited | **Reliable summarizer** (replace NotebookLM) |
| **Firecrawl** | Full web stack: search + scrape + crawl, deep-research endpoint | ~$5 / 1k (flat, predictable) | small | Summarizer alt + scrape lane |
| **Brave Search API** | Independent index, privacy, cheap breadth | $5 / 1k (flat) | removed Feb 2026 ($5 signup credit) | Cheap breadth lane |
| **Keiro** | Lowest cost | ~$0.50 / 1k | — | Budget breadth |
| **NotebookLM** (current) | Free, multi-source synthesis | $0 | n/a (unofficial automation) | Keep as free/optional, not the default |

## Recommendation for DANZA

**Summarizer (the important one):** make **Perplexity Sonar** (or Firecrawl deep-research) the *default*
`Summarizer` adapter, and demote NotebookLM to a free/optional fallback. Why: NotebookLM automation is
unofficial and breaks; Sonar is an official API returning **cited answers**, which is exactly the
"read the result, not the sources" output DANZA wants — more reliable *and* higher quality. This directly
resolves the fragility flag from the last two turns.

**Collector lanes:** start on **Tavily's free 1,000/mo** (LLM-optimized, cited). Add **Exa** for the
`is_big` features (semantic + research recency) and **Brave/Keiro** only if you need cheap breadth. All
three drop into the `SourceLane` port with zero changes to the squad.

## Cost reality (why "small fee" is accurate)
The throttle caps deep research at ~2 proposals/day. At ~$5/1k searches and a handful of
searches per proposal, that's **single-digit dollars per month**, not a real cost center. The fee buys
reliability + better recall — squarely "worth it if results are far better."

## Net
- **Do pay** for the summarizer (Perplexity Sonar / Firecrawl) — biggest quality + reliability jump, tiny cost.
- **Start free** on the collector (Tavily free tier), add Exa for big features later.
- **Keep NotebookLM** only as a $0 fallback adapter, never the critical path.
- Everything swaps behind the ports already built (`Summarizer`, `SourceLane`) — no rework to adopt.

*Sources: Firecrawl deep-research & alternatives blogs, KeiroLabs & Awesome Agents pricing roundups,
Brave "best search API 2026", Composio AI-search tools, alphacorp Perplexity-vs-Tavily — all 2026.*
