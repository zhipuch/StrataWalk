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
Agent citations instead refer to source leaf blocks that were actually returned
by tools, with original character offsets and the exact delivered excerpt.

All source positions are zero-based Python character offsets, with an exclusive
end. They are not bytes, PDF page numbers, or token positions.

Each original section gets a chapter node, including a document preamble where
present. Long chapters reduce through intermediate summary nodes. Adjacent
chapter nodes then reduce to a root. Unary containers reuse existing blocks if
they already fit, avoiding unnecessary LLM calls. Root/chapter wrappers remain
explicit even for a single-section document.

## Construction and budgets

`BuildConfig` controls source chunk size/overlap, embedding input limit,
reduction input, summary output size, total summarizer context, group fanout,
request concurrency, and embedding batch size.

Two source chunks or two summaries must fit the reduction input. Ordered greedy
groups therefore reduce the number of frontier nodes on every nontrivial round.
Summary outputs are validated against their budget; an overlong result fails
explicitly rather than silently discarding information. The full serialized LLM
request is checked with output space and a safety reserve before dispatch.

Independent chapter/group requests share one concurrency semaphore. Parent
summaries wait for children. Embeddings for all blocks are batched after tree
construction. No partial index file is published on a failed build.

Default units are UTF-8 bytes, a conservative approximation for byte-level
model tokenizers, **not a universal tokenizer guarantee**. Supply the actual
model tokenizer through the Python `Tokenizer` protocol, or `--encoding` for a
supported tiktoken encoding. If summary and embedding models use incompatible
tokenizers, implement an appropriate conservative shared counter or validate
against both in a custom builder. The CLI currently uses one counter for both.

## Agent behavior

`ChatPolicy` asks a model for a JSON tool action on each turn. This intentionally
small provider contract does not require vendor-specific native function calling.
The runtime dispatches five tools, validates input/citations, records results,
limits steps, and rejects repeatedly identical actions.

The document map includes a budgeted root overview, chapter descriptors and
summaries, and deduplicated ancestor summaries. Large maps are partial; the
agent can use the root's paginated children or search to reach omitted chapters.

The persistent evidence ledger lives outside the LLM context. Each request
renders a bounded selection of evidence and recent observations. The explicit
compaction tool updates working notes and drops old observations while retaining
source references. Notes are model-generated hypotheses; they are not verified
facts. Context accounting includes serialized messages and output reserves.

Navigation is a batched in-memory read, so independent node requests do not
require expensive model calls of their own. The policy chooses subsequent moves.
The offline policy deliberately performs only search → finish and reports exact
excerpts; it is not a demonstration of autonomous LLM reasoning. Tests use a
scripted policy to exercise both directions and context compaction.

Citation validation proves that cited excerpts were retrieved and have valid
source offsets. It cannot prove that the answer is entailed by those excerpts.
That requires evaluation or an additional verification stage.

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
