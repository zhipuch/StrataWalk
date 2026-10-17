# Index construction and query contract review

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
