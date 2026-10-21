"""Local exact-search microbenchmark; no model calls or quality claims.

Run from the repo root: PYTHONPATH=src python3 scripts/benchmark_search.py
"""
import argparse
import asyncio
import hashlib
import json
import math
import random
import statistics
import time

from stratawalk.index.search import SearchHit, SemanticSearch
from stratawalk.models import Block, Node, Section, TreeIndex


def fixture(blocks, dimensions):
    rng = random.Random(42)
    leaf_count = blocks - 2
    source, nodes = "x" * leaf_count, {}
    chapter_id, root_id = "chapter", "root"

    def vector():
        return [rng.uniform(-1, 1) for _ in range(dimensions)]

    for number in range(leaf_count):
        node_id = "n%06d" % number
        nodes[node_id] = Node(node_id, "leaf", 0, number, number + 1, "s0",
                              [Block(node_id + ":b0", "x", vector())], parent=chapter_id)
    children = list(nodes)
    nodes[chapter_id] = Node(chapter_id, "chapter", 1, 0, len(source), "s0",
                             [Block("chapter:b0", "Synthetic summary", vector(),
                                    [nodes[node_id].blocks[0].id for node_id in children])],
                             children, root_id)
    nodes[root_id] = Node(root_id, "root", 2, 0, len(source), None,
                          [Block("root:b0", "Synthetic overview", vector(), ["chapter:b0"])], [chapter_id])
    index = TreeIndex(hashlib.sha256(source.encode()).hexdigest(), "synthetic.txt", source, root_id,
                      nodes, [Section("s0", "Synthetic", 0, len(source))], {"embedder": "fixture"})
    index.validate()
    return index, vector()


def exhaustive_reference(index, query, top_k):
    """Previous full-sort path, for ordinary finite fixture vectors only."""
    hits = []
    for node in index.nodes.values():
        for block in node.blocks:
            vector = block.embedding
            if not all(math.isfinite(v) for v in query + vector):
                raise ValueError("Invalid fixture")
            norm = math.sqrt(sum(v * v for v in query) * sum(v * v for v in vector))
            score = sum(a * b for a, b in zip(query, vector)) / norm if norm else 0
            hits.append(SearchHit(node.id, block.id, score, node.level, node.kind,
                                  node.start, node.end, block.text))
    return sorted(hits, key=lambda hit: (-hit.score, hit.start, hit.node_id, hit.block_id))[:top_k]


async def run(args):
    index, query = fixture(args.blocks, args.dimensions)

    class Embedder:
        name = "fixture"

        async def embed(self, texts):
            return [query[:] for _ in texts]

    started = time.perf_counter()
    search = SemanticSearch(index, Embedder())
    setup = time.perf_counter() - started
    reference_times, current_times = [], []
    for _ in range(args.queries):
        started = time.perf_counter()
        expected = exhaustive_reference(index, query, args.top_k)
        reference_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        actual = await search.search("synthetic query", args.top_k)
        current_times.append(time.perf_counter() - started)
        if [hit.block_id for hit in actual] != [hit.block_id for hit in expected]:
            raise RuntimeError("Top-k identities differ from exhaustive reference")
        if any(not math.isclose(a.score, b.score, abs_tol=1e-12) for a, b in zip(actual, expected)):
            raise RuntimeError("Scores differ from exhaustive reference")
    print(json.dumps({
        "benchmark": "local synthetic exact search; no model/network I/O",
        "blocks": args.blocks, "dimensions": args.dimensions, "queries": args.queries,
        "top_k": args.top_k, "ranking_agrees": True,
        "setup_ms": round(setup * 1000, 3),
        "reference_median_query_ms": round(statistics.median(reference_times) * 1000, 3),
        "current_median_query_ms": round(statistics.median(current_times) * 1000, 3),
        "current_ms_per_query_including_setup": round((setup + sum(current_times)) / args.queries * 1000, 3),
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, default=4000)
    parser.add_argument("--dimensions", type=int, default=128)
    parser.add_argument("--queries", type=int, default=7)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.blocks < 3 or min(args.dimensions, args.queries) < 1 or not 1 <= args.top_k <= 50:
        parser.error("Require blocks >= 3, positive dimensions/queries, and top-k in 1..50")
    asyncio.run(run(args))
