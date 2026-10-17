"""Model-selected tool loop with explicit context and citation boundaries."""
from dataclasses import asdict, dataclass, field
import json
import re
from typing import List
from .prompts import SYSTEM
from ..providers.compatible import parse_json
from ..tokenization import ByteTokenizer, prefix


@dataclass
class AgentConfig:
    max_steps: int = 24
    context_limit: int = 24000
    output_reserve: int = 2048
    safety_margin: int = 512
    map_budget: int = 1600
    notes_budget: int = 1200

    def validate(self):
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in asdict(self).values()):
            raise ValueError("Agent budgets must be positive integers")
        if self.output_reserve + self.safety_margin >= self.context_limit:
            raise ValueError("No room for agent input")


@dataclass
class AgentResult:
    answer: str
    citations: List[dict]
    status: str
    trace: List[dict] = field(default_factory=list)


class ChatPolicy:
    def __init__(self, model, output_tokens=2048):
        self.model, self.output_tokens = model, output_tokens

    async def decide(self, state):
        return parse_json(await self.model.complete([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(state, ensure_ascii=False)}],
            max_tokens=self.output_tokens))


class Agent:
    def __init__(self, tools, policy, *, config=None, tokenizer=None):
        self.tools, self.policy = tools, policy
        self.config, self.tokenizer = config or AgentConfig(), tokenizer or ByteTokenizer()
        self.config.validate()
        if isinstance(policy, ChatPolicy) and policy.output_tokens > self.config.output_reserve:
            raise ValueError("Policy output limit exceeds reserved context")

    async def run(self, question):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question is empty")
        observations, evidence, notes, trace, repeats = [], {}, "", [], {}
        document_map = self.tools.document_map(self.config.map_budget)
        max_input = self.config.context_limit - self.config.output_reserve - self.config.safety_margin

        def count_state(state):
            messages = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": json.dumps(state, ensure_ascii=False)}]
            return self.tokenizer.count(json.dumps(messages, ensure_ascii=False)) + 32

        def state_for(step):
            state = {"question": question, "document_map": document_map, "notes": notes,
                     "observations": [], "evidence": {}, "remaining_steps": self.config.max_steps - step}
            if count_state(state) > max_input:
                raise ValueError("Question/map/notes exceed agent input budget")
            # Newest evidence first; bounded rendering of the persistent ledger.
            # Reloading a node remains possible even when older excerpts are omitted.
            evidence_budget = max(0, (max_input - count_state(state)) // 2)
            evidence_used = 0
            for block_id, row in reversed(list(evidence.items())):
                size = self.tokenizer.count(json.dumps({block_id: row}, ensure_ascii=False))
                if evidence_used + size > evidence_budget:
                    continue
                state["evidence"][block_id] = row
                evidence_used += size
                if count_state(state) > max_input:
                    del state["evidence"][block_id]
            for observation in reversed(observations):
                state["observations"].insert(0, observation)
                if count_state(state) > max_input:
                    state["observations"].pop(0)
                    break
            return state

        for step in range(self.config.max_steps):
            state = state_for(step)
            # Transport failures propagate; malformed model decisions become a
            # recoverable observation and consume a step.
            try:
                action = await self.policy.decide(state)
                if not isinstance(action, dict) or set(action) != {"tool", "args"}:
                    raise ValueError("Expected exactly tool and args")
                tool, args = action["tool"], action["args"]
                if not isinstance(tool, str) or not isinstance(args, dict):
                    raise ValueError("Invalid action types")
                signature = json.dumps(action, sort_keys=True)
                repeats[signature] = repeats.get(signature, 0) + 1
                if repeats[signature] > 2:
                    raise ValueError("Repeated identical action; choose a new branch or finish")
                if tool == "finish":
                    answer = args.get("answer")
                    ids = args.get("citation_ids", [])
                    insufficient = args.get("insufficient", False)
                    if not isinstance(answer, str) or not answer.strip() or not isinstance(insufficient, bool):
                        raise ValueError("finish requires answer text and boolean insufficient")
                    if not isinstance(ids, list) or any(not isinstance(i, str) or i not in evidence for i in ids):
                        raise ValueError("Citations must reference source blocks actually read")
                    ids = list(dict.fromkeys(ids))
                    inline = set(re.findall(r"\[(n\d+:b\d+)\]", answer))
                    if not inline <= set(ids):
                        raise ValueError("Inline citations must be listed in citation_ids")
                    if not ids and not insufficient:
                        raise ValueError("Read source evidence before answering, or mark insufficient")
                    trace.append({"step": step, "tool": tool, "args": args})
                    return AgentResult(answer, [{"block_id": i, **evidence[i]} for i in ids],
                                       "insufficient" if insufficient else "complete", trace)
                elif tool == "search":
                    result = await self.tools.search(**args)
                elif tool == "move_up":
                    result = self.tools.move_up(**args)
                elif tool == "move_down":
                    result = self.tools.move_down(**args)
                elif tool == "compact_context":
                    if set(args) - {"notes", "keep_node_ids"}:
                        raise ValueError("Unknown compact_context arguments")
                    new_notes, keep = args.get("notes", ""), args.get("keep_node_ids", [])
                    if not isinstance(new_notes, str) or not isinstance(keep, list) or any(i not in self.tools.index.nodes for i in keep):
                        raise ValueError("Invalid compaction notes or node IDs")
                    notes = prefix(new_notes, self.config.notes_budget, self.tokenizer)
                    observations.clear()
                    result = self.tools.read(keep[:10])
                    result["notes"] = notes
                    result["preserved_source_ids"] = list(evidence)[-50:]
                else:
                    raise ValueError("Unknown tool")
                for node in result.get("nodes", []):
                    if node["kind"] == "leaf":
                        for block in node["blocks"]:
                            evidence[block["block_id"]] = {
                                "node_id": node["node_id"], "text": block["text"],
                                "source_name": block["source_name"], "start": block["start"], "end": block["end"]}
                observation = {"tool": tool, "result": result}
                observations.append(observation)
                trace.append({"step": step, "tool": tool, "args": args, "result": result,
                              "input_units": count_state(state)})
            except (ValueError, TypeError, KeyError) as exc:
                observation = {"tool": "error", "error": str(exc)[:300]}
                observations.append(observation)
                trace.append({"step": step, **observation})
        return AgentResult("Exploration budget exhausted before a supported final answer was produced.",
                           [], "budget_exhausted", trace)
