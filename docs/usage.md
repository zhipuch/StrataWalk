# Running StrataWalk

Python 3.9+ is required. Commands below run from the repository root.

## Offline: no account or API key

```bash
PYTHONPATH=src python3 examples/offline_demo.py
```

The example builds `.stratawalk/example.json`, retrieves source passages and
prints their source references. It uses extractive summaries, stable hashed
word vectors, and a scripted search → finish policy. It verifies plumbing;
it does not establish semantic retrieval quality or autonomous reasoning.

Or use the CLI directly:

```bash
PYTHONPATH=src python3 -m stratawalk build examples/report.md --output .stratawalk/report.json
PYTHONPATH=src python3 -m stratawalk inspect .stratawalk/report.json
PYTHONPATH=src python3 -m stratawalk search .stratawalk/report.json 'reranking memory' --kind leaf
PYTHONPATH=src python3 -m stratawalk ask .stratawalk/report.json 'What improved quality and at what cost?' --trace .stratawalk/walk.json
```

For a standard editable install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
stratawalk --help
```

The core runtime has no third-party dependencies. Editable installation may
need network access for the setuptools build dependency.

## Real LLM and embedding endpoints

From a cloned checkout, use `PYTHONPATH=src python3 -m stratawalk` in place of
`stratawalk` below, or install the CLI with the editable-install commands above.

The `compatible` adapter supports the text-based `/chat/completions` and
`/embeddings` HTTP interfaces. Set a base URL that already includes the API
version prefix. Models must support text chat and JSON-formatted responses
when prompted; native tool calling is not required. Not every provider exposes
the same parameters, so compatibility must be checked with the chosen service.

```bash
export STRATAWALK_BASE_URL='https://your-provider.example/v1'
export STRATAWALK_CHAT_MODEL='your-chat-model'
export STRATAWALK_EMBEDDING_MODEL='your-embedding-model'
# Read the API key without putting it into shell history (zsh/bash):
read -rs STRATAWALK_API_KEY
export STRATAWALK_API_KEY
```

Then build and ask using the same embedding model:

```bash
stratawalk build examples/report.md --provider compatible --output .stratawalk/live.json
stratawalk ask .stratawalk/live.json 'What improved quality and at what cost?' --provider compatible --trace .stratawalk/live-walk.json
```

The live mode uses LLM summaries and model-selected tool actions. It refuses
query-time embedding providers that differ from those recorded in the index.
Chat models can differ between construction and answering: pass `--chat-model`
on either command. Different chat and embedding endpoints can be assembled
through the Python API using separate `CompatibleClient` instances.

The API key is not saved to the index or trace. Index files contain source text;
trace files contain retrieved excerpts and generated responses.

## Token budgets

The default counter uses UTF-8 bytes, not a model tokenizer. Configuration
values are measured in that counter's units. For calibrated counting:

```bash
python -m pip install -e '.[tokenizer]'
stratawalk build examples/report.md --provider compatible --encoding cl100k_base --output .stratawalk/live.json
stratawalk ask .stratawalk/live.json 'Summarize the trade-off' --provider compatible --encoding cl100k_base
```

Use an encoding appropriate to your actual model; `cl100k_base` is only an
example. See [development notes](development.md) for multi-tokenizer limits.

Useful build flags:

| Flag | Default | Meaning |
| --- | ---: | --- |
| `--chunk-size` | 768 | Maximum source chunk size in counter units |
| `--chunk-overlap` | 96 | Adjacent chunk overlap budget |
| `--embedding-limit` | 1024 | Maximum block size sent for embedding |
| `--reduction-input` | 4096 | Total input block text per summary group |
| `--summary-size` | 512 | Maximum combined output block text |
| `--max-topics` | 6 | Maximum topic blocks in one parent |
| `--topic-size` | 256 | Maximum text per topic, capped by embedding limit |
| `--summary-retries` | 2 | Corrective retries after invalid LLM output |
| `--context-limit` | 16384 | Summary model context budget including reserves |
| `--concurrency` | 4 | Maximum simultaneous model/embedding requests |
| `--max-children` | 8 | Maximum children grouped in one reduction |

LLM summaries are validated for JSON schema, topic count, total length and
per-topic length. Invalid results trigger up to `--summary-retries` corrective
regenerations, then fail explicitly. Full prompt/input/output reserves are
checked before each call. Overfull groups are reduced in smaller contiguous
subgroups; a pair that cannot fit requires smaller chunks/summaries or a larger
context. Transient HTTP 429 and selected 5xx responses have separate retries.

For `ask`, `--context-limit` defaults to 24000 and `--output-reserve` to 2048.
`--max-steps` bounds policy turns; each turn can issue up to `--parallel-actions`
independent read actions (default 4). Source citations and summary citations are
explicitly distinguished in JSON and CLI output. `--json` returns `answer`,
`citations`, `status`, `answer_scope`, and `provider`. The build confirmation also
identifies an offline demo or model-built index.

### Understanding answers

| Field/value | Meaning |
| --- | --- |
| `status: complete` | The finish action passed reference and answer-scope checks. Factual correctness and complete claim support still need evaluation. |
| `status: insufficient` | The policy reports that evidence is insufficient. Read the answer for the gap or suggested next step. |
| `status: budget_exhausted` | No supported finish was produced within the policy-turn limit. |
| `answer_scope: source` | A completed answer cites at least one read original source block. |
| `answer_scope: overview` | The answer may cite only summary topics; source leaves need not have been read. |
| `answer_scope: null` | Exploration ended without a finish action. |
| `provider: offline` | A scripted demo returns source excerpts using lexical search. |
| `provider: compatible` | Your configured models generate summaries and/or choose query actions. |

Each citation carries the text, source name, character span, and an
`evidence_type` of `source` or `summary`. For a source citation, `start:end`
identifies the exact passage in the indexed snapshot. A summary citation's span
identifies the region summarized; its text is generated abstraction.

`--trace .stratawalk/walk.json` saves navigation actions and tool results for
inspection. Choose a different path from the index. The CLI also rejects an
index output path that would replace its source document.

### System directory and visit deduplication

By default, the system prompt includes every chapter node and its ancestors,
with all their topic text. These nodes count as read. Their contents can support
an overview directly; a precise answer still requires source evidence.

The default `--directory-mode full --map-budget 0` never silently drops directory
nodes. The model context remains the hard limit. If the directory is too large,
choose a larger context or deliberately opt into a partial directory:

```bash
stratawalk ask .stratawalk/report.json 'Compare the conclusions' \
  --directory-mode budgeted --map-budget 3000
