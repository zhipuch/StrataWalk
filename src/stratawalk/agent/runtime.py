"""Multi-entry tool loop with per-query visited state, bounded context and provenance."""
import asyncio
from dataclasses import asdict, dataclass, field
import json
import re
from typing import List
from .prompts import policy_messages
from ..providers.compatible import parse_json
from ..tokenization import ByteTokenizer, prefix


@dataclass
class AgentConfig:
    max_steps: int = 24
    context_limit: int = 24000
    output_reserve: int = 2048
    safety_margin: int = 512
    map_budget: int = 0  # 0 = no separate cap; full directory must fit context.
    notes_budget: int = 1200
    max_parallel_actions: int = 4
    directory_mode: str = "full"

    def validate(self):
        for name, value in asdict(self).items():
            if name == "directory_mode":
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < (0 if name == "map_budget" else 1):
                raise ValueError("Invalid agent budget: " + name)
        if self.directory_mode not in {"full", "budgeted"}:
            raise ValueError("directory_mode must be full or budgeted")
        if not 1 <= self.max_parallel_actions <= 8:
            raise ValueError("max_parallel_actions must be 1..8")
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
        return parse_json(await self.model.complete(policy_messages(state), max_tokens=self.output_tokens))


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
        observations, evidence, summary_evidence, notes, trace, repeats = [], {}, {}, "", [], {}
        document_map = self.tools.document_map(self.config.map_budget, self.config.directory_mode)
        tools = self.tools.new_session(document_map)
        max_input = self.config.context_limit - self.config.output_reserve - self.config.safety_margin

        def remember(records):
            for node in records:
                for block in node["blocks"]:
                    row = {"node_id": node["node_id"], "text": block["text"],
                           "kind": node["kind"], "evidence_type": "source" if node["kind"] == "leaf" else "summary",
                           "source_name": self.tools.index.source_name,
                           "start": block.get("start", node["start"]), "end": block.get("end", node["end"])}
                    (evidence if node["kind"] == "leaf" else summary_evidence)[block["block_id"]] = row
        remember(document_map["nodes"])

        def count_state(state):
            return self.tokenizer.count(json.dumps(policy_messages(state), ensure_ascii=False)) + 32

        def base_state(step):
            return {"question": question, "document_map": document_map, "notes": notes,
                    "observations": [], "evidence": {}, "navigation": tools.navigation_state(),
                    "remaining_steps": self.config.max_steps - step,
                    "max_parallel_actions": self.config.max_parallel_actions}

        def state_for(step):
            state = base_state(step)
            if count_state(state) > max_input:
                raise ValueError("Full system directory/question/notes exceed context. Increase context_limit or explicitly use directory_mode=budgeted with map_budget")
            # Prefer the newest tool result so a visited node is not hidden
            # merely because old evidence filled the prompt first.
            for observation in reversed(observations):
                state["observations"].insert(0, observation)
                if count_state(state) > max_input:
                    state["observations"].pop(0)
                    break
            for block_id, row in reversed(list(evidence.items())):
                state["evidence"][block_id] = row
                if count_state(state) > max_input:
                    del state["evidence"][block_id]
            return state

        def finish(args, step):
            if set(args) - {"answer", "citation_ids", "insufficient", "answer_scope"}:
                raise ValueError("Unknown finish arguments")
            answer, ids = args.get("answer"), args.get("citation_ids", [])
            insufficient, scope = args.get("insufficient", False), args.get("answer_scope", "source")
            if not isinstance(answer, str) or not answer.strip() or not isinstance(insufficient, bool):
                raise ValueError("finish requires answer text and boolean insufficient")
            known = {**summary_evidence, **evidence}
            if not isinstance(ids, list) or any(not isinstance(i, str) or i not in known for i in ids):
                raise ValueError("Citations must reference blocks actually read or in the system directory")
            if scope not in {"source", "overview"}:
                raise ValueError("answer_scope must be source or overview")
            ids = list(dict.fromkeys(ids))
            inline = set(re.findall(r"\[(n\d+:b\d+)\]", answer))
            if not inline <= set(ids):
                raise ValueError("Inline citations must be listed in citation_ids")
            if not insufficient:
                if not ids:
                    raise ValueError("A supported answer requires citations")
                if scope == "source" and not any(i in evidence for i in ids):
                    raise ValueError("Source-scope answers need a read source leaf; use overview scope for directory-only synthesis")
            trace.append({"step": step, "tool": "finish", "args": args})
            return AgentResult(answer, [{"block_id": i, **known[i]} for i in ids],
                               "insufficient" if insufficient else "complete", trace)

        async def execute(action, step):
            tool, args = action["tool"], action["args"]
            try:
                signature = json.dumps(action, sort_keys=True)
                repeats[signature] = repeats.get(signature, 0) + 1
                if repeats[signature] > 2:
                    raise ValueError("Repeated identical action; choose an unread branch or finish")
                if tool == "search":
                    result = await tools.search(**args)
                elif tool == "move_up":
                    result = tools.move_up(**args)
                elif tool == "move_down":
                    result = tools.move_down(**args)
                else:
                    raise ValueError("Unknown navigation tool")
                return {"step": step, "tool": tool, "args": args, "result": result}
            except (ValueError, TypeError, KeyError) as exc:
                return {"step": step, "tool": "error", "error": str(exc)[:300]}

        for step in range(self.config.max_steps):
            state = state_for(step)
            visited_before = set(tools.session.visited)
            notes_before, observations_before = notes, list(observations)
            try:
                raw = await self.policy.decide(state)
                if not isinstance(raw, dict):
                    raise ValueError("Expected an action object")
                actions = raw.get("actions") if set(raw) == {"actions"} else [raw]
                if not isinstance(actions, list) or not 1 <= len(actions) <= self.config.max_parallel_actions:
                    raise ValueError("Invalid number of parallel actions")
                for action in actions:
                    if not isinstance(action, dict) or set(action) != {"tool", "args"} or not isinstance(action["tool"], str) or not isinstance(action["args"], dict):
                        raise ValueError("Expected exactly tool and args for each action")
                if len(actions) > 1 and any(a["tool"] not in {"search", "move_up", "move_down"} for a in actions):
                    raise ValueError("Only independent read tools can run in parallel")
                tool, args = actions[0]["tool"], actions[0]["args"]
                if tool == "finish":
                    return finish(args, step)
                # Budget the total batch, reserving room for JSON framing and
                # observations. Each record is whole, never silently truncated.
                free = max_input - count_state(base_state(step))
                per_action = min(self.tools.response_budget, free // (3 * len(actions)))
                if per_action < 512:
                    raise ValueError("Directory leaves insufficient tool workspace; use a larger context or explicit budgeted directory")
                tools.response_budget = per_action
                if tool == "compact_context":
                    if set(args) - {"notes", "keep_node_ids"}:
                        raise ValueError("Unknown compact_context arguments")
                    new_notes, keep = args.get("notes", ""), args.get("keep_node_ids", [])
                    if not isinstance(new_notes, str) or not isinstance(keep, list) or len(keep) > 10 or any(not isinstance(i, str) or i not in tools.session.cache for i in keep):
                        raise ValueError("Compaction restores only previously read cached nodes")
                    result = tools.read(keep, from_cache=True)
                    notes = prefix(new_notes, self.config.notes_budget, self.tokenizer)
                    observations.clear()
                    result["notes"] = notes
                    result["preserved_source_ids"] = list(evidence)[-50:]
                    events = [{"step": step, "tool": tool, "args": args, "result": result}]
                else:
                    # Shared session makes read/visit commits atomic between
                    # awaits. Parallel branches cannot return a node twice.
                    events = await asyncio.gather(*(execute(a, step) for a in actions))
                observation = {"actions": [
                    {key: value for key, value in event.items() if key in {"tool", "result", "error"}}
                    for event in events]}
                candidate = base_state(step)
                candidate["observations"] = [observation]
                if count_state(candidate) > max_input:
                    # A node counts as visited only if its complete result can
                    # actually reach the next policy request.
                    new_visits = tools.session.visited - visited_before
                    tools.session.visited.difference_update(new_visits)
                    tools.session.order[:] = [i for i in tools.session.order if i not in new_visits]
                    for node_id in new_visits:
                        tools.session.cache.pop(node_id, None)
                    notes, observations[:] = notes_before, observations_before
                    raise ValueError("Tool batch exceeds remaining context; reduce top_k, limit or parallel actions")
                for event in events:
                    remember(event.get("result", {}).get("nodes", []))
                    event["input_units"] = count_state(state)
                    trace.append(event)
                observations.append(observation)
            except (ValueError, TypeError, KeyError) as exc:
                observation = {"tool": "error", "error": str(exc)[:300]}
                observations.append(observation)
                trace.append({"step": step, **observation})
        return AgentResult("Exploration budget exhausted before a supported final answer was produced.",
                           [], "budget_exhausted", trace)
