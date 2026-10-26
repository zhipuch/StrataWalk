import json
import unittest
from stratawalk.agent import Agent, AgentConfig, TreeTools
from stratawalk.agent.prompts import SYSTEM, policy_messages
from stratawalk.index.search import SemanticSearch
from stratawalk.providers.offline import HashEmbedder, OfflinePolicy
from stratawalk.tokenization import ByteTokenizer
from test_index import builder, TEXT


class Scripted:
    def __init__(self, actions):
        self.actions, self.states = iter(actions), []

    async def decide(self, state):
        self.states.append(state)
        return next(self.actions)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.index = await builder().build(TEXT, "report.md")
        self.tools = TreeTools(self.index, SemanticSearch(self.index, HashEmbedder()), response_budget=1024)

    async def test_offline_run_citations_match_original_source(self):
        result = await Agent(self.tools, OfflinePolicy()).run("beta oranges memory")
        self.assertEqual(result.status, "complete")
        self.assertTrue(result.citations)
        for citation in result.citations:
            self.assertEqual(citation["text"], TEXT[citation["start"]:citation["end"]])
        self.assertEqual([t["tool"] for t in result.trace], ["search", "finish"])
        returned = {node["node_id"] for node in result.trace[0]["result"]["nodes"]}
        expected = [hit["block_id"] for hit in result.trace[0]["result"]["matches"] if hit["node_id"] in returned]
        self.assertEqual([citation["block_id"] for citation in result.citations], expected)

    async def test_offline_failed_retrieval_stops_without_repeating(self):
        result = await Agent(self.tools, OfflinePolicy()).run("!!!")
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.citations, [])
        self.assertEqual([event["tool"] for event in result.trace], ["error", "finish"])

    async def test_up_down_pagination_and_compaction(self):
        root = self.index.root_id
        leaf = next(n for n in self.index.nodes.values() if n.kind == "leaf")
        policy = Scripted([
            {"tool": "move_down", "args": {"node_ids": [root], "limit": 1}},
            {"tool": "move_up", "args": {"node_ids": [leaf.id]}},
            {"tool": "search", "args": {"query": "beta", "kind": "leaf", "top_k": 1}},
            {"tool": "compact_context", "args": {"notes": "Need source verification", "keep_node_ids": [root]}},
            {"tool": "finish", "args": {"answer": "Not enough evidence for the requested comparison.", "citation_ids": [], "insufficient": True}},
        ])
        result = await Agent(self.tools, policy).run("Compare chapters")
        self.assertEqual(result.status, "insufficient")
        self.assertTrue(policy.states[-1]["evidence"])
        self.assertEqual(policy.states[-1]["notes"], "Need source verification")
        self.assertIsNotNone(result.trace[0]["result"]["pages"][0]["next_offset"])

    async def test_invented_citations_rejected(self):
        policy = Scripted([
            {"tool": "finish", "args": {"answer": "Unsupported [n999:b0]", "citation_ids": ["n999:b0"]}},
            {"tool": "finish", "args": {"answer": "Insufficient evidence.", "insufficient": True, "citation_ids": []}},
        ])
        result = await Agent(self.tools, policy).run("question")
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.trace[0]["tool"], "error")

    async def test_loop_and_step_limits(self):
        action = {"tool": "move_up", "args": {"node_ids": [self.index.root_id]}}
        result = await Agent(self.tools, Scripted([action] * 5), config=AgentConfig(max_steps=4)).run("question")
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.trace[-1]["tool"], "error")

    async def test_rendered_context_fits_budget(self):
        policy = Scripted([
            {"tool": "search", "args": {"query": "beta", "kind": "leaf", "top_k": 10}},
            {"tool": "finish", "args": {"answer": "Insufficient.", "citation_ids": [], "insufficient": True}},
        ])
        config = AgentConfig(context_limit=12000)
        await Agent(self.tools, policy, config=config).run("question")
        for state in policy.states:
            messages = policy_messages(state)
            self.assertLessEqual(ByteTokenizer().count(json.dumps(messages, ensure_ascii=False)) + 32,
                                 config.context_limit - config.output_reserve - config.safety_margin)

    async def test_compaction_can_clear_notes_when_new_reads_cannot_fit(self):
        config = AgentConfig()
        directory = self.tools.document_map()
        session = self.tools.new_session(directory)
        state = {"question": "question", "document_map": directory, "notes": "", "observations": [],
                 "evidence": {}, "navigation": session.navigation_state(),
                 "remaining_steps": config.max_steps, "max_parallel_actions": config.max_parallel_actions}
        base_units = ByteTokenizer().count(json.dumps(policy_messages(state), ensure_ascii=False)) + 32
        config.context_limit = base_units + config.output_reserve + config.safety_margin + 2600
        policy = Scripted([
            {"tool": "compact_context", "args": {"notes": "x" * config.notes_budget}},
            {"tool": "compact_context", "args": {"notes": ""}},
            {"tool": "finish", "args": {"answer": "Insufficient.", "insufficient": True}},
        ])
        result = await Agent(self.tools, policy, config=config).run("question")
        self.assertEqual([event["tool"] for event in result.trace], ["compact_context", "compact_context", "finish"])
        self.assertEqual(policy.states[1]["notes"], "x" * config.notes_budget)
        self.assertEqual(policy.states[2]["notes"], "")
        for item in policy.states:
            used = ByteTokenizer().count(json.dumps(policy_messages(item), ensure_ascii=False)) + 32
            self.assertLessEqual(used + config.output_reserve + config.safety_margin, config.context_limit)

    async def test_unknown_nodes_and_bad_pagination(self):
        with self.assertRaises(ValueError):
            self.tools.move_down(["unknown"])
        with self.assertRaises(ValueError):
            self.tools.move_down([self.index.root_id], offset=-1)
        at_root = self.tools.move_up([self.index.root_id])
        self.assertEqual(at_root["nodes"], [])
        self.assertEqual(at_root["at_root"], [self.index.root_id])
