import uuid
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.middleware.metrics import ACTIVE_TASKS, TOKENS_USED
from app.services.episodic_memory import episodic_memory
from app.services.keyword_memory import keyword_memory
from app.services.llm import LLMResponse, get_llm_provider
from app.services.llm_usage import log_llm_usage
from app.services.vector_memory import vector_memory

logger = get_logger(__name__)
settings = get_settings()

ProgressCallback = Callable[[str, str, dict[str, Any]], Any]

SYSTEM_PROMPT = (
    "You are an expert AI agent in a multi-agent orchestration system. "
    "Be concise, structured, and actionable."
)


class OrchestratorState(TypedDict):
    goal: str
    mode: str
    context: str
    decomposed_steps: list[str]
    agent_results: list[dict[str, Any]]
    synthesis: str
    tokens_used: int
    status: str
    llm_provider: str


class LangGraphOrchestrator:
    """LangGraph ensemble orchestrator with memory, LLM fallback, and token logging."""

    def __init__(self) -> None:
        self._graph = self._build_graph()
        self._llm = get_llm_provider()
        self._db: AsyncSession | None = None
        self._user_id: uuid.UUID | None = None
        self._goal_id: uuid.UUID | None = None

    def _build_graph(self):
        graph = StateGraph(OrchestratorState)

        graph.add_node("load_context", self._load_context)
        graph.add_node("decompose", self._decompose)
        graph.add_node("execute_agents", self._execute_agents)
        graph.add_node("synthesize", self._synthesize)
        graph.add_node("evaluate", self._evaluate)

        graph.set_entry_point("load_context")
        graph.add_edge("load_context", "decompose")
        graph.add_edge("decompose", "execute_agents")
        graph.add_edge("execute_agents", "synthesize")
        graph.add_edge("synthesize", "evaluate")
        graph.add_edge("evaluate", END)

        return graph.compile()

    async def _call_llm(self, prompt: str, *, node: str, system: str | None = None) -> LLMResponse:
        response = await self._llm.complete(prompt, system=system)
        if self._db is not None:
            await log_llm_usage(
                self._db,
                response=response,
                user_id=self._user_id,
                goal_id=self._goal_id,
                node=node,
                prompt_preview=prompt[:500],
            )
        return response

    async def _load_context(self, state: OrchestratorState) -> dict[str, Any]:
        return {
            "context": state.get("context", ""),
            "status": "loading_context",
            "llm_provider": self._llm.active_provider,
        }

    async def _decompose(self, state: OrchestratorState) -> dict[str, Any]:
        goal = state["goal"]
        context = state.get("context", "")
        prompt = (
            f"Decompose this goal into 4 concrete steps.\n"
            f"Goal: {goal}\nContext: {context or 'none'}\n"
            f"Return JSON array of step strings only."
        )
        response = await self._call_llm(prompt, node="decompose", system=SYSTEM_PROMPT)
        steps = self._parse_steps(response.text, goal)
        return {
            "decomposed_steps": steps,
            "status": "decomposed",
            "tokens_used": state.get("tokens_used", 0) + response.tokens_used,
            "llm_provider": response.provider,
        }

    async def _execute_agents(self, state: OrchestratorState) -> dict[str, Any]:
        mode = state.get("mode", "ensemble")
        agents = ["researcher", "executor", "reviewer"] if mode == "ensemble" else ["executor"]
        results: list[dict[str, Any]] = []
        total_tokens = state.get("tokens_used", 0)
        last_provider = state.get("llm_provider", self._llm.active_provider)

        for i, step in enumerate(state.get("decomposed_steps", [])):
            for agent in agents:
                prompt = (
                    f"Agent role: {agent}\nStep: {step}\n"
                    f"Goal: {state['goal']}\nContext: {state.get('context', '')}\n"
                    f"Provide a short result."
                )
                response = await self._call_llm(
                    prompt, node=f"agent_{agent}", system=SYSTEM_PROMPT
                )
                total_tokens += response.tokens_used
                last_provider = response.provider
                results.append(
                    {
                        "agent": agent,
                        "step": step,
                        "step_index": i,
                        "output": response.text,
                        "confidence": 0.9,
                        "provider": response.provider,
                    }
                )

        return {
            "agent_results": results,
            "status": "executed",
            "tokens_used": total_tokens,
            "llm_provider": last_provider,
        }

    async def _synthesize(self, state: OrchestratorState) -> dict[str, Any]:
        outputs = "\n".join(
            f"- [{r['agent']}] {r['output'][:500]}" for r in state.get("agent_results", [])
        )
        prompt = (
            f"Synthesize a final answer for the user.\n"
            f"Goal: {state['goal']}\nContext: {state.get('context', '')}\n"
            f"Agent outputs:\n{outputs}"
        )
        response = await self._call_llm(prompt, node="synthesize", system=SYSTEM_PROMPT)
        return {
            "synthesis": response.text,
            "status": "synthesized",
            "tokens_used": state.get("tokens_used", 0) + response.tokens_used,
            "llm_provider": response.provider,
        }

    async def _evaluate(self, state: OrchestratorState) -> dict[str, Any]:
        prompt = (
            f"Rate completion 0-100 and give one-line verdict.\n"
            f"Goal: {state['goal']}\nSynthesis: {state.get('synthesis', '')[:1000]}"
        )
        response = await self._call_llm(prompt, node="evaluate", system=SYSTEM_PROMPT)
        return {
            "status": "completed",
            "tokens_used": state.get("tokens_used", 0) + response.tokens_used,
            "llm_provider": response.provider,
        }

    @staticmethod
    def _parse_steps(text: str, goal: str) -> list[str]:
        import json

        try:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, list) and parsed:
                    return [str(s) for s in parsed[:6]]
        except json.JSONDecodeError:
            pass
        return [
            f"Analyze: {goal[:200]}",
            f"Research: {goal[:200]}",
            f"Execute: {goal[:200]}",
            f"Validate: {goal[:200]}",
        ]

    async def run(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        goal_id: uuid.UUID,
        goal_text: str,
        mode: str = "ensemble",
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        ACTIVE_TASKS.inc()
        self._db = db
        self._user_id = user_id
        self._goal_id = goal_id
        try:
            user_key = str(user_id)

            keyword_hits = keyword_memory.search(user_key, goal_text, limit=3)
            vector_hits = await vector_memory.search(user_key, goal_text, limit=3)
            context_parts = [h["content"] for h in keyword_hits] + [h["content"] for h in vector_hits]
            context = "\n".join(context_parts) if context_parts else ""

            await episodic_memory.save_step(
                db,
                user_id=user_id,
                goal_id=goal_id,
                step_type="start",
                content=f"Starting orchestration: {goal_text}",
                metadata={"mode": mode, "llm_provider": self._llm.active_provider},
            )
            if on_progress:
                await on_progress("start", "Orchestration started", {"mode": mode})

            current: OrchestratorState = {
                "goal": goal_text,
                "mode": mode,
                "context": context,
                "decomposed_steps": [],
                "agent_results": [],
                "synthesis": "",
                "tokens_used": 0,
                "status": "pending",
                "llm_provider": self._llm.active_provider,
            }

            for node_name in ["load_context", "decompose", "execute_agents", "synthesize", "evaluate"]:
                update = await getattr(self, f"_{node_name}")(current)
                current.update(update)

                await episodic_memory.save_step(
                    db,
                    user_id=user_id,
                    goal_id=goal_id,
                    step_type=node_name,
                    content=str(update.get("synthesis") or update.get("decomposed_steps") or update)[:4000],
                    metadata={
                        "status": current.get("status"),
                        "node": node_name,
                        "llm_provider": current.get("llm_provider"),
                    },
                )
                if on_progress:
                    await on_progress(node_name, f"Completed node: {node_name}", update)

            keyword_memory.add(user_key, goal_text, {"goal_id": str(goal_id)})
            await vector_memory.add(
                user_key,
                current.get("synthesis", goal_text),
                {"goal_id": str(goal_id), "mode": mode},
            )

            TOKENS_USED.labels(user_id=str(user_id)).inc(current.get("tokens_used", 0))

            return {
                "status": "completed",
                "synthesis": current.get("synthesis", ""),
                "agent_results": current.get("agent_results", []),
                "tokens_used": current.get("tokens_used", 0),
                "mode": mode,
                "llm_provider": current.get("llm_provider", self._llm.active_provider),
            }
        finally:
            ACTIVE_TASKS.dec()
            self._db = None
            self._user_id = None
            self._goal_id = None


orchestrator = LangGraphOrchestrator()