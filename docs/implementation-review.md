# Implementation and scope review

## 2026-10-25: promotion readiness and budget boundaries

The project is suitable for an early technical preview, with implementation
claims separated from unmeasured semantic quality and end-to-end performance.
See [the launch review and draft announcement](launch-readiness.md).

Two reproduced boundary failures were fixed:

- Corrective summary feedback can consume more counter units than repetitive
  planning filler. Each actual request is now checked before model dispatch,
  including retries; a compressed-counter regression verifies that an over-budget
  second request is never sent.
- Compaction previously demanded new-read workspace before it could clear notes.
  Read budgeting now applies to navigation and cache restoration, with restoration
  using the proposed notes. A tight-context regression clears 1,200 units of notes
  successfully while keeping every rendered policy request within its budget.

The shared response-budget helper keeps these rules in one place. No broad
runtime rewrite was needed. Local regression results are 65 passing tests and
one skipped optional LlamaIndex integration; remote CI status and live-model
quality have not been established by this review.

## 2026-10-21: user workflow and exact search

This pass follows a first-time user's path: understand the purpose, run a demo,
configure models, reuse an index, read results, and recover from failed inputs.

| Finding | Change |
| --- | --- |
| The first own-material example used a scripted offline policy for a comparison question | README separates the offline trial from model-driven questions and shows two queries reusing one index |
| Users had to infer mode and answer scope from other fields | JSON results include `provider` and `answer_scope`; usage explains statuses, citation types and recovery steps |
| Malformed index files raised uncaught data-shape errors | Loader reports the index name and a rebuild instruction; validation checks primitive types and walks iteratively |
| Vector norm products overflowed/underflowed for valid finite values | Stable norm/scaling handles large and small values; malformed or zero query vectors fail explicitly |
| Every query revalidated/renormalized all vectors and sorted all hits | Cache scalar statistics once, normalize the query once, select Top-k without a full sort, and skip embedding when no candidates remain |
| Output/trace paths could replace an input file | Reject identical paths, symlink targets and hard-linked aliases |
| Failed offline retrieval repeated until the turn budget expired | Return an explicit insufficient result after the unsuccessful attempt |
| Embedding responses accepted Boolean/float indices or overflowed on oversized integers | Validate row types, integer indices and representable finite vector values |

`scripts/benchmark_search.py` provides a reproducible local microbenchmark with
4,000 synthetic blocks, 128 dimensions, seven queries, and Top-5 comparison.
On this machine, a sample run reported 104.1 ms median for the exhaustive
reference and 36.6 ms for the current query path, plus 81.0 ms one-time setup.
The mean query time including setup over seven queries was 49.3 ms. Top-5 IDs
and scores agreed with the exhaustive reference on that fixture.

These timings exclude index loading, model/network calls and agent execution.
They establish a local repeated-query improvement, with a setup cost that matters
for one-off queries. Exact search still scans eligible vectors. Broad live-model
quality, cost and latency claims remain unvalidated.

Regression coverage includes corruption/type errors, extreme vectors, exact
ranking and filters, deep trees, path collisions, result labels, and prompt/tool
contracts. The optional LlamaIndex integration requires its extra to be installed.

## Long-context positioning

StrataWalk's reusable method is an ordered hierarchy over source text, searchable
abstractions, and an agent that changes reading scale within a bounded prompt.
The current implementation covers one static Markdown/TXT snapshot. Broader
long-context workloads need adapters and task-specific evaluation; universal
applicability would be an unsupported claim.

