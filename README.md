<div align="center">

<img src="assets/hero.png" alt="StrataWalk — Long documents. Navigable memory. Ordered summary trees, multi-scale search, and agentic navigation." width="100%">

### Hierarchical memory for long-document agents

**Zoom out for perspective. Zoom in for evidence.**

[Watch the Walk](#watch-the-walk) · [How It Works](#how-it-works) · [Architecture](docs/architecture.md) · [Roadmap](#roadmap)

<sub>🚧 Design preview · Implementation and benchmarks forthcoming</sub>

</div>

---

A passage tells you **what happened**. A chapter explains **why**.
The whole document reveals **how the argument fits together**.

**StrataWalk gives agents a way to move between these scales.**
It builds an ordered hierarchy from source passages to a document overview,
then lets an agent search, explore, and return to the original evidence.

## Watch the Walk

<img src="assets/agent-walk.gif" alt="Concept animation: source chunks form a summary tree; an agent searches a chapter, moves up for context, then descends into memory and quality evidence to answer with source references." width="100%">

<sub>Looping mechanism illustration with a synthetic report. This is not a live execution recording or a benchmark result.</sub>

**Example question:** “What improved quality, and at what trade-off?”

The illustration follows a search into the results chapter, a move upward to
recover context, and a descent into two evidence branches. In this synthetic
fixture, reranking improves answer quality while requiring more memory.

[View the still image](assets/agent-walk-poster.png) · [Inspect or regenerate the animation](scripts/render_visuals.py)

## How It Works

| 01 · Build memory | 02 · Find a starting point | 03 · Follow the evidence |
| :--- | :--- | :--- |
| Split sections into overlapping source passages. Recursively summarize adjacent groups into higher-level nodes. | Search embeddings of source passages and summary blocks, or begin with a compact document map. | Move upward for context and downward for detail. Gather evidence across branches and answer with citations. |

### One document. Multiple reading scales.

```text
Document overview                  ← global orientation
├── Chapter summary                ← arguments and themes
│   ├── Local summary              ← focused context
│   │   ├── Source passage         ← original evidence
│   │   └── Source passage
│   └── ...
└── Chapter summary
    └── ...
```

**Build upward.** LlamaIndex-based processing establishes source sections.
Token-bounded passages become leaves. Adjacent groups are summarized into
nodes containing individually searchable topic blocks, then reduced again
until they fit a compact root budget.

**Explore in either direction.** The agent starts at a useful scale, reads,
identifies what is missing, and selects its next action. Search remains
available throughout the walk.

**Keep memory outside the context window.** The persistent tree stores the
document. A bounded workspace and evidence ledger hold the current investigation,
source references, and unresolved questions.

## The Agent's Toolkit

| Tool | When the agent needs it |
| :--- | :--- |
| `search` | “Find another relevant region or a better entry point.” |
| `move_up` | “I need the broader context around this detail.” |
| `move_down` | “Show me the supporting passages.” |
| `compact_context` | “Keep the findings and citations; make room to continue.” |
| `finish` | “The evidence supports an answer—or the remaining gap must be stated.” |

*Proposed tool contracts, not released API signatures.*

## Why This Design?

- **Preserve the document's progression.** Adjacent regions are reduced in source order.
- **Make every scale searchable.** Embed original passages and generated summary blocks.
- **Connect perspective to proof.** Summary blocks retain links to supporting children.
- **Let the question guide the walk.** Begin at the overview, a chapter, or a source passage.
- **Build through concurrent work.** Independent groups can be summarized in parallel;
  parents are scheduled after their children become ready.

Summaries guide exploration. Specific facts, figures, and quotations should
be verified against source text. Indexing speed, retrieval quality, and cost
remain targets for reproducible evaluation.

## Questions Worth Exploring

| Question | Reading behavior |
| :--- | :--- |
| “What is the central argument?” | Start with the overview; inspect the major themes. |
| “Which experiments support this conclusion?” | Follow the conclusion down to results and limitations. |
| “How do these chapters disagree?” | Compare source evidence across separate branches. |
| “Where is this number justified?” | Locate the passage and verify its surrounding context. |

## Roadmap

- [ ] **Build the memory:** parsing, ordered recursive summaries, embeddings, persistent tree links.
- [ ] **Enable the walk:** search, batched navigation, context compaction, evidence tracking.
- [ ] **Show it working:** runnable example, real execution recording, source-grounded answers.
- [ ] **Measure it:** indexing cost and latency, evidence recall, answer quality, and ablations.

This repository currently publishes the design and explanatory visuals.
Installation instructions and runnable examples will accompany the implementation.

## Related Work

[PageIndex](https://github.com/VectifyAI/PageIndex) explores reasoning-based
retrieval over document trees. [RAPTOR](https://arxiv.org/abs/2401.18059)
develops recursive embedding, clustering, and summarization for hierarchical
retrieval. StrataWalk explores **source-ordered reduction, multi-scale semantic
entry points, and agent-directed navigation with explicit context management**.

See the [detailed architecture](docs/architecture.md) for token budgets,
node/block structure, provenance, and evaluation plans.

## Help Shape StrataWalk

Have a long-document question that your current retrieval workflow struggles with?
[Open an issue](https://github.com/zhipuch/StrataWalk/issues) with a shareable
example, expected evidence, and the failure you observed.

---

<div align="center">

**Give agents a map, a memory, and a way to explore.**

Created by [zhipuch](https://github.com/zhipuch)

</div>
