import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from stratawalk import load_index
from stratawalk.cli import main


class CLITests(unittest.TestCase):
    def test_tree_view_is_bounded_and_json_inspection_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "report.md", Path(directory) / "report.json"
            source.write_text("# Report\n\n## First\nEvidence.\n## Second\nMore evidence.")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["build", str(source), "--output", str(target)]), 0)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["inspect", str(target), "--tree", "--max-nodes", "2"]), 0)
            tree = stdout.getvalue()
            self.assertIn("Overview", tree)
            self.assertIn("nodes omitted", tree)
            self.assertEqual(tree.count(" topic]"), 2)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["inspect", str(target)]), 0)
            stats = json.loads(stdout.getvalue())
            self.assertEqual(stats["source"], "report.md")
            self.assertEqual(stats["sections"][1]["title"], "First")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["inspect", str(target), "--tree", "--max-nodes", "0"]), 1)
    def test_invalid_index_files_return_actionable_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "broken.json"
            for content in ("[]", "null", "{}", '{"schema_version":1}',
                            '{"schema_version":1,"nodes":null}', "{broken"):
                target.write_text(content)
                stdout, stderr = io.StringIO(), io.StringIO()
                with self.subTest(content=content), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main(["inspect", str(target)]), 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("Invalid index file", stderr.getvalue())
                self.assertIn("Rebuild", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_build_output_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.md"
            original = b"# Report\nOriginal evidence."
            source.write_bytes(original)
            symlink, hardlink = Path(directory) / "symlink.md", Path(directory) / "hardlink.md"
            symlink.symlink_to(source)
            os.link(source, hardlink)
            for output in (source, symlink, hardlink):
                with self.subTest(output=output), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["build", str(source), "--output", str(output)]), 1)
            self.assertEqual(source.read_bytes(), original)

    def test_json_answer_labels_provider_scope_and_protects_index_from_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.md"
            target = Path(directory) / "report.json"
            trace = Path(directory) / "trace.json"
            source.write_text("# Report\nReranking improved quality with additional memory.")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["build", str(source), "--output", str(target)]), 0)
            original = target.read_bytes()
            symlink, hardlink = Path(directory) / "symlink.json", Path(directory) / "hardlink.json"
            symlink.symlink_to(target)
            os.link(target, hardlink)
            for alias in (target, symlink, hardlink):
                with self.subTest(alias=alias), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["ask", str(target), "memory", "--trace", str(alias)]), 1)
            self.assertEqual(target.read_bytes(), original)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["ask", str(target), "memory", "--trace", str(trace), "--json"]), 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["provider"], "offline")
            self.assertEqual(result["answer_scope"], "source")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["citations"][0]["text"], source.read_text())
            self.assertEqual([row["tool"] for row in json.loads(trace.read_text())], ["search", "finish"])

    def test_build_preserves_crlf_source_and_character_offsets(self):
        text = "# 报告\r\n\r\n## 结果\r\nOriginal evidence.\r\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.md"
            target = Path(directory) / "index.json"
            source.write_bytes(text.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["build", str(source), "--output", str(target)]), 0)
            index = load_index(target)
            self.assertEqual(index.source_text, text)
            for node in index.nodes.values():
                if node.kind == "leaf":
                    self.assertEqual(node.blocks[0].text, text[node.start:node.end])
