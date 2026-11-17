from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .budget import TurnBudget, detach_turn, start_turn
from .config import AgenticSettings
from .graph import AgenticShoppingGraph
from .marketplace import MarketplaceClient, MarketplaceError
from .memory import extend_backlog, split_history
from .models import GeminiGateway
from .policy import PolicyRetriever
from .rerank import CrossEncoderReranker
from .retrieval import StructuredProductRetriever
from .schemas import ChatRequest, ChatResponse, PendingAction
from .visual import VisualSearch

log = logging.getLogger(__name__)

_STREAM_STATUS = {
    "understand": "Đang hiểu yêu cầu…",
    "plan": "Đang lập kế hoạch…",
    "retrieve": "Đang tìm và xếp hạng sản phẩm…",
    "web_expand": "Catalog chưa có mẫu khớp, đang tra cứu web để mở rộng tìm kiếm…",
    "research_side": "Đang tra cứu thông tin trên web…",
    "relax": "Không có mẫu khớp hoàn toàn, đang nới điều kiện…",
    "product_detail": "Đang đọc thông tin sản phẩm…",
    "policy": "Đang tra cứu chính sách…",
    "policy_side": "Đang tra cứu chính sách…",
    "cart_view": "Đang đọc giỏ hàng…",
    "prepare_cart": "Đang chuẩn bị thao tác giỏ hàng…",
    "prepare_checkout": "Đang chuẩn bị thanh toán…",
    "order_status": "Đang tra cứu đơn hàng…",
    "collect": "Đang soạn câu trả lời…",
    "plan_done": "Đang tra cứu và soạn câu trả lời…",
}

# Nodes whose model output is the reply the customer reads.
_REPLY_NODES = {"advisor", "finalize", "policy"}


class TokenRelay:
    """Turns LangGraph message chunks into the widget's token stream.

    Only reply-writing nodes are relayed. A generation that turns out to be a
    tool call (the advisor deciding to search) is not the reply: what it
    streamed is withdrawn with a "reset" event, as is a draft followed by
    another generation (an advisor step after a preamble, or the graph's
    answer after a failed advisor). The final event carries the reply text
    that counts.
    """

    def __init__(self):
        self.current = None
        self.sent = False
        self.tool_steps: set = set()

    def feed(self, message, metadata) -> list[tuple[str, dict]]:
        node = (metadata or {}).get("langgraph_node")
        if node not in _REPLY_NODES:
            return []
        key = (node, getattr(message, "id", None) or (metadata or {}).get("langgraph_checkpoint_ns"))
        events: list[tuple[str, dict]] = []
        if getattr(message, "tool_call_chunks", None) or getattr(message, "tool_calls", None):
            self.tool_steps.add(key)
            if key == self.current and self.sent:
                events.append(("reset", {}))
            if key == self.current:
                self.current, self.sent = None, False
            return events
        if key in self.tool_steps:
            return events
        text = str(message.text) if isinstance(getattr(message, "text", None), str) else ""
        if not text:
            return events
        if key != self.current:
            if self.sent:
                events.append(("reset", {}))
            self.current, self.sent = key, False
        events.append(("token", {"text": text}))
        self.sent = True
        return events


async def _latest_committed(graph, config):
    snapshot = await graph.aget_state(config)
    while snapshot and snapshot.values and not snapshot.values.get("committed"):
        snapshot = (
            await graph.aget_state(snapshot.parent_config)
            if snapshot.parent_config
            else None
        )
    return snapshot if snapshot and snapshot.values else None


@dataclass
class _Turn:
    session_id: str
    config: dict
    previous: dict
    user_id: str
    bound_user: str
    state: dict
    started: float


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, MarketplaceError):
        status = error.status if 400 <= error.status < 500 else 503
        return HTTPException(status, str(error))
    if isinstance(error, asyncio.TimeoutError):
        return HTTPException(504, "Agent xử lý quá lâu. Vui lòng thử lại.")
    log.error("Agentic RAG request failed", exc_info=error)
    return HTTPException(503, "Agentic RAG tạm thời chưa xử lý được yêu cầu.")


