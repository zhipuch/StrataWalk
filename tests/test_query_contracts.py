import asyncio
import json
import unittest
from stratawalk.agent import Agent, AgentConfig, TreeTools
from stratawalk.agent.prompts import DIRECTORY_TAG, policy_messages
from stratawalk.index.search import SemanticSearch
from stratawalk.providers.offline import HashEmbedder, OfflinePolicy
from test_index import builder, TEXT
from test_agent import Scripted


class QueryContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.index = await builder().build(TEXT, "report.md")
        self.tools = TreeTools(self.index, SemanticSearch(self.index, HashEmbedder()), response_budget=2048)

    def test_directory_has_every_chapter_and_ancestor_with_full_topics(self):
        expected = {self.index.root_id}
        for node in self.index.nodes.values():
            if node.kind == "chapter":
                while node:
                    expected.add(node.id)
                    node = self.index.nodes.get(node.parent)
        directory = self.tools.document_map()
        self.assertTrue(directory["complete"])
        self.assertEqual({n["node_id"] for n in directory["nodes"]}, expected)
        self.assertEqual(len(directory["nodes"]), len(expected))
        for node in directory["nodes"]:
            self.assertEqual([b["text"] for b in node["blocks"]],
                             [b.text for b in self.index.nodes[node["node_id"]].blocks])
        messages = policy_messages({"document_map": directory, "question": "overview"})
        self.assertEqual(json.loads(messages[0]["content"].split(DIRECTORY_TAG)[1]), directory)
        self.assertNotIn('"nodes"', messages[1]["content"])

    def test_directory_truncation_is_explicit_opt_in(self):
        full = self.tools.document_map()
        budget = max(512, self.tools.tokenizer.count(json.dumps({**full, "nodes": full["nodes"][:1]}, ensure_ascii=False)) + 30)
        with self.assertRaisesRegex(ValueError, "Full chapter-to-root"):
            self.tools.document_map(budget, "full")
        partial = self.tools.document_map(budget, "budgeted")
        self.assertFalse(partial["complete"])
        self.assertGreater(partial["omitted_nodes"], 0)

    async def test_directory_overview_can_finish_without_source_search(self):
        root = self.index.nodes[self.index.root_id]
        block_id = root.blocks[0].id
        policy = Scripted([{"tool": "finish", "args": {
            "answer": "Overview based on document abstractions [%s]." % block_id,
            "citation_ids": [block_id], "answer_scope": "overview"}}])
        result = await Agent(self.tools, policy).run("Give an overview")
        self.assertEqual(result.status, "complete")
        self.assertEqual([t["tool"] for t in result.trace], ["finish"])
        self.assertEqual(result.citations[0]["evidence_type"], "summary")

    async def test_full_directory_overflow_fails_before_model_call(self):
        policy = Scripted([])
        with self.assertRaisesRegex(ValueError, "Full system directory"):
            await Agent(self.tools, policy, config=AgentConfig(context_limit=3000, output_reserve=1000)).run("overview")
        self.assertEqual(policy.states, [])

    async def test_session_visits_once_and_cache_restore_is_not_a_visit(self):
        session = self.tools.new_session(self.tools.document_map())
        leaf = next(n for n in self.index.nodes.values() if n.kind == "leaf")
        first = session.read([leaf.id])
        self.assertEqual(len(first["nodes"]), 1)
        before = len(session.session.order)
        again = session.read([leaf.id])
        self.assertEqual(again["nodes"], [])
        self.assertEqual(again["already_visited"], [leaf.id])
        restored = session.read([leaf.id], from_cache=True)
        self.assertEqual(restored["nodes"], first["nodes"])
        self.assertEqual(len(session.session.order), before)
        hits = await session.search("alpha", top_k=3, kind="leaf")
        self.assertNotIn(leaf.id, [h["node_id"] for h in hits["matches"]])

    async def test_omitted_nodes_remain_unvisited(self):
        tools = TreeTools(self.index, SemanticSearch(self.index, HashEmbedder()), response_budget=512)
        session = tools.new_session(tools.document_map())
        leaves = [n.id for n in self.index.nodes.values() if n.kind == "leaf"][:2]
        result = session.read(leaves)
        self.assertTrue(result["omitted_node_ids"])
        for node_id in result["omitted_node_ids"]:
            self.assertNotIn(node_id, session.session.visited)
            self.assertEqual(len(session.read([node_id])["nodes"]), 1)

    async def test_distinct_entry_nodes_and_concurrent_subqueries(self):
        together = asyncio.Event()
        class Observed(HashEmbedder):
            active = peak = 0
            async def embed(self, texts):
                self.active += 1
                self.peak = max(self.peak, self.active)
                if self.active == 2:
                    together.set()
                try:
                    await together.wait()
                    return await super().embed(texts)
                finally:
                    self.active -= 1
        embedder = Observed()
        tools = TreeTools(self.index, SemanticSearch(self.index, embedder), response_budget=4096)
        result = await asyncio.wait_for(tools.search(queries=["alpha apples", "beta oranges"], top_k=4), 2)
        ids = [h["node_id"] for h in result["matches"]]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(embedder.peak, 2)

    async def test_parallel_branches_share_visited_and_do_not_return_duplicates(self):
        chapter = next(n for n in self.index.nodes.values() if n.kind == "chapter" and len(n.children) > 1)
        action = {"tool": "move_down", "args": {"node_ids": [chapter.id], "limit": 1}}
        policy = Scripted([
            {"actions": [action, action]},
            {"tool": "finish", "args": {"answer": "Insufficient for the comparison.", "insufficient": True}},
        ])
        result = await Agent(self.tools, policy).run("Compare chapters")
        branches = result.trace[:2]
        self.assertEqual([b["tool"] for b in branches], ["move_down", "move_down"])
        returned = [n["node_id"] for b in branches for n in b["result"]["nodes"]]
        self.assertEqual(len(returned), 1)
        self.assertTrue(branches[1]["result"]["already_visited"])

    async def test_queries_do_not_share_mutable_visit_state(self):
        agent = Agent(self.tools, OfflinePolicy())
        first = await agent.run("beta memory")
        second = await agent.run("beta memory")
        self.assertEqual(first.status, "complete")
        self.assertEqual(first.citations, second.citations)

    async def test_tool_metadata_failure_does_not_commit_invisible_visits(self):
        tools = TreeTools(self.index, SemanticSearch(self.index, HashEmbedder()), response_budget=512)
        session = tools.new_session(tools.document_map())
        before = set(session.session.visited)
        with self.assertRaisesRegex(ValueError, "metadata exceeds"):
            await session.search("alpha", top_k=50, kind="leaf")
        self.assertEqual(session.session.visited, before)

    async def test_source_scope_cannot_cite_only_directory_abstracts(self):
        block_id = self.index.nodes[self.index.root_id].blocks[0].id
        policy = Scripted([
            {"tool": "finish", "args": {"answer": "A precise figure [%s]" % block_id, "citation_ids": [block_id]}},
            {"tool": "finish", "args": {"answer": "Insufficient source evidence.", "insufficient": True}},
        ])
        result = await Agent(self.tools, policy).run("What is the exact figure?")
        self.assertEqual(result.trace[0]["tool"], "error")
        self.assertEqual(result.status, "insufficient")
