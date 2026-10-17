"""Tree reads and per-query navigation sessions, distinct from persistent storage."""
import asyncio
from dataclasses import dataclass, field
import json
from ..tokenization import ByteTokenizer


@dataclass
class TraversalState:
    visited: set = field(default_factory=set)
    cache: dict = field(default_factory=dict)
    order: list = field(default_factory=list)


class TreeTools:
    def __init__(self, index, search, *, tokenizer=None, response_budget=4096, session=None):
        self.index, self.search_engine = index, search
        self.tokenizer = tokenizer or ByteTokenizer()
        if response_budget < 512:
            raise ValueError("Tool response budget must be >= 512")
        self.response_budget, self.session = response_budget, session

    def _ids(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(not isinstance(i, str) for i in ids):
            raise ValueError("node_ids must contain 1..10 node IDs")
        ids = list(dict.fromkeys(ids))
        if any(i not in self.index.nodes for i in ids):
            raise ValueError("Unknown node ID")
        return ids

    def _record(self, node_id):
        node = self.index.nodes[node_id]
        record = {"node_id": node.id, "kind": node.kind, "level": node.level,
                  "parent": node.parent, "child_count": len(node.children),
                  "start": node.start, "end": node.end, "blocks": []}
        for block in node.blocks:
            row = {"block_id": block.id, "text": block.text, "truncated": False}
            if node.kind == "leaf":
                row.update(source_name=self.index.source_name, start=node.start, end=node.end)
            record["blocks"].append(row)
        return record

    def new_session(self, directory):
        """Independent questions never share visited sets or mutable caches."""
        state = TraversalState()
        for record in directory["nodes"]:
            node_id = record["node_id"]
            state.visited.add(node_id)
            state.order.append(node_id)
            state.cache[node_id] = self._record(node_id)
        return TreeTools(self.index, self.search_engine, tokenizer=self.tokenizer,
                         response_budget=self.response_budget, session=state)

    def read(self, ids, *, from_cache=False, commit=True):
        """Emit whole nodes once; defer oversized batches without marking them visited.

        Cached rehydration is explicit and does not traverse the tree again.
        Oversized single nodes fail rather than silently hide unread text forever.
        """
        result = {"nodes": [], "omitted_node_ids": [], "already_visited": []}
        for node_id in dict.fromkeys(ids):
            if self.session and node_id in self.session.visited and not from_cache:
                result["already_visited"].append(node_id)
                continue
            if from_cache:
                if not self.session or node_id not in self.session.cache:
                    raise ValueError("Cannot restore an unread node from cache")
                record = self.session.cache[node_id]
            else:
                record = self.session.cache.get(node_id) if self.session else None
                record = record or self._record(node_id)
            if self.tokenizer.count(json.dumps({"nodes": [record]}, ensure_ascii=False)) > self.response_budget:
                raise ValueError("Node %s exceeds tool response budget; increase --tool-response-budget or reduce chunk/topic sizes" % node_id)
            result["nodes"].append(record)
            if self.tokenizer.count(json.dumps(result, ensure_ascii=False)) > self.response_budget:
                result["nodes"].pop()
                result["omitted_node_ids"].append(node_id)
                continue
        return self._finalize(result, commit=commit, from_cache=from_cache)

    def _finalize(self, result, *, commit=True, from_cache=False):
        """Include ranking/page metadata in the same budget before committing visits."""
        if "entry_node_ids" in result:
            result["entry_node_ids"] = [n["node_id"] for n in result["nodes"]]
        while self.tokenizer.count(json.dumps(result, ensure_ascii=False)) > self.response_budget:
            if not result["nodes"]:
                raise ValueError("Tool metadata exceeds response budget; reduce top_k, limit, node_ids or batch size")
            record = result["nodes"].pop()
            result["omitted_node_ids"].append(record["node_id"])
            if "entry_node_ids" in result:
                result["entry_node_ids"] = [n["node_id"] for n in result["nodes"]]
        if self.session and commit and not from_cache:
            for record in result["nodes"]:
                node_id = record["node_id"]
                if node_id not in self.session.visited:
                    self.session.visited.add(node_id)
                    self.session.order.append(node_id)
                self.session.cache[node_id] = record
        return result

    def navigation_state(self):
        if not self.session:
            return {}
        frontier = set()
        for node_id in self.session.visited:
            node = self.index.nodes[node_id]
            frontier.update(node.children)
            if node.parent:
                frontier.add(node.parent)
        frontier -= self.session.visited
        ordered = sorted(frontier, key=lambda i: (self.index.nodes[i].start, i))
        return {"visited_count": len(self.session.visited), "recent_node_ids": self.session.order[-16:],
                "frontier": ordered[:16], "frontier_omitted": max(0, len(ordered) - 16)}

    def document_map(self, budget=0, mode="full"):
        """All chapter-to-root nodes, deduplicated, with every topic's full text.

        Full mode never silently truncates. Budgeted mode is an explicit fallback
        for documents whose chapter count/summaries make the directory too large.
        """
        if mode not in {"full", "budgeted"} or not isinstance(budget, int) or budget < 0:
            raise ValueError("Invalid directory mode/budget")
        if mode == "budgeted" and budget < 512:
            raise ValueError("Budgeted directory needs map_budget >= 512")
        chapters = sorted((n for n in self.index.nodes.values() if n.kind == "chapter"), key=lambda n: n.start)
        upper = {self.index.root_id}
        for chapter in chapters:
            current = chapter.id
            while current:
                upper.add(current)
                current = self.index.nodes[current].parent
        section_titles = {s.id: s.title for s in self.index.sections}
        result = {"root_id": self.index.root_id, "nodes": [], "total_nodes": len(upper),
                  "omitted_nodes": len(upper), "mode": mode, "complete": False}
        # Higher abstractions first; each node appears only once even if shared
        # by many chapter paths. Actual IDs/text come from this document's index.
        for node in sorted((self.index.nodes[i] for i in upper), key=lambda n: (-n.level, n.start, n.id)):
            record = self._record(node.id)
            record["children"] = [i for i in node.children if i in upper]
            if node.section_id in section_titles:
                record["section_title"] = section_titles[node.section_id]
            result["nodes"].append(record)
            if budget and self.tokenizer.count(json.dumps(result, ensure_ascii=False)) > budget:
                result["nodes"].pop()
                if mode == "full":
                    raise ValueError("Full chapter-to-root directory exceeds map_budget; increase it or explicitly select budgeted mode")
                break
        result["omitted_nodes"] = len(upper) - len(result["nodes"])
        result["complete"] = not result["omitted_nodes"]
        if not result["nodes"]:
            raise ValueError("Directory budget cannot fit the root; increase map_budget")
        return result

    async def search(self, query=None, top_k=5, kind=None, min_level=None, max_level=None, queries=None):
        if (query is None) == (queries is None):
            raise ValueError("Provide exactly one of query or queries")
        requests = [query] if query is not None else queries
        if not isinstance(requests, list) or not 1 <= len(requests) <= 8:
            raise ValueError("queries must contain 1..8 strings")
        if any(not isinstance(q, str) or not q.strip() for q in requests):
            raise ValueError("Queries must be nonempty strings")
        visited = set(self.session.visited) if self.session else set()
        gate = asyncio.Semaphore(4)

        async def find(q):
            async with gate:
                return await self.search_engine.search(q, top_k, kind, min_level, max_level,
                                                      unique_nodes=True, exclude_nodes=visited)
        batches = await asyncio.gather(*(find(q) for q in requests))
        candidates = {}
        for hits in batches:
            for hit in hits:
                if hit.node_id not in candidates or hit.score > candidates[hit.node_id].score:
                    candidates[hit.node_id] = hit
        hits = sorted(candidates.values(), key=lambda h: (-h.score, h.start, h.node_id))[:top_k]
        result = self.read([hit.node_id for hit in hits], commit=False)
        result["matches"] = [{"node_id": h.node_id, "block_id": h.block_id,
                              "score": h.score, "kind": h.kind, "level": h.level} for h in hits]
        result["entry_node_ids"] = []
        return self._finalize(result)

    def move_up(self, node_ids):
        ids = self._ids(node_ids)
        parents = list(dict.fromkeys(self.index.nodes[i].parent for i in ids if self.index.nodes[i].parent))
        result = self.read(parents, commit=False)
        result["at_root"] = [i for i in ids if self.index.nodes[i].parent is None]
        return self._finalize(result)

    def move_down(self, node_ids, offset=0, limit=5):
        ids = self._ids(node_ids)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("limit must be 1..20")
        children, pages = [], []
        for node_id in ids:
            node = self.index.nodes[node_id]
            selected = node.children[offset:offset + limit]
            children.extend(selected)
            pages.append({"node_id": node_id, "total": len(node.children),
                          "next_offset": offset + limit if offset + limit < len(node.children) else None,
                          "selected_node_ids": selected})
        result = self.read(children, commit=False)
        result["pages"] = pages
        return self._finalize(result)
