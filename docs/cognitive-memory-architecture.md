# Cognitive Memory & Context System — Architecture Specification

**Codename:** CORTEX (Cognitive Observation, Retrieval & Token-Efficient eXchange)
**Status:** LEGACY architecture spec. It remains useful as design background, but it is not a complete current-state document.
**Home:** A subsystem *inside* DANZA-OS. Every project / app / workflow DANZA builds
inherits a project-scoped memory automatically; cross-project knowledge is shared.
**Source of truth:** local repo. Multi-stack / multi-DB by design (adapter architecture).

Current baseline: CORTEX is now REAL/PARTIAL in `danzaboss/cortex/` as a local memory/context system. Some items below are roadmap or historical design language rather than current product reality.

---

## 0. What this is (and is not)

CORTEX is **not** a chatbot memory, a transcript archive, or a vector-search plugin. It is a
**cognitive layer** that sits between the user and the LLM and continuously maintains a living
model of each project — its code, architecture, decisions, history, and lessons — then assembles
**the smallest context that yields the highest-quality answer** for each request.

> **North star:** every subsystem exists to improve one number — the quality of the context
> package delivered to the model, per token spent.

The LLM never receives entire conversations, entire repositories, every memory, or every document.
It receives a ranked, compressed, budget-optimized package with an attached explanation of *why*
each item was included.

---

## 1. Positioning — the upgrade over existing tools

| Capability | claude-mem | memsearch | CTX | context-mode | **CORTEX** |
|---|:--:|:--:|:--:|:--:|:--:|
| Compress transcripts → observations | ✅ | ◑ | ✗ | ✅ | ✅ |
| Hybrid keyword + vector search | ✅ (FTS5+Chroma) | ✅ (Milvus) | ✗ | ◑ | ✅ **+ more signals** |
| Progressive disclosure (search→detail) | ✅ | ✅ | ✗ | ✗ | ✅ |
| Transcript binding / branching | ✗ | ✗ | ✅ | ◑ | ✅ (Live Workspace) |
| **Typed knowledge graph + traversal queries** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Layered memory (L0–L5) w/ per-layer policy** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Intent detection drives retrieval strategy** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Dynamic per-intent token budget** | ✗ (fixed workflow) | ✗ | ✗ | ◑ | ✅ |
| **Observation evolution / merge / confidence** | ◑ | ✗ | ✗ | ✗ | ✅ |
| **"When NOT to retrieve" anti-relevance** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Decision memory (the WHY) as a first-class type** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Cross-project reusable knowledge (L5)** | ✗ | ◑ | ✗ | ✗ | ✅ |
| **Context quality score + explainability** | ✗ | ✗ | ✗ | ✗ | ✅ |
| **Multi-signal fusion (graph+git+deps+usage)** | ✗ | ✗ | ✗ | ✗ | ✅ |
| Language-agnostic repo/doc/git intelligence | ◑ | ◑ | ✗ | ◑ | ✅ (tree-sitter) |
| Inherited by every project the OS builds | ✗ | ✗ | ✗ | ✗ | ✅ (DANZA-native) |

**Summary of the leap:** the incumbents are *transcript-compression + hybrid-search + progressive
disclosure*. CORTEX keeps those as the floor and adds the missing cognitive layer: a **structured,
graph-linked, layered, intent-aware, self-evolving model** that reasons about *why* the codebase
became what it is — and can explain every retrieval decision.

---

## 2. Design principles (optimization order)

1. **Retrieval quality over storage quantity.** Never optimize for storage; optimize for what comes back.
2. **Structured knowledge over raw transcripts.** Store observations, not conversations.
3. **Hybrid retrieval over single-method search.** Never trust embeddings alone.
4. **Explainability over opaque ranking.** Every included item carries a reason.
5. **Evolutionary memory that improves with use.** Merge, update, re-weight; don't duplicate.
6. **Modular components, independently replaceable.** Ports + adapters everywhere.
7. **Context quality is the primary optimization target.** Score every package; ship only good ones.

Negative space (things we deliberately do NOT do): save everything, store raw chat, trust one
retrieval method, use fixed token budgets, or ask the user to curate memory.

---

## 3. System overview

