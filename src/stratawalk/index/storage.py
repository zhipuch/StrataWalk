"""Versioned, atomic JSON persistence. Source text and embeddings stay together."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from ..models import Block, Node, Section, TreeIndex


def save_index(index: TreeIndex, path) -> None:
    index.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temp = handle.name
            json.dump(asdict(index), handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def load_index(path) -> TreeIndex:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported index schema")
        data["nodes"] = {key: Node(**{**node, "blocks": [Block(**b) for b in node["blocks"]]})
                         for key, node in data["nodes"].items()}
        data["sections"] = [Section(**section) for section in data["sections"]]
        index = TreeIndex(**data)
        index.validate()
        return index
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid index file '%s': %s. Rebuild it from the source with stratawalk build."
                         % (path.name, exc)) from None
