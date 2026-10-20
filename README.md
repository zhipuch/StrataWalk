<div align="center">

<img src="assets/hero.png" alt="StrataWalk — Long context. Navigable memory. Ordered summary trees, multi-scale search, and agent-directed navigation." width="100%">

### Hierarchical memory for long-context agents

**Zoom out for perspective. Zoom in for evidence.**

[Quick Start](#quick-start) · [The Design](#the-stratawalk-design) · [Beyond Documents](#long-context-beyond-documents) · [Watch the Walk](#watch-the-walk) · [Architecture](docs/architecture.md)

<sub>Early implementation · Markdown/TXT today · Offline demo available · Live-model benchmarks pending</sub>

</div>

---

A precise question needs a passage. A comparison needs several regions.
An explanation needs the larger picture—and a way back to its supporting details.

**StrataWalk turns long, ordered text into navigable external memory.**
It builds a source-ordered summary tree, makes source passages and summary topics
searchable, and lets an agent change reading scale as the question develops.
The tree persists outside the model context; each question uses a bounded workspace.

Long documents are the first implementation. The underlying design targets
**long-context exploration** wherever material can be segmented, organized,
and linked back to stable source evidence.

## The StrataWalk Design

| Mechanism | What it gives the agent |
| :--- | :--- |
| **Source order as the backbone** | Adjacent passages reduce into adjacent higher-level regions, retaining the progression of an argument or sequence. |
| **Search at every scale** | Source chunks and individual summary topics have embeddings. A question can enter at a detail, a theme, or an overview. |
| **A walk that changes direction** | Move up for context, down for supporting detail, or search for another branch. Entry points and actions depend on the question. |
| **Persistent memory, bounded working context** | Keep the index outside the prompt. Load whole nodes as needed; compact working notes and restore cached evidence. |

**The distinctive combination is ordered abstraction + semantic entry + explicit
navigation + context management.** Summaries orient the walk; original passages
support precise claims.

## Quick Start

Python 3.9+, no API key or third-party runtime dependencies:

```bash
git clone https://github.com/zhipuch/StrataWalk.git
cd StrataWalk
PYTHONPATH=src python3 examples/offline_demo.py
```

The example builds `.stratawalk/example.json`, retrieves source excerpts,
and prints character-offset citations and a `search → finish` trace.
Extractive summaries, hashed lexical vectors, and a scripted policy make this
an offline plumbing demonstration. Real models choose their own tool actions.

Try your own UTF-8 Markdown/TXT file:

```bash
PYTHONPATH=src python3 -m stratawalk build notes.md --output .stratawalk/notes.json
PYTHONPATH=src python3 -m stratawalk inspect .stratawalk/notes.json
PYTHONPATH=src python3 -m stratawalk ask .stratawalk/notes.json 'Which findings disagree?' --json
```

These commands default to the offline fixtures. For LLM summaries and an
LLM-directed walk, configure chat and embedding endpoints and pass
`--provider compatible` to both `build` and `ask`: [model setup and usage](docs/usage.md).

## Long Context, Beyond Documents

The reusable unit is **source text → ordered hierarchy → searchable blocks →
question-directed exploration**. Document chapters are one way to define regions;
the Python API accepts a custom section parser with exact source offsets.

| Material | Natural regions | Support today / work needed |
| :--- | :--- | :--- |
| Reports, books, manuals | Chapters and sections | Markdown/TXT indexing and querying implemented; PDF/OCR needs an adapter. |
| Conversation history, meeting transcripts | Sessions, turns, time ranges | A text snapshot can be indexed; speaker/time metadata and update policies need adapters. |
| Research notes, collected evidence | Items, topics, source groups | One combined text snapshot works; separate source identities and corpus routing need extensions. |
| Code and execution traces | Files, symbols, execution stages | Text is indexable; syntax, dependencies, and exact code analysis need task-specific tools and links. |

**This is a general design for organizing long context; its usefulness depends
on the workload.** Stable source references, meaningful segmentation, and useful
abstractions are the key assumptions. Streaming memory needs incremental updates
and invalidation. Graph-shaped relationships need links beyond a tree. Exact
counts, exhaustive checks, and lossless transformations need direct source processing.

The current release builds **one static text index at a time**. Broader workloads
are extension directions; they have not been validated by benchmarks.
See [scope and assumptions](docs/architecture.md#scope-and-assumptions).

## Build the Index

<img src="assets/index-build.gif" alt="Ordered source chunks become leaves. Adjacent groups reduce into nodes with multiple summary topics, then into a root. Source and summary blocks receive embeddings." width="100%">

**Build upward, preserve the path downward.** A node is a structural container;
a block is an individually searchable piece of text inside it.

```text
Root: overview topics                         ← summary blocks + embeddings
├── Section: themes and conclusions            ← summary blocks + embeddings
│   ├── Passage-group summary                  ← intermediate levels as needed
│   │   ├── Source chunk                       ← exact text + embedding + offsets
│   │   └── Source chunk
│   └── …
└── Section: themes and conclusions
    └── …
```

1. Parse sections; split each into overlapping, budget-bounded source chunks.
2. Summarize adjacent groups into bounded topic blocks, then reduce upward.
3. Embed source and summary blocks; persist the tree, source spans, and input provenance.

Independent reductions run concurrently. A parent starts when **its own children**
are ready, allowing work to progress across levels without a whole-level barrier.
Embeddings are currently batched after summary construction.

Tree depth, section count, and topic counts depend on the input and budgets.
Summary provenance records the child input group; it is not claim-level attribution.
The default parser is standalone Markdown; LlamaIndex parsing is optional.

## Watch the Walk

<img src="assets/agent-walk.gif" alt="A question guides entry selection, inspection, upward or downward navigation, context compaction, and a cited answer on a persistent tree." width="100%">

**The tree is the memory. The walk is the investigation.**
One coordinating agent can decompose a question and explore independent branches
with concurrent tool actions. Each question shares a visited set across branches;
cached restoration lets evidence return to the prompt without another traversal.

| Tool | Purpose |
| :--- | :--- |
| `search` | Find distinct entry nodes using one query or several subqueries. |
| `move_up` | Follow parent links toward broader context. |
| `move_down` | Inspect finer detail through paginated child reads. |
| `compact_context` | Retain working notes and restore selected cached nodes. |
| `finish` | Return a cited answer or state the remaining evidence gap. |

The system directory includes all section-to-root topics by default. Those nodes
already count as read. An overview may cite these summaries directly; precise
answers require at least one read source-leaf citation. Result records distinguish
`source` from `summary` evidence. Citation validation checks references and scope;
semantic support still requires evaluation.

A full directory can grow beyond the model context. Full mode fails explicitly;
`--directory-mode budgeted --map-budget …` opts into a partial map. Tool results
and policy requests are budgeted as serialized messages. The default counter
uses UTF-8 bytes; calibrated model-token accounting needs a suitable tokenizer.

<sub>The animations are mechanism illustrations, not execution recordings or benchmark results. Node IDs and paths are illustrative; actions are optional.</sub>

[Static index](assets/index-structure.png) · [Navigation still](assets/agent-walk-poster.png) · [Regenerate visuals](scripts/render_visuals.py)

## Current Status

| Available | Still to build or validate |
| :--- | :--- |
| Markdown/TXT parsing, exact source spans, ordered recursive topic summaries | PDF/OCR, native conversation/code/corpus adapters |
| All-level embeddings, exact cosine search, atomic JSON persistence | ANN search, incremental updates, checkpoint/resume |
| Batched navigation, shared visit state, bounded prompts, evidence ledger and traces | Live-model summary fidelity, answer quality, and retrieval efficiency |
| Offline end-to-end example and local regression tests | Reproducible benchmarks and a real model execution recording |

The HTTP adapter supports compatible text chat and embedding endpoints, with
bounded transient retries and corrective summary regeneration. Compatibility
and quality must be checked with the selected service. Core runtime uses only
the Python standard library.

The next priority is **reproducible evaluation**: measure source-evidence
recall, citation support, cross-region answer completeness, indexing cost, latency,
and peak prompt size against flat retrieval and full-context prompting where it fits.
See the [evaluation plan](docs/architecture.md#evaluation-plan) and
[implementation review](docs/implementation-review.md).

## Related Work

[PageIndex](https://github.com/VectifyAI/PageIndex) explores vectorless,
reasoning-based retrieval over document trees.
[RAPTOR](https://arxiv.org/abs/2401.18059) recursively embeds, clusters, and
summarizes text for retrieval across abstraction levels.

StrataWalk builds on hierarchical retrieval with **source-ordered reduction,
embedded topics at every level, and an explicit navigation loop with bounded
working context**. Quality and efficiency comparisons remain open until benchmarked.

## Contribute a Difficult Question

A useful test case includes shareable source material, a question, the passages
needed to answer it, and a failure in the current workflow. Cross-section
comparisons, qualified conclusions, and evidence lost in summaries are especially
useful. [Open an issue](https://github.com/zhipuch/StrataWalk/issues).

[Architecture](docs/architecture.md) · [Usage](docs/usage.md) · [Code and extension points](docs/development.md)

---

**StrataWalk** · Long context. Navigable memory.

Maintained by [@zhipuch](https://github.com/zhipuch)
