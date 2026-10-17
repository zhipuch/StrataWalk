"""Persisted data model: structural nodes contain individually embedded blocks."""
from dataclasses import dataclass, field
import math
import hashlib
from typing import Dict, List, Optional


@dataclass
class Section:
    id: str
    title: str
    start: int
    end: int


@dataclass
class Block:
    id: str
    text: str
    embedding: List[float] = field(default_factory=list)
    # Immediate child blocks supplied to the summarizer, not claim-level proof.
    source_block_ids: List[str] = field(default_factory=list)


@dataclass
class Node:
    id: str
    kind: str  # leaf, summary, chapter, root
    level: int
    start: int
    end: int
    section_id: Optional[str]
    blocks: List[Block]
    children: List[str] = field(default_factory=list)
    parent: Optional[str] = None


@dataclass
class TreeIndex:
    document_id: str
    source_name: str
    source_text: str
    root_id: str
    nodes: Dict[str, Node]
    sections: List[Section]
    metadata: dict = field(default_factory=dict)
    schema_version: int = 1

    def block_map(self) -> Dict[str, Block]:
        return {b.id: b for n in self.nodes.values() for b in n.blocks}

    def validate(self) -> None:
        """Reject broken provenance, coverage, vectors, cycles and orphan nodes."""
        if self.schema_version != 1:
            raise ValueError("Unsupported index schema")
        if not self.source_text or self.document_id != hashlib.sha256(self.source_text.encode()).hexdigest():
            raise ValueError("Source checksum mismatch or empty source")
        if self.root_id not in self.nodes:
            raise ValueError("Missing root")
        if self.nodes[self.root_id].parent is not None:
            raise ValueError("Root must not have a parent")
        section_map = {s.id: s for s in self.sections}
        section_ids = set(section_map)
        if len(section_ids) != len(self.sections):
            raise ValueError("Duplicate section IDs")
        end = 0
        for section in self.sections:
            if section.start != end or not section.start < section.end <= len(self.source_text):
                raise ValueError("Sections must cover the source in order")
            end = section.end
        if end != len(self.source_text):
            raise ValueError("Incomplete section coverage")
        seen, block_ids, chapter_sections = set(), set(), set()
        dimension = None

        def visit(node_id):
            nonlocal dimension
            if node_id in seen:
                raise ValueError("Cycle or multiple structural parents")
            seen.add(node_id)
            node = self.nodes[node_id]
            if node.id != node_id or node.kind not in {"leaf", "summary", "chapter", "root"}:
                raise ValueError("Invalid node identity or kind")
            if (node.kind == "root") != (node.id == self.root_id):
                raise ValueError("Only the designated root may have root kind")
            if not 0 <= node.start < node.end <= len(self.source_text) or not node.blocks:
                raise ValueError("Invalid span or empty node")
            if node.section_id is not None and node.section_id not in section_ids:
                raise ValueError("Unknown section")
            if node.section_id is not None:
                section = section_map[node.section_id]
                if not section.start <= node.start < node.end <= section.end:
                    raise ValueError("Node escapes its section span")
            if node.kind == "chapter":
                if node.section_id is None or node.section_id in chapter_sections:
                    raise ValueError("Require exactly one chapter node per section")
                chapter_sections.add(node.section_id)
                section = section_map[node.section_id]
                if (node.start, node.end) != (section.start, section.end):
                    raise ValueError("Chapter does not cover its section")
            if node.kind == "leaf":
                if node.children or node.level != 0 or len(node.blocks) != 1 or node.section_id is None:
                    raise ValueError("Invalid source leaf")
                if node.blocks[0].text != self.source_text[node.start:node.end]:
                    raise ValueError("Source text does not match leaf offsets")
            elif not node.children:
                raise ValueError("Summary node must have children")
            if any(c not in self.nodes for c in node.children):
                raise ValueError("Missing child node")
            children = [self.nodes[c] for c in node.children]
            if children:
                if node.start != children[0].start or node.end != children[-1].end:
                    raise ValueError("Parent span differs from child coverage")
                if node.level != 1 + max(c.level for c in children):
                    raise ValueError("Invalid node level")
                last_start, covered = -1, node.start
                for child in children:
                    if (child.parent != node.id or child.start < last_start or child.start > covered
                            or child.start < node.start or child.end > node.end
                            or (node.section_id is not None and child.section_id != node.section_id)):
                        raise ValueError("Broken parent link, order or coverage")
                    last_start, covered = child.start, max(covered, child.end)
            allowed = {b.id for c in children for b in c.blocks}
            for block in node.blocks:
                if block.id in block_ids or not block.text:
                    raise ValueError("Duplicate block ID or empty block")
                block_ids.add(block.id)
                if not block.embedding or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                    and math.isfinite(v) for v in block.embedding):
                    raise ValueError("Missing or nonfinite embedding")
                if dimension is None:
                    dimension = len(block.embedding)
                if len(block.embedding) != dimension:
                    raise ValueError("Inconsistent embedding dimensions")
                if node.kind != "leaf" and (not block.source_block_ids or not set(block.source_block_ids) <= allowed):
                    raise ValueError("Invalid summary provenance")
            for child in children:
                visit(child.id)

        visit(self.root_id)
        if chapter_sections != section_ids:
            raise ValueError("Missing chapter representation")
        if seen != set(self.nodes):
            raise ValueError("Unreachable nodes")
        root = self.nodes[self.root_id]
        if root.start != 0 or root.end != len(self.source_text):
            raise ValueError("Root must cover the full document")
