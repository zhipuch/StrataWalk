<div align="center">

# StrataWalk

### Give long documents a hierarchy. Give agents a way to explore it.

Agentic long-document understanding through order-preserving summary trees,
multi-scale semantic search, and evidence-grounded navigation.

Build bottom-up · Search across scales · Navigate with intent · Answer with evidence

Architecture (#architecture) ·
Agent Tools (#agent-tools) ·
Design Principles (#design-principles) ·
Roadmap (#roadmap)
</div>

———

> Project status — Design preview
>
> This repository introduces the proposed architecture of StrataWalk.
> Implementation, runnable examples, and benchmarks are planned.
> Capabilities described below are design targets unless explicitly marked as released.

## Why StrataWalk?

Long-document questions require different reading strategies.

A precise question may need a single passage. A comparison may span several
chapters. An explanation of the document's central argument may require both
a global overview and detailed supporting evidence.

StrataWalk is designed to give an agent access to all of these scales.

It builds a hierarchy from source passages to chapter-level summaries and
document-level abstractions. The agent can enter this hierarchy through semantic
search or a compact document map, move toward broader context or finer detail,
and assemble evidence within a bounded working context.

The goal is to make a long document navigable at the level each question needs.

## The Core Idea

StrataWalk combines three mechanisms:

- Ordered recursive abstraction: summarize adjacent document regions
  bottom-up while preserving their source order.
- Multi-scale semantic search: embed source passages and summary blocks,
  allowing retrieval to begin at different abstraction levels.
- Agent-directed navigation: let the agent decide where to start,
  which branches to explore, when to recover broader context, and when
  the evidence supports an answer.

The resulting tree acts as persistent document memory. A tool-driven agent
maintains a smaller working context while exploring that memory.

## Architecture

This Mermaid diagram exceeds the terminal renderer's size limits.
flowchart TB
    DOC["Long document"] --> PARSE["Parse chapters and document structure"]
    PARSE --> CHUNK["Create overlapping, token-bounded source chunks"]
    CHUNK --> LEAF["Source leaves + embeddings"]
    LEAF --> REDUCE["Summarize adjacent groups within token budgets"]
    REDUCE --> SUMMARY["Summary nodes with addressable topic blocks"]
    SUMMARY --> AGAIN{"Fits the root budget?"}
    AGAIN -->|No| REDUCE
    AGAIN -->|Yes| ROOT["Document root"]

    LEAF -.-> STORE["Multi-scale embedding index"]
    SUMMARY -.-> STORE
    ROOT -.-> STORE

    QUERY["User question"] --> AGENT["Navigation agent"]
    MAP["Compact document map"] --> AGENT
    ROOT -.-> MAP
    STORE <-->|"Semantic entry points"| AGENT
    AGENT <-->|"Move up / move down"| TREE["Persisted tree + source references"]
    AGENT --> MEMORY["Working context + evidence ledger"]
    MEMORY --> AGENT
    AGENT --> ANSWER["Answer with source citations"]

### 1. Establish Source Structure

Use document parsing and LlamaIndex-based processing to identify chapters or
sections where reliable structure is available.

Within each section, create overlapping source chunks that fit the configured
embedding model's input budget. The chunk size is configurable; a value such
as 1,024 tokens is an initial setting to evaluate, rather than a universal limit.

When reliable chapter boundaries are unavailable, use a documented fallback
segmentation policy.

Each source leaf retains:

- Its original text.
- Its document and section identifiers.
- Its position in the original document.
- Page references or character offsets, where available.
- Its embedding and parent reference.

Source text remains available throughout the hierarchy.

### 2. Build the Tree Bottom-Up

Group adjacent source chunks within a summarization token budget.

For each group, an LLM generates a parent node containing a bounded set of
summary paragraphs or topic blocks. These blocks are embedded individually
and retain references to their supporting children.

Repeat this process within chapters, then across adjacent chapter
representations, until the document fits a configured root budget.

Document root
├── Overview block
├── Major themes
│
├── Chapters 1–2 summary
│   ├── Chapter 1 summary
│   │   ├── Passage-group summary
│   │   │   ├── Source chunk 001
│   │   │   └── Source chunk 002
│   │   └── Passage-group summary
│   │       ├── Source chunk 003
│   │       └── Source chunk 004
│   └── Chapter 2 summary
│       └── ...
│
└── Chapters 3–4 summary
    └── ...

Illustrative hierarchy; the number of levels depends on document length
and configured budgets.

Grouping follows document order. Summary blocks are stored in source order
where their supporting regions permit it; cross-cutting themes retain
explicit source references.

A long chapter may require several reduction rounds before producing its
chapter-level representation.

#### Nodes and blocks

A node is a structural container with parent–child links and a source span.

A block is an addressable unit of text inside a node, such as a summary
paragraph or topic. Each block can have its own embedding and supporting
child references.

A search result therefore identifies both a node and the specific block
that matched the query.

This lets the agent retrieve a focused topic while retaining access to
its structural context and underlying evidence.

#### Token-aware reduction

Each summarization request must satisfy:

prompt tokens
+ input block tokens
+ reserved output tokens
+ safety margin
≤ summarizer context limit

Reduction must also produce a smaller representation. Bounded output budgets
and a minimum reduction policy prevent repeated summarization from stalling.

The root may contain several blocks; it does not need to collapse into
one paragraph.

### 3. Let the Agent Navigate

At query time, provide the agent with:

- The user's question and relevant conversation context.
- A compact document map.
- Navigation and search tools.
- A bounded working context and an evidence ledger.

The document map includes selected chapter descriptors and ancestor summaries,
deduplicated and constrained by a token budget. Larger maps can be loaded
progressively.

The agent then:

1. Interprets the question and identifies subquestions where useful.
2. Selects one or more entry points through the map or semantic search.
3. Reads the available information and identifies evidence gaps.
4. Moves upward for broader context or downward for finer detail.
5. Explores independent branches concurrently where useful.
6. Compacts working context while preserving evidence references.
7. Produces an answer supported by source passages, or explains the
   remaining uncertainty.

The traversal policy adapts to the question. It can begin at the root,
a chapter summary, an intermediate topic, or a source leaf.

## Agent Tools

The following interfaces describe the proposed tool contract.
They are not released API signatures.

| Tool | Purpose | Expected behavior |
|---|---|---|
| search | Find semantic entry points | Search source and summary blocks; return text, node IDs, block IDs, levels, scores, and source spans. |
| move_up | Recover broader context | Load parent summaries and their structural metadata. |
| move_down | Inspect supporting detail | List or load selected children, with pagination and token limits. |
| compact_context | Maintain a bounded working context | Preserve verified findings, citations, unresolved questions, and the exploration frontier. |
| finish | End the exploration | Return a supported answer, a partial answer, or an explicit statement of insufficient evidence. |

Navigation tools should accept batches of node IDs so independent branches
can be explored efficiently.

search remains available throughout exploration, allowing the agent to
recover from an unproductive branch or locate another relevant region.

### Context Management

StrataWalk separates persistent document memory from query-specific working
memory.

| Memory | Contents |
|---|---|
| Document memory | Source text, summary blocks, embeddings, tree links, and provenance. |
| Working memory | Current passages, subquestions, candidate branches, and recent tool results. |
| Evidence ledger | Verified claims, supporting source references, conflicts, and open questions. |

Context compaction reduces the active workspace while retaining references
needed to reload evidence.

The runtime should reserve space for tool results and the final answer,
and trigger compaction before the context window is exhausted.

### Stopping Conditions

Exploration is bounded by configurable limits on tool calls, tokens,
latency, and concurrent branches.

The agent should finish when the evidence adequately supports the answer,
or when further exploration is unlikely to resolve a remaining gap within
the available budget.

Repeated visits and duplicate evidence should be tracked to avoid loops
and inflated support from overlapping chunks.

## Design Principles

### Preserve document order

Build higher-level representations from adjacent regions so the hierarchy
retains the progression of the source document.

### Make every scale searchable

Embed source passages and summary blocks. A question about a broad theme
should be able to enter at a different level from a question about a
specific figure.

### Keep abstractions connected to evidence

Summary blocks retain supporting child references. The agent can descend
from an overview to the passages needed to verify a claim.

### Use summaries for orientation

Recursive summaries are lossy. They help the agent locate relevant regions;
specific claims, numbers, and quotations should be checked against source text.

### Keep the agent's workspace bounded

The document index persists outside the model context. The agent loads
relevant regions progressively and maintains a compact evidence ledger.

### Expose the retrieval process

Record visited node IDs, tool actions, source references, and resource usage
so retrieval behavior can be inspected and evaluated.

## Indexing Efficiency

The construction pipeline is designed around parallel work:

- Batch embeddings across source passages and summary blocks.
- Summarize independent groups concurrently.
- Process independent chapters in parallel.
- Schedule parent tasks as soon as their children are ready.
- Cache completed artifacts to support resumable construction.

Parent–child dependencies still constrain execution. A parent cannot be
summarized before its children exist.

For a roughly balanced tree with a stable reduction factor, the number
of levels grows logarithmically with the number of source chunks.
Actual latency and cost depend on token volume, generation length,
model throughput, concurrency limits, and tree shape.

Indexing speed and retrieval quality remain evaluation targets.
No performance advantage is claimed before reproducible measurements.

## Relationship to Existing Work

StrataWalk draws on hierarchical retrieval and agentic document navigation.

- PageIndex demonstrates
  reasoning-based retrieval over document trees and emphasizes vectorless
  navigation. StrataWalk's proposed design combines explicit tree navigation
  with embeddings at multiple abstraction levels.
- RAPTOR introduces recursive embedding,
  clustering, and summarization for tree-organized retrieval. StrataWalk
  focuses on source-ordered reduction and a tool-driven navigation loop
  with explicit working-context management.

The intended contribution is the integration of ordered abstraction,
multi-scale entry points, evidence-linked traversal, and bounded agent memory.

## Evaluation Plan

Evaluation should cover both answer quality and the resources required
to obtain it.

| Area | Planned measurements |
|---|---|
| Index construction | Wall-clock time, input/output tokens, cost, tree depth, and storage. |
| Retrieval | Evidence recall, source coverage, redundant retrieval, and tool calls. |
| Answer quality | Correctness, citation accuracy, completeness, and unsupported claims. |
| Agent execution | Latency, peak context usage, token cost, and budget exhaustion. |
| Summary fidelity | Preservation of entities, numbers, qualifications, and conflicting claims. |

Planned comparisons include flat vector retrieval, recursive-summary retrieval,
tree navigation, and full-document prompting where the document fits.

Ablations should test:

- Source-only embeddings versus embeddings at all levels.
- Map-only entry versus semantic entry versus their combination.
- Navigation with and without upward moves.
- Context compaction with and without an evidence ledger.
- Different grouping budgets, overlap settings, and reduction factors.

## Roadmap

- [ ] Define node, block, provenance, and storage schemas.
- [ ] Implement section parsing and token-aware source chunking.
- [ ] Implement ordered recursive reduction with bounded outputs.
- [ ] Add embeddings for source and summary blocks.
- [ ] Add persistent tree links and source-span lookup.
- [ ] Implement search and batched navigation tools.
- [ ] Add context compaction and an evidence ledger.
- [ ] Add citation-grounded answer generation.
- [ ] Add concurrency, caching, retries, and resumable indexing.
- [ ] Publish an end-to-end example and reproducible benchmarks.

## Current Availability

This initial release contains the design document.

Installation instructions, supported model providers, document formats,
and runnable examples will be published alongside the implementation.

## Contributing

Feedback on the architecture, evaluation methodology, and agent tool
design is welcome.

Particularly useful contributions include difficult long-document questions,
examples where recursive summaries lose important evidence, and workloads
that require reasoning across distant sections.

Please describe the source material, expected evidence, and the failure
mode when proposing an evaluation case.

## Author

Created by zhipuch.

———

From passages to perspective. From perspective back to evidence.
