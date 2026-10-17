"""Exact cosine search over every block; replace this module for ANN scale."""
import math
from dataclasses import dataclass
from typing import List
from ..models import TreeIndex


@dataclass
class SearchHit:
    node_id: str
    block_id: str
    score: float
    level: int
    kind: str
    start: int
    end: int
    text: str


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("Query and index embedding dimensions differ")
    if not all(math.isfinite(v) for v in left + right):
        raise ValueError("Embedding contains nonfinite values")
    norm = math.sqrt(sum(v * v for v in left) * sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right)) / norm if norm else 0.0


class SemanticSearch:
    def __init__(self, index: TreeIndex, embedder):
        self.index, self.embedder = index, embedder
        if index.metadata.get("embedder") != embedder.name:
            raise ValueError("Use the same embedding provider/model as index construction")

    async def search(self, query, top_k=5, kind=None, min_level=None, max_level=None,
                     *, unique_nodes=False, exclude_nodes=None) -> List[SearchHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k must be 1..50")
        if kind is not None and kind not in {"leaf", "summary", "chapter", "root"}:
            raise ValueError("Unknown node kind")
        if min_level is not None and (not isinstance(min_level, int) or min_level < 0):
            raise ValueError("Invalid min_level")
        if max_level is not None and (not isinstance(max_level, int) or max_level < 0):
            raise ValueError("Invalid max_level")
        if min_level is not None and max_level is not None and min_level > max_level:
            raise ValueError("min_level exceeds max_level")
        vector = (await self.embedder.embed([query]))[0]
        hits = []
        for node in self.index.nodes.values():
            if exclude_nodes and node.id in exclude_nodes:
                continue
            if kind and node.kind != kind:
                continue
            if min_level is not None and node.level < min_level:
                continue
            if max_level is not None and node.level > max_level:
                continue
            for block in node.blocks:
                hits.append(SearchHit(node.id, block.id, cosine(vector, block.embedding),
                                      node.level, node.kind, node.start, node.end, block.text))
        ranked = sorted(hits, key=lambda h: (-h.score, h.start, h.node_id, h.block_id))
        if not unique_nodes:
            return ranked[:top_k]
        seen, selected = set(), []
        for hit in ranked:
            if hit.node_id not in seen:
                selected.append(hit)
                seen.add(hit.node_id)
                if len(selected) == top_k:
                    break
        return selected