```
User prompt
   │
   ▼
Intent Detection ─────────────────────────────┐
   │                                           │ (intent tunes every stage below)
   ├───────────────┐                           │
   ▼               ▼                           │
Live Workspace   Memory Engine                 │
 (L0/L1)          (L2–L5)                       │
   │               │                            │
   ▼               ▼                            │
Repository     Observation Store               │
Intelligence   Knowledge Graph                 │
Doc Intelligence  Git Intelligence             │
   └──────┬────────┘                            │
          ▼                                     │
   Hybrid Retriever  ◄──────────────────────────┘
   (semantic + BM25 + graph + metadata + git + deps + recency + importance + usage)
          ▼
   Ranking → Deduplication → Compression → Token-Budget Optimizer
          ▼
   Context Quality Scorer  ──(reject & re-plan if low)──┐
          ▼                                             │
   Final Context Package (+ explanations) ──────────────┘
          ▼
        Claude
          │
          ▼
 Observation Extractor (background) → evolve/merge into Memory Engine + Graph
          │
          ▼
 Learning Engine (updates weights, expiry, importance from usage)
```

Every box is a **port with a default adapter** and can be swapped without touching its neighbors.

---

## 4. Core data models

### 4.1 Observation (the atomic unit of knowledge)

```python
@dataclass
class Observation:
    id: str
    title: str                     # one-line headline
    summary: str                   # dense, compressed body
    type: ObsType                  # bug_fix | decision | perf | dependency | security |
                                   # api_behavior | milestone | lesson | root_cause |
                                   # limitation | impl_detail | convention
    importance: Importance         # critical | high | medium | low | temporary | archive
    confidence: int                # 0–100 (see §Confidence)
    # scoping
    project: str
    repository: str
    branch: Optional[str]
    layer: int                     # which memory layer owns it (0–5)
    # lifecycle
    created: str; updated: str; last_used: Optional[str]
    usage_count: int = 0
    expires: Optional[str] = None  # aging policy resolves this
    # linkage (feeds the knowledge graph)
    tags: list[str]; concepts: list[str]
    files: list[str]; symbols: list[str]; dependencies: list[str]
    related_observations: list[str]; related_docs: list[str]
    related_commits: list[str]; related_issues: list[str]
    # reasoning (the part incumbents lack)
    reasoning: str                 # WHY, not just what
    evidence: list[str]            # commit hashes, file:line, doc anchors, user quote
    resolution: Optional[str]
    lessons: Optional[str]
    future_risks: Optional[str]
    # precision controls (the differentiator)
    when_relevant: list[str]       # intents/entities that SHOULD trigger this
    when_not_relevant: list[str]   # explicit anti-triggers → precision boost
    # evolution
    supersedes: Optional[str]      # id of an older observation this replaces
    history: list[dict]            # append-only change log (merge/expand/confidence bumps)
```

Two fields do most of the precision work and are absent from prior tools: **`when_relevant` /
`when_not_relevant`** (anti-relevance kills false positives) and **`reasoning`** (decision memory).

### 4.2 Knowledge graph node & edge

```python
@dataclass
class GraphNode:
    id: str
    kind: NodeKind      # entity | file | symbol | api | test | doc | commit | decision | dependency
    name: str
    project: str
    attrs: dict

@dataclass
class GraphEdge:
    src: str; dst: str
    relation: Relation  # depends_on | consumed_by | parent_of | child_of | touches |
                        # documented_by | tested_by | decided_by | introduced_in | related_to
    weight: float       # strength/confidence of the relationship
    evidence: list[str]
```

Supported queries (impossible with flat observations): *"What depends on JWT?"*, *"What breaks if
Redis changes?"* (reverse-dependency closure), *"Every API touching billing"*, *"What decisions
affected authentication?"* (decision→entity edges).

### 4.3 Layer descriptor

Each layer declares its own storage, retrieval, ranking, expiration, and confidence defaults:

```python
@dataclass
class LayerPolicy:
    layer: int
    store: str            # adapter id (e.g. sqlite-local, neon-shared)
    retrieval: list[str]  # signals enabled for this layer
    ranking: str          # ranker profile id
    expiry: str           # aging rule (e.g. "temporary:24h", "critical:never")
    default_confidence: int
```

---

## 5. Layered memory (L0–L5)

