import io
import json
import unittest
from unittest.mock import patch
from stratawalk.models import Block
from stratawalk.providers.compatible import CompatibleClient, CompatibleChat, CompatibleEmbedder, LLMSummarizer, parse_json


class FakeClient:
    base_url = "https://fixture.example/v1"
    def __init__(self, response):
        self.response, self.calls = response, []
    async def post(self, path, payload):
        self.calls.append((path, payload))
        return self.response


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_response_order_and_missing_indices(self):
        client = FakeClient({"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})
        embedder = CompatibleEmbedder(client, "fixture-embedding")
        self.assertEqual(await embedder.embed(["a", "b"]), [[1, 0], [0, 1]])
        client.response = {"data": [{"index": 0, "embedding": [1, 0]}]}
        with self.assertRaises(ValueError):
            await embedder.embed(["a", "b"])

    async def test_chat_and_summary_response_validation(self):
        client = FakeClient({"choices": [{"message": {"content": '{"blocks":["A summary.","Another theme."]}'}}]})
        model = CompatibleChat(client, "fixture-chat")
        paragraphs = await LLMSummarizer(model).summarize([Block("b0", "source")], 100)
        self.assertEqual(len(paragraphs), 2)
        self.assertEqual(client.calls[0][0], "/chat/completions")
        client.response = {"choices": [{"message": {"content": '{"blocks":[1]}'}}]}
        with self.assertRaises(ValueError):
            await LLMSummarizer(model).summarize([Block("b0", "source")], 100)

    async def test_http_transport_payload_and_authorization(self):
        client = CompatibleClient("https://fixture.example/v1", "fixture-secret")
        def respond(request, timeout):
            self.assertEqual(request.full_url, "https://fixture.example/v1/embeddings")
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture-secret")
            self.assertEqual(json.loads(request.data), {"input": ["text"]})
            self.assertGreater(timeout, 0)
            return io.BytesIO(b'{"data":[]}')
        with patch("urllib.request.urlopen", side_effect=respond):
            self.assertEqual(await client.post("/embeddings", {"input": ["text"]}), {"data": []})

    def test_json_fences_and_invalid_shapes(self):
        self.assertEqual(parse_json('```json\n{"tool":"search"}\n```'), {"tool": "search"})
        with self.assertRaises(ValueError):
            parse_json("[]")
        with self.assertRaises(ValueError):
            parse_json('```json\n{}')

    async def test_full_compatible_build_and_model_chosen_walk(self):
        """Exercise real adapters/policy, replacing only the remote HTTP service."""
        from stratawalk import BuildConfig, IndexBuilder
        from stratawalk.agent import Agent, ChatPolicy, TreeTools
        from stratawalk.index.search import SemanticSearch
        from stratawalk.providers.offline import HashEmbedder
        from stratawalk.tokenization import ByteTokenizer
        from test_index import TEXT

        class Service:
            base_url = "https://fixture.example/v1"
            decisions = 0
            async def post(self, path, payload):
                if path == "/embeddings":
                    vectors = await HashEmbedder().embed(payload["input"])
                    return {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]}
                instructions = payload["messages"][0]["content"]
                if instructions.startswith("Summarize ordered"):
                    content = json.dumps({"blocks": ["first", "second"]})
                else:
                    state = json.loads(payload["messages"][1]["content"])
                    self.decisions += 1
                    if self.decisions == 1:
                        action = {"tool": "move_down", "args": {"node_ids": [state["document_map"]["root_id"]]}}
                    elif self.decisions == 2:
                        action = {"tool": "search", "args": {"query": "beta memory", "kind": "leaf", "top_k": 1}}
                    else:
                        block_id, record = next(iter(state["evidence"].items()))
                        action = {"tool": "finish", "args": {"answer": "[%s] %s" % (block_id, record["text"]), "citation_ids": [block_id]}}
                    content = json.dumps(action)
                return {"choices": [{"message": {"content": content}}]}
        service = Service()
        embedder = CompatibleEmbedder(service, "fixture-embedding")
        model = CompatibleChat(service, "fixture-chat")
        index = await IndexBuilder(LLMSummarizer(model), embedder,
            config=BuildConfig(chunk_size=100, chunk_overlap=20, summary_size=48, reduction_input=220)).build(TEXT)
        self.assertTrue(any(len(n.blocks) > 1 for n in index.nodes.values()))
        result = await Agent(TreeTools(index, SemanticSearch(index, embedder)), ChatPolicy(model)).run("beta memory")
        self.assertEqual(result.status, "complete")
        self.assertEqual([t["tool"] for t in result.trace], ["move_down", "search", "finish"])