```

Partial mode explicitly reports omissions and retains node IDs for navigation.
Actual directory size depends on chapter count and topic lengths; upper-level
geometric reduction alone is not proof that the full directory always fits.

Embedding search selects distinct unvisited entry nodes. The policy can search
several subquestions and batch independent up/down moves; a shared per-question
visited set prevents duplicate node reads. Compaction restores cached content
without another traversal. Omitted nodes can be requested in a narrower batch.
Use `--tool-response-budget` (default 4096) for larger individual nodes, while
also providing sufficient total context. Metadata counts toward this budget.

CLI exit codes: 0 for success; 1 for invalid inputs/provider failure; 2 for
insufficient evidence or an exhausted agent budget.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `stratawalk: command not found` | From the repository root, use `PYTHONPATH=src python3 -m stratawalk`, or install with `python -m pip install -e .`. |
| Embedding provider/model differs from the index | Use the same `--provider`, base URL and embedding model as construction. Rebuild when switching from offline fixtures to real embeddings. |
| Invalid index file | Restore a known-good copy or rebuild from the original source with `build`. Malformed schemas and field types produce an error with the index name. |
| Full directory/question/notes exceed context | Increase `--context-limit` within your model's capacity, or explicitly add `--directory-mode budgeted --map-budget 3000` to the same ask command. |
| A node exceeds the tool response budget | Increase `--tool-response-budget` and allow enough total context; smaller batches alone cannot fit an oversized node. Alternatively rebuild with smaller chunk/topic budgets. |
| Offline demo could not retrieve excerpts | Try a descriptive question and check the index and tool budget. Offline mode stops with `insufficient` after an unsuccessful attempt. |
| Query embedding has zero magnitude | For direct search, use meaningful words rather than punctuation; check a custom embedder if substantive text also produces zero vectors. |
| Unsupported input format | Convert the material to UTF-8 Markdown/TXT first. Native PDF, OCR, image and code-aware adapters are not implemented. |

Keep `--provider compatible` and your model settings on live commands when adding
budget flags. Budget numbers use the selected counter: UTF-8 bytes by default.

## LlamaIndex section parsing

```bash
python -m pip install -e '.[llamaindex]'
stratawalk build examples/report.md --parser llamaindex --output .stratawalk/llamaindex.json
```

The default standalone parser groups Markdown H2 sections (or H1 when H2 is
absent). It retains preambles and ignores fenced-code headings.
`--heading-level` selects another depth. LlamaIndex uses its own Markdown header
boundaries; parser choice is explicit. Plain UTF-8 TXT is treated as one section
when no headings exist. This version does not parse PDF, scanned pages or images.

The CLI preserves decoded source text including CRLF line endings. Citation
positions are zero-based Python character offsets with an exclusive end, referring
to the source snapshot stored in the index. Editing the file requires rebuilding;
the existing index continues to refer to its original snapshot.

Transcripts, notes, or traces may be supplied as a Markdown/TXT snapshot. Each
index still has one source identity. Native turn metadata, multi-file references,
and incremental updates require additional adapters and schema support. See
[scope and assumptions](architecture.md#scope-and-assumptions).
