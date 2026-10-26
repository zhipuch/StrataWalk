"""Bounded terminal views of a validated index; persisted data stays unchanged."""
import json
from .models import TreeIndex


def _preview(text, limit=60):
    # Bound work on long source passages and escape terminal control characters.
    compact = " ".join(text[:limit * 4].split())
    label = compact[:limit] + ("…" if len(compact) > limit else "")
    return json.dumps(label, ensure_ascii=False)


def format_index_tree(index: TreeIndex, max_nodes: int = 40) -> str:
    """Show source-ordered nodes without recursion or unbounded tree output."""
    if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or max_nodes < 1:
        raise ValueError("--max-nodes must be a positive integer")
    titles = {section.id: section.title for section in index.sections}
    block_count = sum(len(node.blocks) for node in index.nodes.values())
    lines = ["StrataWalk · " + _preview(index.source_name, 80),
             "%d sections · %d nodes · %d blocks" % (len(index.sections), len(index.nodes), block_count)]
    pending, shown = [(index.root_id, "", None)], 0
    while pending and shown < max_nodes:
        node_id, prefix, last = pending.pop()
        node = index.nodes[node_id]
        branch = "" if last is None else "└── " if last else "├── "
        if node.kind == "root":
            label = "Overview"
        elif node.kind == "chapter":
            label = "Section: " + _preview(titles[node.section_id])
        elif node.kind == "leaf":
            label = "Source: " + _preview(node.blocks[0].text, 48)
        else:
            label = "Summary"
        detail = "chars %d:%d" % (node.start, node.end) if node.kind == "leaf" else (
            "%d topic%s" % (len(node.blocks), "" if len(node.blocks) == 1 else "s"))
        lines.append(prefix + branch + label + " [" + _preview(node.id, 32)[1:-1] + " · " + detail + "]")
        shown += 1
        child_prefix = prefix + ("" if last is None else "    " if last else "│   ")
        # Never queue an entire high-fanout tree merely to print a small preview.
        children = node.children[:max_nodes - shown]
        for number in range(len(children) - 1, -1, -1):
            pending.append((children[number], child_prefix, number == len(node.children) - 1))
    omitted = len(index.nodes) - shown
    if omitted:
        lines.append("… %d nodes omitted; increase --max-nodes to see more." % omitted)
    return "\n".join(lines)
