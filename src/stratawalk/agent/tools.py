"""Read-only tree tools with bounded serialization and exact source provenance."""
import json
from ..tokenization import ByteTokenizer, prefix


class TreeTools:
    def __init__(self, index, search, *, tokenizer=None, response_budget=4096):
        self.index, self.search_engine = index, search
        self.tokenizer = tokenizer or ByteTokenizer()
        if response_budget < 512:
            raise ValueError("Tool response budget must be >= 512")
        self.response_budget = response_budget

    def _ids(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(not isinstance(i, str) for i in ids):
            raise ValueError("node_ids must contain 1..10 node IDs")
        ids = list(dict.fromkeys(ids))
        if any(i not in self.index.nodes for i in ids):
            raise ValueError("Unknown node ID")
        return ids

    def read(self, ids, focus=None):
        """Return bounded records. Truncated text is explicitly marked.

        Source offsets for delivered leaf excerpts refer to exactly the
        delivered prefix, rather than pretending the entire leaf was read.
        """
        records = []
        remaining = self.response_budget
        omitted = []
        for node_id in dict.fromkeys(ids):
            node = self.index.nodes[node_id]
            record = {"node_id": node.id, "kind": node.kind, "level": node.level,
                      "parent": node.parent, "child_count": len(node.children),
                      "start": node.start, "end": node.end, "blocks": []}
            ordered = sorted(node.blocks, key=lambda b: b.id not in (focus or set()))
            for block in ordered:
                # Reserve identifier/metadata overhead for each block.
                if remaining < 192:
                    break
                excerpt = prefix(block.text, remaining - 192, self.tokenizer)
                if not excerpt:
                    break
                row = {"block_id": block.id, "text": excerpt,
                       "truncated": len(excerpt) != len(block.text)}
                if node.kind == "leaf":
                    row.update(source_name=self.index.source_name, start=node.start,
                               end=node.start + len(excerpt))
                record["blocks"].append(row)
                remaining -= self.tokenizer.count(excerpt) + 192
            record["blocks_omitted"] = len(node.blocks) - len(record["blocks"])
            if record["blocks"]:
                records.append(record)
            else:
                omitted.append(node_id)
        return {"nodes": records, "omitted_node_ids": omitted}

    def document_map(self, budget=1600):
        """Deduplicated chapter/ancestor summaries within a serialized budget."""
        root = self.index.nodes[self.index.root_id]
        overview = prefix("\n".join(b.text for b in root.blocks), budget // 3, self.tokenizer)
        result = {"root_id": root.id, "overview": overview, "chapters": [],
                  "ancestors": [], "chapters_omitted": 0}
        sections = {s.id: s for s in self.index.sections}
        chapters = sorted((n for n in self.index.nodes.values() if n.kind == "chapter"), key=lambda n: n.start)
        included = {root.id}
        for chapter in chapters:
            ancestors, current = [], chapter.parent
            while current:
                ancestors.append(current)
                current = self.index.nodes[current].parent
            row = {"node_id": chapter.id, "section": sections[chapter.section_id].title,
                   "summary": prefix(" ".join(b.text for b in chapter.blocks), 120, self.tokenizer),
                   "ancestors": ancestors, "start": chapter.start, "end": chapter.end}
            result["chapters"].append(row)
            if self.tokenizer.count(json.dumps(result, ensure_ascii=False)) > budget:
                result["chapters"].pop()
                break
            for node_id in ancestors:
                if node_id in included:
                    continue
                node = self.index.nodes[node_id]
                entry = {"node_id": node_id, "summary": prefix(" ".join(b.text for b in node.blocks), 120, self.tokenizer)}
                result["ancestors"].append(entry)
                if self.tokenizer.count(json.dumps(result, ensure_ascii=False)) > budget:
                    result["ancestors"].pop()
                else:
                    included.add(node_id)
        result["chapters_omitted"] = len(chapters) - len(result["chapters"])
        return result

    async def search(self, query, top_k=5, kind=None, min_level=None, max_level=None):
        hits = await self.search_engine.search(query, top_k, kind, min_level, max_level)
        # Only bounded node text is returned. Search ranking does not bypass
        # context limits by including an extra unbounded copy of each hit text.
        result = self.read([hit.node_id for hit in hits], {hit.block_id for hit in hits})
        result["matches"] = [{"node_id": h.node_id, "block_id": h.block_id,
                              "score": h.score, "kind": h.kind, "level": h.level} for h in hits]
        return result

    def move_up(self, node_ids):
        ids = self._ids(node_ids)
        parents = list(dict.fromkeys(self.index.nodes[i].parent for i in ids if self.index.nodes[i].parent))
        result = self.read(parents)
        result["at_root"] = [i for i in ids if self.index.nodes[i].parent is None]
        return result

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
        result = self.read(children)
        result["pages"] = pages
        return result