def create_agentic_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings = AgenticSettings()
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        checkpoint_context = AsyncSqliteSaver.from_conn_string(
            str(Path(settings.data_dir) / "agentic_checkpoints.sqlite")
        )
        checkpointer = await checkpoint_context.__aenter__()
        models = GeminiGateway(settings)
        marketplace = MarketplaceClient(settings)
        retriever = StructuredProductRetriever(settings, models)
        policy = PolicyRetriever(settings, models)
        reranker = CrossEncoderReranker(settings)
        visual = VisualSearch(settings)
        agent = AgenticShoppingGraph(
            settings, models, retriever, marketplace, policy=policy, checkpointer=checkpointer,
            reranker=reranker, visual=visual,
        )
        application.state.settings = settings
        application.state.models = models
        application.state.marketplace = marketplace
        application.state.retriever = retriever
        application.state.policy = policy
        application.state.visual = visual
        application.state.agent = agent
        application.state.checkpointer = checkpointer
        application.state.busy_sessions = set()
        # session_id -> the background task folding old messages into the
        # session's summary; the next turn of that session waits for it.
        application.state.summary_tasks = {}
        try:
            yield
        finally:
            for task in list(application.state.summary_tasks.values()):
                task.cancel()
            await retriever.close()
            await policy.close()
            await reranker.close()
            await visual.close()
            await marketplace.close()
            await models.close()
            await checkpoint_context.__aexit__(None, None, None)

    application = FastAPI(
        title="Agentic RAG Shopping Service",
        version="0.2.0",
        lifespan=lifespan,
    )

    @application.get("/assistant/health")
    async def agentic_health():
        try:
            vector = await application.state.retriever.health()
            policy = await application.state.policy.health()
            try:
                visual = await application.state.visual.health()
            except Exception as error:
                # Photo search is optional: text chat stays ready without it.
                visual = {"exists": False, "error": type(error).__name__}
            policy_ready = bool(policy["exists"] and policy["points"] > 0)
            ready = bool(
                vector["exists"]
                and vector["dimensionMatches"]
                and vector.get("catalogComplete", False)
                and vector.get("hybridReady", False)
                and policy_ready
            )
            return {
                "status": "ready" if ready else "warming_up",
                "llmProvider": application.state.settings.llm_provider,
                "model": application.state.settings.chat_model,
                "vector": vector,
                "policy": policy,
                "imageSearch": visual,
                "agents": {
                    "product": ["catalog_search", "product_detail", "policy", "web_research"],
                    "order": ["cart", "checkout", "order_status"],
                    "llmFirst": application.state.settings.llm_first,
                    "webSearch": application.state.settings.web_search_enabled,
                },
                "rerank": {
                    "mode": application.state.settings.rerank_mode,
                    "crossEncoder": application.state.settings.rerank_enabled,
                    "candidates": application.state.settings.rerank_candidates,
                    "llmCandidates": application.state.settings.llm_rerank_candidates,
                    "topK": application.state.settings.result_limit,
                },
                "semanticSchemaVersion": vector.get("semanticSchemaVersion"),
                "specCoverage": vector.get("specCoverage", 0),
                "policyReady": policy_ready,
                "readOnlyVectorStore": True,
            }
        except Exception as error:
            log.exception("Agentic RAG health check failed")
            raise HTTPException(503, f"Không kết nối được Qdrant: {type(error).__name__}")

    def _claim(session_id: str):
        busy = application.state.busy_sessions
        if session_id in busy:
            raise HTTPException(409, "Vui lòng chờ lượt xử lý trước hoàn tất.")
        busy.add(session_id)

    def _summary_tasks() -> dict:
        tasks = getattr(application.state, "summary_tasks", None)
        if tasks is None:
            tasks = application.state.summary_tasks = {}
        return tasks

    async def _await_summary(session_id: str) -> None:
        """A turn reads the session only after the previous turn's summary
        is written, so the two never overwrite each other's state."""
        task = _summary_tasks().get(session_id)
        if task is None or task.done():
            return
        try:
            await asyncio.shield(task)
        except Exception:
            # The task logs its own failure; the backlog stays for a retry.
            pass

    async def _summarize_session(session_id: str, config: dict) -> None:
        detach_turn()
        graph = application.state.agent.graph
        try:
            snapshot = await _latest_committed(graph, config)
            values = snapshot.values if snapshot else {}
            backlog = list(values.get("summary_backlog") or [])
            if not backlog:
                return
            summary = await application.state.models.summarize(
                str(values.get("conversation_summary") or ""), backlog
            )
            # Only the folded messages leave the backlog; anything appended
            # meanwhile stays for the next run.
            latest = await _latest_committed(graph, config)
            current = list((latest.values if latest else {}).get("summary_backlog") or [])
            remaining = current[len(backlog):] if current[: len(backlog)] == backlog else current
            await graph.aupdate_state(
                config,
                {"conversation_summary": summary, "summary_backlog": remaining},
                as_node="finalize",
            )
            log.info(
                "agentic_summary session=%s folded=%d summary_chars=%d",
                session_id[:8], len(backlog), len(summary),
            )
        except Exception as error:
            log.warning(
                "summary failed, backlog kept: %s: %s", type(error).__name__, str(error)[:200]
            )
        finally:
            tasks = _summary_tasks()
            if tasks.get(session_id) is asyncio.current_task():
                tasks.pop(session_id, None)

    def _schedule_summary(session_id: str, config: dict) -> None:
        tasks = _summary_tasks()
        running = tasks.get(session_id)
        if running is not None and not running.done():
            return
        tasks[session_id] = asyncio.create_task(_summarize_session(session_id, config))

    async def _open_turn(
        request: ChatRequest, http_request: Request, session_id: str
    ) -> _Turn:
        settings = application.state.settings
        config = {"configurable": {"thread_id": session_id}}
        await _await_summary(session_id)
        snapshot = (
            await _latest_committed(application.state.agent.graph, config)
            if request.sessionId
            else None
        )
        if request.sessionId and (
            not snapshot
            or snapshot.values.get("session_expires_at", 0) <= time.time()
        ):
            if snapshot:
                await application.state.checkpointer.adelete_thread(session_id)
            raise HTTPException(
                410, "Phiên chat đã hết hạn. Hãy bắt đầu cuộc trò chuyện mới."
            )
        previous = snapshot.values if snapshot else {}
        user_id = str(http_request.headers.get("x-user-id", "")).strip()
        role = str(http_request.headers.get("x-user-role", "")).strip()
        bound_user = str(previous.get("user_id", "")).strip()
        if bound_user and bound_user != user_id:
            raise HTTPException(403, "Phiên chat thuộc về một tài khoản khác.")
        state = {
            "message": request.message.strip(),
            "user_id": user_id or bound_user,
            "role": role,
            "session_id": session_id,
            "history": previous.get("history", []),
            "conversation_summary": previous.get("conversation_summary", ""),
            "summary_backlog": previous.get("summary_backlog", []),
            "shopper_profile": previous.get("shopper_profile", {}),
            "request": request.model_dump(),
            "understanding": {},
            "semantic_turn": {},
            "search_context": previous.get("search_context", {}),
            "last_search": previous.get("last_search", {}),
            "plan": {},
            "query": "",
            "retrieval_rounds": 0,
            "retrieval_hits": [],
            "products": [],
            "render_product_cards": True,
            "tool_result": {},
            "answer": "",
            "pending_action": previous.get("pending_action"),
            "focused_products": previous.get("focused_products", []),
            "active_product_id": previous.get("active_product_id"),
            "selected_options": previous.get(
                "selected_options", {"colors": [], "sizes": []}
            ),
            "shopping_phase": previous.get("shopping_phase", "exploring"),
            "cart_lines_added": previous.get("cart_lines_added", []),
            "warnings": [],
            "sources": [],
            "suggestions": [],
            "handoff": False,
            "skipped_tasks": [],
            "policy_appendix": "",
            "policy_sources": [],
            "web_research": {},
            "expanded_queries": [],
            "extra_searches": [],
            "extra_results": [],
            "clarify_count": int(previous.get("clarify_count") or 0),
            "last_clarify_key": previous.get("last_clarify_key", ""),
            "route": "",
            "session_expires_at": time.time() + settings.session_ttl,
            "committed": False,
        }
        return _Turn(
            session_id=session_id,
            config=config,
            previous=previous,
            user_id=user_id,
            bound_user=bound_user,
            state=state,
            started=time.monotonic(),
        )

    async def _commit_turn(
        turn: _Turn, request: ChatRequest, result: dict, budget: TurnBudget
    ) -> ChatResponse:
        settings = application.state.settings
        previous = turn.previous
        semantic = result.get("semantic_turn") or {}
        log.info(
            "agentic_turn route=%s confidence=%.3f clarification=%s verifier=%s rounds=%s "
            "llm_calls=%d llm_kinds=%s budget_exhausted=%s latency_ms=%d warnings=%s",
            result.get("route", "general"),
            float(semantic.get("confidence") or 0),
            bool(semantic.get("needs_clarification")),
            bool((result.get("tool_result") or {}).get("verification")),
            result.get("retrieval_rounds", 0),
            budget.calls,
            ",".join(budget.kinds),
            budget.exhausted,
            int((time.monotonic() - turn.started) * 1000),
            ",".join(result.get("warnings", [])),
        )
        rewritten = str(semantic.get("standalone_query") or "").strip()
        if rewritten and rewritten != (request.message or "").strip():
            # What the model understood the message to mean: the evaluation
            # record of query rewriting (shown only when it differs).
            log.info("agentic_rewrite original=%r standalone=%r", request.message[:300], rewritten[:300])
        history, evicted = split_history(
            [
                *previous.get("history", []),
                {"role": "user", "content": request.message or "[Hành động UI]"},
                {"role": "assistant", "content": result["answer"]},
            ],
            settings.history_keep_messages,
            settings.history_max_messages,
        )
        backlog = extend_backlog(previous.get("summary_backlog"), evicted)
        pending = result.get("pending_action")
        await application.state.agent.graph.aupdate_state(
            turn.config,
            {
                "history": history,
                "summary_backlog": backlog,
                "shopper_profile": result.get(
                    "shopper_profile", previous.get("shopper_profile", {})
                ),
                "user_id": turn.user_id or turn.bound_user,
                "pending_action": pending,
                "focused_products": result.get(
                    "focused_products", previous.get("focused_products", [])
                ),
                "active_product_id": result.get("active_product_id"),
                "selected_options": result.get(
                    "selected_options", previous.get("selected_options", {})
                ),
                "search_context": result.get(
                    "search_context", previous.get("search_context", {})
                ),
                "shopping_phase": result.get(
                    "shopping_phase", previous.get("shopping_phase", "exploring")
                ),
                "cart_lines_added": result.get(
                    "cart_lines_added", previous.get("cart_lines_added", [])
                ),
                "clarify_count": int(result.get("clarify_count") or 0),
                "last_clarify_key": result.get("last_clarify_key", ""),
                "session_expires_at": time.time() + settings.session_ttl,
                "committed": True,
            },
            as_node="finalize",
        )
        if backlog and settings.summary_enabled:
            _schedule_summary(turn.session_id, turn.config)
        public_pending = (
            PendingAction.model_validate(pending).public() if pending else None
        )
        tool_result = result.get("tool_result") or {}
        action_result = (
            tool_result.get("result")
            if isinstance(tool_result, dict) and tool_result.get("success")
            else tool_result
        )
        return ChatResponse(
            sessionId=turn.session_id,
            answer=result["answer"],
            products=(
                result.get("products", [])
                if result.get("render_product_cards", True)
                else []
            ),
            route=result.get("route", "general"),
            retrievalRounds=result.get("retrieval_rounds", 0),
            pendingAction=public_pending,
            actionResult=action_result,
            warnings=result.get("warnings", []),
            sources=result.get("sources", []),
            suggestions=result.get("suggestions", []),
            handoff=bool(result.get("handoff")),
            selection=(
                tool_result.get("selection")
                if isinstance(tool_result, dict) and isinstance(tool_result.get("selection"), dict)
                else None
            ),
        )

    def _start_budget() -> TurnBudget:
        settings = application.state.settings
        return start_turn(settings.max_llm_calls, settings.turn_deadline)

    @application.post("/assistant/chat", response_model=ChatResponse)
    async def agentic_chat(request: ChatRequest, http_request: Request):
        session_id = request.sessionId or secrets.token_urlsafe(32)
        _claim(session_id)
        try:
            turn = await _open_turn(request, http_request, session_id)
            budget = _start_budget()
            result = await asyncio.wait_for(
                application.state.agent.graph.ainvoke(
                    turn.state, config=turn.config, durability="exit"
                ),
                # Every model call is bounded by the budget; the margin only
                # covers deterministic tool calls after the deadline.
                timeout=application.state.settings.turn_deadline + 5,
            )
            return await _commit_turn(turn, request, result, budget)
        except HTTPException:
            raise
        except Exception as error:
            raise _http_error(error) from error
        finally:
            application.state.busy_sessions.discard(session_id)

    @application.post("/assistant/chat/stream")
    async def agentic_chat_stream(request: ChatRequest, http_request: Request):
        """Server-sent events: status, products, token, then one final ChatResponse."""
        session_id = request.sessionId or secrets.token_urlsafe(32)
        _claim(session_id)
        try:
            turn = await _open_turn(request, http_request, session_id)
        except HTTPException:
            application.state.busy_sessions.discard(session_id)
            raise
        except Exception as error:
            application.state.busy_sessions.discard(session_id)
            raise _http_error(error) from error

        def event(name: str, payload) -> str:
            return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        async def events():
            settings = application.state.settings
            budget = _start_budget()
            queue: asyncio.Queue = asyncio.Queue()

            async def produce():
                try:
                    async for mode, chunk in application.state.agent.graph.astream(
                        turn.state,
                        config=turn.config,
                        stream_mode=["updates", "messages"],
                        durability="exit",
                    ):
                        await queue.put((mode, chunk))
                    await queue.put(("done", None))
                except Exception as error:
                    await queue.put(("error", error))

            producer = asyncio.create_task(produce())
            deadline = time.monotonic() + settings.turn_deadline + 5
            result = dict(turn.state)
            sent_products = False
            relay = TokenRelay()
            # Feedback at once: understanding the turn alone takes seconds.
            yield event("status", {"node": "understand", "message": _STREAM_STATUS["understand"]})
            try:
                while True:
                    mode, chunk = await asyncio.wait_for(
                        queue.get(), timeout=max(deadline - time.monotonic(), 0.1)
                    )
                    if mode == "done":
                        break
                    if mode == "error":
                        raise chunk
                    if mode == "messages":
                        for name, payload in relay.feed(*chunk):
                            yield event(name, payload)
                        continue
                    for node, update in chunk.items():
                        if not update:
                            continue
                        result.update(update)
                        if node == "understand":
                            continue
                        if node == "plan":
                            yield event("status", {"node": "plan", "message": _STREAM_STATUS["plan_done"]})
                            continue
                        if node in _STREAM_STATUS:
                            yield event("status", {"node": node, "message": _STREAM_STATUS[node]})
                        if (
                            not sent_products
                            and update.get("products")
                            and result.get("render_product_cards", True)
                        ):
                            sent_products = True
                            yield event("products", {"products": update["products"]})
                response = await _commit_turn(turn, request, result, budget)
                yield event("final", response.model_dump())
            except Exception as error:
                failure = _http_error(error)
                yield event("error", {"status": failure.status_code, "detail": failure.detail})
            finally:
                producer.cancel()
                application.state.busy_sessions.discard(session_id)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return application


app = create_agentic_app()
