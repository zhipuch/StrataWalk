"""Section boundaries without an LLM; optional LlamaIndex adapter."""
import re
from typing import List, Protocol
from .models import Section


class SectionParser(Protocol):
    def parse(self, text: str) -> List[Section]: ...


def _sections(text, starts, titles):
    return [Section("s%d" % i, titles[i], start,
                    starts[i + 1] if i + 1 < len(starts) else len(text))
            for i, start in enumerate(starts)]


class MarkdownSectionParser:
    """Split at headings of a selected depth, preserving preamble and offsets.

    By default, use H2 chapters when present, otherwise H1. Ignore headings
    inside fenced code. Plain text becomes one section. No semantic inference.
    """
    def __init__(self, heading_level=None):
        if heading_level is not None and not 1 <= heading_level <= 6:
            raise ValueError("Heading level must be 1..6")
        self.heading_level = heading_level

    def parse(self, text):
        if not text.strip():
            raise ValueError("Document is empty")
        headings = []
        offset, fence = 0, None
        for line in text.splitlines(keepends=True):
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if marker:
                run = marker.group(1)
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence):
                    fence = None
            elif fence is None:
                match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
                if match:
                    headings.append((len(match.group(1)), offset, match.group(2)))
            offset += len(line)
        level = self.heading_level or (2 if any(h[0] == 2 for h in headings) else 1)
        selected = [(offset, title) for depth, offset, title in headings if depth == level]
        if not selected or selected[0][0] != 0:
            selected.insert(0, (0, "Preamble" if selected else "Document"))
        return _sections(text, [h[0] for h in selected], [h[1] for h in selected])


class LlamaIndexSectionParser:
    """Use MarkdownNodeParser boundaries; keep the original source unchanged.

    LlamaIndex strips/reformats text. Sequential matching maps its content back
    to exact source spans. Fail explicitly if matching is ambiguous or impossible.
    """
    def parse(self, text):
        if not text.strip():
            raise ValueError("Document is empty")
        try:
            from llama_index.core import Document
            from llama_index.core.node_parser import MarkdownNodeParser
        except ImportError as exc:
            raise ImportError("Install stratawalk[llamaindex] for this parser") from exc
        nodes = MarkdownNodeParser().get_nodes_from_documents([Document(text=text)])
        starts, titles, cursor = [], [], 0
        for node in nodes:
            content = node.get_content().strip()
            if not content:
                continue
            start = text.find(content, cursor)
            if start < 0:
                raise ValueError("Cannot map LlamaIndex section back to source; use markdown parser")
            starts.append(start)
            titles.append(content.splitlines()[0].lstrip("# ")[:160])
            cursor = start + len(content)
        if not starts:
            raise ValueError("LlamaIndex returned no sections")
        starts[0] = 0
        return _sections(text, starts, titles)