| Layer | Scope | Contents | Store (default) | Expiry | Retrieval emphasis |
|---|---|---|---|---|---|
| **L0** | Prompt/turn | current prompt, current message | in-memory | end of turn | verbatim |
| **L1** | Session | scratchpad, open files, branch, terminal, temp notes | in-memory + sqlite (ephemeral) | end of session (temporary→24h) | recency, open-file proximity |
| **L2** | Project | architecture, decisions, known bugs, roadmap, conventions, key files | **per-project** sqlite-local (→ Neon shared) | critical: never; else importance-aged | graph + BM25 + semantic |
| **L3** | Cross-session | lessons, successful fixes, historical bugs, repeated solutions, refactors, dev habits | project store, long-lived | slow decay by importance | usage history + semantic |
| **L4** | Personal | coding style, preferred frameworks, naming, response/format preferences | **global** shared store | never (until changed) | metadata filter, always-on |
| **L5** | Cross-project | reusable components, shared architecture, common libs, templates, frequently-solved problems | **global** shared store (Neon recommended) | never; confidence-gated | semantic + graph federation |

**Inheritance model:** L2 is instantiated **per project DANZA builds**; L3–L5 are **shared across all
projects**. A brand-new build therefore starts with your preferences (L4) and the OS's accumulated
reusable knowledge (L5), and immediately begins accruing its own L2/L3.

---

## 6. Subsystem contracts

Each subsystem is a port (interface). Defaults are adapters. Contracts kept minimal so they're
independently testable and replaceable.

### 6.1 IntentDetector
Classifies the prompt into an intent that reconfigures the whole pipeline.
```python
class IntentDetector(Protocol):
    def detect(self, prompt: str, workspace: "WorkspaceState") -> Intent: ...
# Intent ∈ {fix_bug, write_code, explain, refactor, architecture, docs, testing,
#           deploy, performance, security, planning, learning}
```
Each intent maps to (a) a **budget profile** (§9) and (b) a **signal-weight profile** (§8). Example:
`security` boosts graph traversal + dependency signals and the `security`/`decision` observation
types; `explain` boosts current-file + doc signals and lowers git history.

### 6.2 LiveWorkspace (L0/L1)
Owns volatile session state; the source for "what am I doing right now."
```python
class LiveWorkspace(Protocol):
    def snapshot(self) -> WorkspaceState: ...   # open files, branch, terminal, cursor, scratchpad
    def note(self, text: str) -> None: ...       # scratchpad, temporary observations
```

### 6.3 ObservationStore (L2–L5)
```python
class ObservationStore(Protocol):
    def upsert(self, obs: Observation) -> str: ...       # evolves, never blind-duplicates
    def get(self, ids: list[str]) -> list[Observation]: ...
    def query(self, q: Query) -> list[Scored[Observation]]: ...
    def age(self) -> AgingReport: ...                    # archive/expire per policy
```

### 6.4 KnowledgeGraph
```python
class KnowledgeGraph(Protocol):
    def add(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None: ...
    def neighbors(self, node_id: str, relation: Relation, depth: int = 1) -> list[GraphNode]: ...
    def impact(self, node_id: str) -> list[GraphNode]: ...  # "what breaks if X changes"
    def path(self, src: str, dst: str) -> list[GraphEdge]: ...
```

### 6.5 RepositoryIntelligence
Turns a repo into a navigable graph: folders, entry points, module boundaries, ownership,
generated vs third-party vs tests vs config. **Language-agnostic** via `LanguageAnalyzer` adapters
(tree-sitter grammars → same engine reads TypeScript, Python, Go, …).
```python
class RepositoryIntelligence(Protocol):
    def scan(self, root: str, incremental: bool = True) -> RepoModel: ...
    def symbols(self, path: str) -> list[Symbol]: ...
```

### 6.6 DocumentationIntelligence
Indexes markdown, wiki, API docs, READMEs, RFCs, comments; associates each doc with files,
observations, graph nodes, and APIs.
```python
class DocumentationIntelligence(Protocol):
    def index(self, root: str) -> DocModel: ...
    def for_node(self, node_id: str) -> list[DocRef]: ...
```

### 6.7 GitIntelligence
Understands commits, branches, MRs, authors, releases. Tags observations with commit hashes so
historical reasoning is retrievable ("why was this introduced?").
```python
class GitIntelligence(Protocol):
    def history(self, path: Optional[str], since: Optional[str]) -> list[Commit]: ...
    def summarize_changes(self, entity: str) -> str: ...   # compressed, e.g. "Recent Auth Changes"
```

