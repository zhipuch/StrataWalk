# Search Quality Evaluation — Synthetic Fixture

This is a deliberately synthetic report used to demonstrate StrataWalk's
index structure and source navigation. These are not real experimental results.

## Baseline

The baseline system retrieves passages using a lexical index. It uses one
retrieval pass and retains five candidate passages. Its main limitation is that
matching terms may occur in passages that do not answer the question.

## Reranking Experiment

The experimental pipeline adds a reranking stage after candidate retrieval.
The reranker compares the question against each candidate passage before
selecting the final context. In this synthetic fixture, reranking improves
answer quality by prioritizing passages that directly support an answer.

The improvement has a trade-off: keeping a larger candidate pool and running
the reranker require additional memory. The report does not provide numeric
quality scores or memory measurements, so no percentage gain can be inferred.

## Limitations

The example concerns one synthetic workload. It does not establish that
reranking always improves quality or that its cost is acceptable in every
application. A production evaluation should measure answer correctness,
source recall, latency, and peak memory on representative documents.
