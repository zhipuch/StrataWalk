# Reading and extending the code

The package uses a `src/` layout. Core code requires Python 3.9+ and the standard
library. Optional adapters import their dependencies only when selected.

## Repository map

```text
src/stratawalk/
├── models.py              # Node, Block, Section, TreeIndex; structural validation
├── tokenization.py        # Explicit budget units and exact source chunk spans
├── parsing.py             # Markdown chapters and optional LlamaIndex adapter
├── providers/
│   ├── base.py            # Small async model protocols
│   ├── offline.py         # Clearly labeled deterministic development fixtures
│   └── compatible.py      # HTTP model adapters and structured LLM summaries
├── index/
│   ├── builder.py         # Ordered bottom-up reduction and concurrent embedding
│   ├── storage.py         # Atomic versioned JSON save/load
│   └── search.py          # Exact cosine search across all levels
├── agent/
│   ├── prompts.py         # Agent instructions and five tool contracts
│   ├── tools.py           # Search, node navigation and bounded document map
│   └── runtime.py         # Model decisions, working context, citations, trace
└── cli.py                 # build / inspect / search / ask
examples/                  # Synthetic report and an executable offline example
tests/                     # Source integrity, index, tools, policy and transport checks
```

Suggested reading order: `models.py` → `index/builder.py` → `agent/tools.py`
→ `agent/runtime.py`. Provider adapters can be understood independently.

## Data semantics

A structural node has a parent and ordered children. It contains one or more
blocks. A leaf contains one exact source chunk. An upper node contains generated
summary/topic blocks, each with an embedding. `level` is subtree height, not
necessarily a globally balanced depth.

`source_block_ids` records immediate child blocks supplied to a summary call.
The first implementation conservatively records the whole input group for each
output paragraph. This is input provenance, **not precise claim-level attribution**.
Precise-answer citations refer to source leaves actually returned by tools,
with original character offsets. Overview answers may instead cite directory
or read summary blocks using explicit `answer_scope="overview"`; result records
label these as `evidence_type="summary"`, not original source quotations.

All source positions are zero-based Python character offsets, with an exclusive
end. They are not bytes, PDF page numbers, or token positions.

Each original section gets a chapter node, including a document preamble where
present. Long chapters reduce through intermediate summary nodes. Adjacent
chapter nodes then reduce to a root. Unary containers reuse existing blocks if
they already fit, avoiding unnecessary LLM calls. Root/chapter wrappers remain
explicit even for a single-section document.

## Construction and budgets

`BuildConfig` separates the input and output constraints:

- `max_children` caps structural fan-in; `reduction_input` caps combined input text.
- `summary_size` caps total output text; `max_topics` caps topic count.
- `topic_size` caps each topic and is limited by `embedding_limit`.
- Effective total output cap is `min(summary_size, max_topics * effective_topic_size)`.
- `context_limit` includes the complete serialized prompt, input block IDs/text,
  completion JSON reserve, corrective-feedback reserve and a safety margin.

The `ordered-topics-v2` prompt asks for core themes and claims, coherent standalone
topics, overlap deduplication, source language/order, and preservation of material
qualifications, negations and disagreements. LLM output is validated and can be
regenerated with bounded corrective feedback (`summary_retries`, default 2).
Malformed or overlong output is never silently truncated into a valid summary.
This enforces structure and budgets; semantic fidelity still needs real-model evaluation.

Construction is a dependency DAG, not a loop with whole-level barriers.
Contiguous groups are planned using source order and reserved output caps.
Every parent waits only for its own children, acquiring a shared request semaphore
**after** those children are ready. Other groups on that level need not finish.
The same applies across chapter boundaries: upper groups may start while unrelated
chapters are still reducing. Completion order never changes group membership.

Actual serialized requests are checked before dispatch. If a planned group is too
large after JSON/prompt overhead, contiguous halves reduce first. If even a pair
cannot fit, construction fails with a configuration error. Two reserved outputs
must fit the text budget so frontier node counts converge. On failure/cancellation,
pending sibling tasks are cancelled and awaited. Embedding batches run after the
completed tree; embedding is not currently pipelined with summarization.

Default units are UTF-8 bytes, a conservative approximation for byte-level
model tokenizers, **not a universal tokenizer guarantee**. Supply the actual
model tokenizer through the Python `Tokenizer` protocol, or `--encoding` for a
supported tiktoken encoding. If summary and embedding models use incompatible
tokenizers, implement an appropriate conservative shared counter or validate
against both in a custom builder. The CLI currently uses one counter for both.

## Agent behavior

`ChatPolicy` asks a model for JSON tool actions on each turn. It supports either
one action or a batch of independent `search`/`move_up`/`move_down` actions.
This is one coordinating agent with concurrent tool branches, not separate LLM
agents per starting node. `finish` and `compact_context` execute alone.

The default system message contains the **full deduplicated chapter-to-root
directory**, including all topic text in those nodes. It is not repeated in the
user message. `policy_messages()` is shared by inference and context accounting.
Full mode fails before a policy request if the directory cannot fit; an explicit
`directory_mode="budgeted"` and positive `map_budget` enables partial coverage.
No empirical directory-size claim is made: chapter count and topic lengths matter.

A search result selects up to `top_k` **distinct nodes**, not `top_k` blocks from
possibly one node. Multiple subqueries embed concurrently. A per-query session
shares visited state and a cache across all branches. Nodes in the system directory
are already read. Repeated node reads return `already_visited` references instead
of re-emitting text; known parents can still be expanded toward unread children.
Omitted nodes remain unvisited. A new question always creates a fresh session.

Tool results return whole nodes within an actual serialized budget, including
rankings and page metadata. A single node that cannot fit raises an actionable
error; reducing batching alone cannot solve an oversized individual node.
Pagination changes child ranges, not whether an already read child is reread.
Context compaction rehydrates cached nodes without retraversing the index.

The source-evidence ledger persists outside the active prompt. Each request
renders a bounded selection of recent observations and evidence. Notes are
working hypotheses. A node is not committed as visited if its result cannot
reach the next policy request. Citation validation checks known block IDs,
source offsets and answer scope; it cannot prove textual entailment.

The offline policy deliberately performs only search → finish and reports exact
excerpts. It is not evidence of autonomous reasoning quality. Scripted/model-adapter
fixtures exercise navigation, parallel branches, directory-only overview answers,
compaction, and shared visit deduplication.

## Extension points

- Implement `Embedder.embed(texts)` with a stable `name` for another embedding backend.
- Implement `summarize(blocks, budget)` for a different summarizer.
- Implement `ChatModel.complete(messages, max_tokens=...)` for a different model API.
- Implement `SectionParser.parse(text)` for other input structures, preserving exact offsets.
- Implement `policy.decide(state)` to change the agent decision mechanism.
- Replace `SemanticSearch` for ANN/vector database scale without changing the tree model.

On Python 3.9, the optional extra selects LlamaIndex 0.10/0.11 to avoid
newer transitive dependencies that use Python 3.10-only syntax. Python 3.10+
uses the newer release family.

The optional LlamaIndex adapter uses
[`MarkdownNodeParser`](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/file/markdown.py).
It maps the parsed text back onto the original document and fails explicitly
if source alignment is impossible. It does not silently rewrite the source.

## Development checks

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 examples/offline_demo.py
```

There are no live provider calls in these tests. Transport contracts use local
fixtures. Provider-specific live testing and retrieval-quality benchmarks are
still required. PDF/OCR, ANN search, checkpoint/resume, persistent model caching,
and a corpus-level index are outside the first implementation.