### 6.8 HybridRetriever
Runs multiple retrieval methods, then **fuses** them (see §8). Never a single method.
```python
class HybridRetriever(Protocol):
    def retrieve(self, prompt: str, intent: Intent, budget: BudgetPlan) -> list[Scored[Item]]: ...
# signals: semantic, bm25, graph_traversal, metadata_filter, file_relationships,
#          git_history, observation_links, dependency_analysis, recency, importance,
#          confidence, usage_history
```

### 6.9 RetrievalPipeline
Ordered orchestration: intent → entity extraction → concept detection → repo/observation/doc/graph/
git/issue/dependency search → rank → dedup → compress → budget-optimize → final context.

### 6.10 Ranker
```python
class Ranker(Protocol):
    def rank(self, items: list[Scored[Item]], intent: Intent) -> list[Scored[Item]]: ...
```
Blends signal fusion score × importance × confidence × recency × usage, weighted by intent profile.

### 6.11 Compressor
Compresses code, docs, observations, git logs into dense summaries. **Never compresses away
reasoning.** Streaming so it feels instant.
```python
class Compressor(Protocol):
    def compress(self, item: Item, target_tokens: int, preserve: list[str]) -> Item: ...
```

### 6.12 ContextAssembler (the heart)
Decides how much of each category (code / docs / observations / architecture / history / git /
conversation) to include — **dynamically, never fixed** — given intent and the live budget.
```python
class ContextAssembler(Protocol):
    def assemble(self, retrieved: list[Scored[Item]], intent: Intent,
                 budget: BudgetPlan) -> ContextPackage: ...
```

### 6.13 TokenBudgetOptimizer
Computes the live budget (§9), then expands/contracts each category to maximize quality-per-token,
trimming lowest-marginal-value items first.

### 6.14 ContextQualityScorer
Scores every package on **relevance, novelty, coverage, redundancy, token-efficiency, completeness**.
Low-scoring packages are rejected and the pipeline re-plans (e.g. widen graph depth, drop a category).
```python
class ContextQualityScorer(Protocol):
    def score(self, pkg: ContextPackage, intent: Intent) -> QualityReport: ...
```

### 6.15 ExplainabilityLayer
Attaches to each included item a machine-readable reason: `["prompt references JWT",
"recently modified", "high confidence", "architecture dependency of Auth", "frequently useful"]`.
Enables debugging and trust.

### 6.16 LearningEngine
Observes usage (opened files, retrieved observations, solved bugs, repeated workflows, edited
modules) and updates retrieval weights, importance, and expiry. The system gets better with use.

### 6.17 ObservationExtractor (background, automatic)
After each meaningful interaction, detects: bug fixed? architecture changed? decision made? perf
improved? something learned? If yes → generates observations **without asking the user**, then
evolves/merges them into the store and graph. Runs off the hot path.

---

## 7. Adapter / port architecture (the modularity + multi-stack backbone)

This is what makes DANZA compatible across tech stacks and databases. The **engine** stays Python
(it lives in DANZA); the **things it plugs into** are swappable. Ports:

| Port | Responsibility | Default adapter | Alternatives |
|---|---|---|---|
| `StoragePort` | persist observations/layers | **SQLite (local, FTS5)** | **Neon/Postgres** (shared/team), any SQL |
| `SearchIndexPort` | keyword/BM25 | SQLite FTS5 | Postgres tsvector, Elastic |
| `VectorIndexPort` | semantic search | *none (off)* / local ONNX | pgvector (Neon), Chroma, Milvus |
| `GraphStorePort` | nodes/edges + traversal | SQLite recursive CTE | Postgres CTE, Neo4j |
| `EmbeddingProviderPort` | text→vectors | pluggable | local MiniLM, API providers |
| `LanguageAnalyzerPort` | parse code | tree-sitter (per grammar) | LSP servers |
| `CompressionModelPort` | summarize | LLM via DANZA | extractive/local |

**Consequence:** a project can start on zero-config local SQLite and graduate to Neon/Postgres for
team-shared memory *without touching engine code* — only the adapter binding changes. Because the
engine exposes an **MCP wrapper**, TypeScript tooling and Claude Code consume the same brain; the
engine's language never limits its consumers. (The concrete storage + embedding choices are
resolved in ADR-002 / ADR-005 below — flagged, not baked in here.)

---

## 8. Retrieval fusion (how signals combine)

Each enabled signal returns a ranked list. We fuse with **Reciprocal Rank Fusion** (robust,
score-scale-independent), then apply intent-weighted multipliers and object priors:

```
fused(item) = Σ_signal  w_intent[signal] * 1/(k + rank_signal(item))
final(item) = fused(item) * importance_mult * confidence_mult * recency_mult * usage_mult
              * anti_relevance_penalty(item, intent)   # when_not_relevant → strong penalty
```

`w_intent` is the per-intent weight vector (e.g. `security` → high graph+dependency; `explain` →
high current-file+doc). RRF means no single method can dominate, satisfying "never trust embeddings
alone." Anti-relevance (`when_not_relevant`) is a precision multiplier the incumbents lack.

---

## 9. Dynamic token budget (per intent)

The budget is **computed**, never fixed. Given a total window, reserve instructions, then allocate
the remainder across categories by intent, expanding/contracting each:

```
budget = total - system_instructions - response_reserve
allocate(budget) by intent profile, e.g. (fractions of the working budget):

Category          fix_bug  architecture  explain  performance  security
current_files       0.30      0.10         0.35      0.20        0.15
architecture        0.10      0.35         0.15      0.15        0.20
observations        0.25      0.20         0.10      0.20        0.25
documentation       0.05      0.15         0.25      0.05        0.10
git_history         0.15      0.10         0.05      0.20        0.10
dependency_graph    0.10      0.10         0.05      0.15        0.20
conversation        remainder in every profile
```

The TokenBudgetOptimizer then trims lowest-marginal-value items until the package fits, and the
QualityScorer verifies the result clears threshold before delivery.

---

## 10. Lifecycle & data flow

**Write path (background, off hot path):** interaction → ObservationExtractor detects meaningful
knowledge → drafts Observation(s) with reasoning + when_relevant/when_not → ObservationStore.upsert
**evolves/merges** (supersede, expand, bump confidence, append history) → KnowledgeGraph adds
nodes/edges → aging policy schedules expiry → LearningEngine updates weights.

**Read path (hot, <100 ms cached):** prompt → IntentDetector → entity/concept extraction →
HybridRetriever fans out across signals → RRF fusion + ranking → dedup → compression →
budget optimization → QualityScorer gate → ContextPackage (+ explanations) → LLM.

---

## 11. Integration with DANZA-OS

CORTEX is not bolted on; it maps onto the existing agent roster and the v2 modules already built:

| DANZA piece | CORTEX role |
|---|---|
| `samantha-mapper` | feeds **RepositoryIntelligence** (its 6-pass scan becomes the repo graph) |
| `mona-historian` | RETIRED / LEGACY owner reference; CORTEX now owns build-history and pattern memory concepts |
| `angela-auditor` | emits **decision** observations (the WHY) — decision memory |
| `carmella-researcher` | populates L5 cross-project reusable knowledge from research |
| `tony-d-orchestrator` | primary **ContextAssembler** consumer; requests packages per turn |
| v2 `memory/store.py` | the **seed** of ObservationStore (layered scopes already exist) — grows into it |
| v2 `context/pipeline.py` | the **seed** of the Assembler (select→compress→isolate already exists) |
| v2 `security/capabilities.py` | gates memory writes/reads (least privilege; secrets never stored) |

**Inheritance:** DANZA instantiates an L2 store per project it builds and binds L3–L5 to the global
shared store, so every new build starts with your preferences + the OS's reusable knowledge and
accrues its own project memory. Exposed to external tooling (your TS SaaS, Claude Code) via MCP.

---

## 12. Performance model

| Operation | Target | Mechanism |
|---|---|---|
| Cached retrieval | < 100 ms | hot index + memoized fusion |
| Observation extraction | background | off hot path, queued |
| Graph updates | incremental | only changed nodes/edges |
| Compression | streaming | token-by-token, early-out |
| Cold retrieval | < 1 s | bounded fan-out + budget cap |

---

## 13. Security & privacy