The README now leads with this mechanism, separates implemented support from
extension directions, and describes the distinctive combination without making
unmeasured quality or speed claims. Related-work descriptions are linked to
[PageIndex's repository](https://github.com/VectifyAI/PageIndex) and the
[RAPTOR paper](https://arxiv.org/abs/2401.18059).

## Robustness fixes in this review

| Finding | Resolution | Verification |
| --- | --- | --- |
| Chunking repeatedly copied and counted the remaining source suffix, causing near-quadratic counter work at fixed chunk size | Local expanding probes find each boundary without scanning the suffix | Counter-work scaling regression plus compressed-counter and Unicode cases |
| An empty custom parser result could leave reduction planning looping forever; invalid spans failed only after model work | Validate nonempty sections, IDs, source order and complete coverage before scheduling | Invalid adapter fixtures fail before any summary call |
| CLI text reading normalized CRLF, changing the stored text and source offsets | Preserve decoded line endings | Build/load regression compares original Unicode CRLF text and leaf spans |
| Local HTTP validation used a string prefix and accepted lookalike remote hosts | Parse scheme/hostname; accept exact local hosts; reject URL credentials/query/fragment | Endpoint acceptance/rejection fixtures, including IPv6 loopback |
| Architecture described partial maps, verified claims, and latency limits more strongly than implemented | Align directory, evidence and budget descriptions with runtime | Documentation checked against prompts, tools, runtime and CLI |

The chunking regression measures work submitted to a deterministic counter.
It establishes the removal of repeated suffix scans, not end-to-end model
indexing speed. Network/model latency may dominate live runs.

## Next optimization priorities

| Priority | Work | Why it matters |
| --- | --- | --- |
| P1 | A reproducible live-model evaluation set with expected source spans | Distinguish reference validity from factual support, summary faithfulness, and answer completeness |
| P1 | Compare flat retrieval, all-level retrieval, navigated retrieval, and full-context prompting under recorded budgets | Establish where the design pays for preprocessing and extra tool turns |
| P1 | Measure full-directory growth, tool workspace and host-memory use on long inputs | A bounded prompt and compact root do not guarantee bounded directory or host memory |
| P2 | Incremental builds, stable versioned identities and resumable construction | Required for practical evolving conversation/trace memory and costly builds |
| P2 | Source adapters and per-source metadata, followed by graph links where needed | Make broader context types useful without losing provenance |
| P2 | ANN search and lighter persistence when scale measurements justify them | Norm caching is implemented; exact search still scans eligible blocks, and JSON/in-memory caches remain first-version choices |

Evaluation should include distant evidence, conflicting statements, exact facts,
irrelevant lexical matches, and deliberately unanswerable questions. For broader
context types, add temporal supersession, cross-file dependencies, and exhaustive
tasks to establish fit and failure boundaries.

## Index construction and query contracts

This review records the implementation changes made against the intended
algorithm. Tests below establish engineering behaviors. Live-model semantic
accuracy and end-to-end performance remain unmeasured.

| Requirement | Earlier implementation | Current behavior |
| --- | --- | --- |
| Extract core topics | Generic summary prompt | Versioned topic-extraction prompt with abstraction/fidelity rules |
| Configure output topics | Combined length only | Topic count, per-topic length and total length enforced |
| Robust model output | First malformed/overlong result failed | Bounded corrective regeneration with exact validation |
| Model context | Late serialized-request check | Full request reserve check; smaller contiguous reductions when necessary |
| Pipeline within chapters | Whole-level gather barrier | Each parent awaits only its own contiguous child group |
| Pipeline above chapters | Wait for all chapters | Ready chapter groups reduce while other chapters are unfinished |
| Preserve document order | Ordered grouping | Group membership independent of request completion order |
| Directory in system | Partial map in user state | Full chapter-to-root nodes/topics in system by default |
| Macro questions | Source-only finish requirement | Explicit overview scope can cite directory summaries directly |
| Multiple entry nodes | Top blocks could share a node | Search selects distinct nodes; concurrent subqueries supported |
| Parallel walking | One tool action per model turn | Independent navigation/search actions can run in one batch |
| No repeat visits | Repeated action-string check | Per-query shared visited set plus cache, including directory nodes |
| Bidirectional navigation | Parent and children stored | Links retained, validated, and covered by corruption tests |

## What the scheduling tests prove

One test deliberately blocks a same-level group until an unrelated upper group
has started. A layer-barrier implementation deadlocks this test. A second test
blocks a chapter while an already-ready pair of other chapter nodes reduces
above it. Both use events, not timing-based speed thresholds.

Concurrency is limited only around actual model requests. Tasks waiting on
children do not consume request slots. Failed dependencies cancel sibling work.
Input and summary embeddings are currently batched after the tree is complete;
this stage is not yet overlapped with summarization.

## Query interpretation

Parallel exploration uses one coordinating agent issuing independent read
actions. It does not create a separate LLM agent per branch. Session-level node
reads and evidence are deduplicated across branches. Expanding a known parent
toward an unread child is allowed; rereading the known parent's content is skipped.
Cached context restoration is allowed and is not another tree traversal.

Directory nodes are already present in the system message and count as read.
For an overview, the policy may finish with summary citations. For precise facts,
the default source answer scope requires original leaf evidence. Citation types
remain visible so generated abstraction is not presented as an original quote.

## Explicit assumptions and remaining evaluation

- Full directory size is data-dependent. Chapters alone contribute linearly;
  exponential convergence above them does not guarantee a small system prompt.
  Full mode fails on overflow; partial mode requires explicit opt-in.
- Default UTF-8 byte accounting is conservative for byte-level tokenizers, not
  a universal model guarantee. Use the chosen providers' actual tokenizers for
  calibrated production budgets. The CLI currently uses one counter.
- Topic/input provenance records the child input group, not exact claim-level
  alignment. Precise statements should be checked against original leaves.
- Prompt tests check schema/instructions/retry behavior. They do not establish
  semantic faithfulness. Real long documents and selected models are needed
  to measure summary omissions, conflicts, question coverage and answer quality.
- Bounded tasks and retries improve failure handling; cancelling a coroutine
  cannot necessarily terminate an HTTP request already running in a worker thread.
