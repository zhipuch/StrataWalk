# Implementation and scope review

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
| P2 | ANN search, lighter persistence and cached vector norms when scale measurements justify them | Exact search scans all blocks; JSON and in-memory node caches are first-version choices |

Evaluation should include distant evidence, conflicting statements, exact facts,
irrelevant lexical matches, and deliberately unanswerable questions. For broader
context types, add temporal supersession, cross-file dependencies, and exhaustive
tasks to establish fit and failure boundaries.

## Index construction and query contracts

This review records the implementation changes made against the intended
algorithm. Tests establish engineering behaviors; no real-model semantic
accuracy or speed advantage is claimed.

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