Secrets/keys/credentials are **never** stored as observations (extractor redaction pass). Memory
reads/writes are capability-gated (reuse Upgrade #10): only authorized agents write L2–L5; elevated
domains follow the same hard-stop/elevation model. Shared (Neon) stores add row-level project
scoping so cross-project leakage is structurally prevented.

---

## 14. Architecture Decision Records

> ADRs capture *why*. Each: context, options, decision, consequences. Recommendations below are
> proposals for your sign-off; ADR-002 is the one deferred earlier.

**ADR-001 — Layered memory over a single store.** *Context:* one flat store conflates volatile
session state with durable architecture. *Decision:* six layers (L0–L5), each with its own policy.
*Consequences:* +precision & correct aging; −more surface (mitigated by shared LayerPolicy).

**ADR-002 — Semantic/embedding retrieval strategy (deferred item).** *Context:* hybrid wants
meaning-based recall; SQLite has no native vectors, Neon has pgvector. *Options:* off (lexical+graph
only) / on day-one (needs embedding provider) / **pluggable, off by default**. *Recommendation:*
**pluggable, off by default; auto-enabled when a VectorIndex adapter (e.g. Neon+pgvector or local
ONNX) is bound.** Keeps zero-dependency local default, unlocks semantic recall where a vector store
exists. *Consequences:* retrieval quality varies by binding — QualityScorer surfaces this.

**ADR-003 — Multi-signal RRF fusion over vector-only.** *Decision:* combine ≥3 signals via RRF with
intent weights. *Consequences:* robust, explainable ranking; slightly more compute per query.

**ADR-004 — Structured observations over raw transcripts; auto-extraction in background.**
*Decision:* store observations with reasoning + relevance controls; extract automatically, never ask
the user. *Consequences:* dense, precise memory; requires a reliable extractor (confidence-gated).

**ADR-005 — Ports & adapters for multi-stack/multi-DB (SQLite local + Neon shared).** *Decision:*
every storage/index/graph/embedding/analyzer is a port; SQLite local default, Neon/Postgres shared
adapter. *Consequences:* portability across your TS/Neon world and any future stack; parity tests
required across adapters.

**ADR-006 — Knowledge graph as first-class retrieval + reasoning.** *Decision:* typed nodes/edges,
traversal + impact queries drive both retrieval and reasoning. *Consequences:* answers
"what breaks if X changes"; graph must stay incrementally consistent.

**ADR-007 — Language-agnostic analyzers (tree-sitter).** *Decision:* per-language grammar adapters
so one engine understands polyglot repos (TS, Python, …). *Consequences:* broad compatibility;
grammar upkeep per language.

---

## 15. Phased implementation roadmap (verifiable slices)

Each phase ships with tests + a measurable acceptance metric, promoted only when green.

- **P1 — Observation core + L2 store.** Evolve v2 `memory/store.py` into the Observation schema
  (reasoning, when_relevant/when_not, confidence, evolution/merge). *Accept: upsert merges instead
  of duplicating; anti-relevance measurably raises precision on a fixture set.*
- **P2 — Knowledge graph + Repository Intelligence.** tree-sitter analyzer + graph store; impact
  queries. *Accept: "what depends on X" / "what breaks if X changes" return correct closures.*
- **P3 — Hybrid retriever + RRF fusion + intent detection.** *Accept: fused ranking beats
  vector-only and BM25-only on a labeled retrieval eval.*
- **P4 — Context Assembler + dynamic budget + Quality Scorer.** Evolve v2 `context/pipeline.py`.
  *Accept: package respects per-intent budget and clears quality threshold; low packages re-planned.*
- **P5 — Compression + Explainability.** *Accept: reasoning preserved; every item carries a reason.*
- **P6 — Observation Extractor (background) + Learning Engine.** *Accept: meaningful interactions
  auto-produce observations; weights shift with usage on a replay.*
- **P7 — Git/Doc Intelligence + Neon shared adapter + MCP wrapper.** *Accept: L3–L5 shared across
  projects; external MCP consumer retrieves a package.*
- **P8 — Aging, cross-project L5 federation, ADR-002 vector binding.** *Accept: expiry runs;
  reusable knowledge surfaces in a new project.*

---

## 16. Open questions / next round
1. ADR-002 final binding (local ONNX vs Neon+pgvector as the default vector adapter) — decide with a
   retrieval eval once P3 exists.
2. Conflict resolution when L5 (cross-project) advice contradicts L2 (project-specific) — precedence rule.
3. Extraction confidence threshold for auto-write vs "hold for review."
4. Multi-agent concurrency on shared L3–L5 (locking/versioning) — reuse the kernel state lessons.
5. Package-quality threshold value and the re-plan strategy ladder.

---

*This spec is the blueprint. No engine code was written this phase. On approval of the ADR
recommendations (esp. ADR-002/005), P1 begins by evolving the existing v2 memory + context modules.*
