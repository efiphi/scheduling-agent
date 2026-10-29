"""The agent's flow as a LangGraph state graph (ADR-002). One email in, one plan out.

    extract --(not a request / unclear)--------------------------> plan
       |
       +--(meeting request)--> free_busy --> choose_slots ---------> plan

Each node is one step; the edges are code, so a manipulated model cannot add a step or
skip one (T1-T7). Only `extract` calls the model. The graph returns an AgentPlan, which
the gateway's policy guard checks again before anything reaches the user (invariant 3).

No checkpoints: a task runs start to finish in seconds, and the human approval happens
outside the graph, as a database record (invariant 4). A crash mid-task is covered by the
queue instead: the task is acknowledged only after its plan is published (worker.py).
"""

from collections.abc import Callable
from datetime import datetime
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.extraction import (
    Extraction,
    FormFiller,
    MeetingRequest,
    NotAMeeting,
    Unclear,
    Usage,
    extract,
)
from agent.free_busy import FreeBusyClient
from agent.slots import pick_slots, search_window
from shared.messages import (
    AgentPlan,
    AskUser,
    EmailTask,
    FreeBusyRequest,
    Interval,
    NotAMeetingRequest,
    PlanDecision,
    ProposeSlots,
)

CALENDAR_UNAVAILABLE = "לא הצלחתי לבדוק את היומן כרגע. לנסות שוב, או שתציע מועדים בעצמך?"
NO_FREE_SLOTS = "אין מועדים פנויים בטווח שהשולח ביקש. להציע טווח אחר?"


class AgentState(TypedDict, total=False):
    task: EmailTask
    extraction: Extraction
    usage: Usage
    calendar_ok: bool
    busy: tuple[Interval, ...]
    slots: tuple[Interval, ...]
    plan: AgentPlan


def build_graph(
    filler: FormFiller, free_busy: FreeBusyClient, clock: Callable[[], datetime]
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    def extract_node(state: AgentState) -> AgentState:
        task = state["task"]
        result = extract(task.email, task.context, filler)
        return {"extraction": result.extraction, "usage": result.usage}

    def after_extract(state: AgentState) -> str:
        return "free_busy" if isinstance(state["extraction"], MeetingRequest) else "plan"

    def free_busy_node(state: AgentState) -> AgentState:
        task, request = state["task"], _meeting_request(state)
        reply = free_busy.ask(
            FreeBusyRequest(
                request_id=uuid4(),
                task_id=task.task_id,
                user_id=task.user_id,
                window=search_window(request, task.context),
            )
        )
        if reply is None or reply.status != "ok":
            return {"calendar_ok": False, "busy": ()}
        return {"calendar_ok": True, "busy": reply.busy}

    def after_free_busy(state: AgentState) -> str:
        return "choose_slots" if state["calendar_ok"] else "plan"

    def choose_slots_node(state: AgentState) -> AgentState:
        request = _meeting_request(state)
        return {"slots": pick_slots(request, state["task"].context, state["busy"])}

    def plan_node(state: AgentState) -> AgentState:
        task = state["task"]
        plan = AgentPlan(
            task_id=task.task_id,
            user_id=task.user_id,
            thread_id=task.thread_id,
            decision=decide(state),
            created_at=clock(),
        )
        return {"plan": plan}

    graph = StateGraph(AgentState)
    graph.add_node("extract", extract_node)
    graph.add_node("free_busy", free_busy_node)
    graph.add_node("choose_slots", choose_slots_node)
    graph.add_node("plan", plan_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", after_extract, ["free_busy", "plan"])
    graph.add_conditional_edges("free_busy", after_free_busy, ["choose_slots", "plan"])
    graph.add_edge("choose_slots", "plan")
    graph.add_edge("plan", END)
    return graph.compile()


def _meeting_request(state: AgentState) -> MeetingRequest:
    # The edges only route a MeetingRequest here; anything else is a bug in the graph.
    request = state["extraction"]
    if not isinstance(request, MeetingRequest):
        raise TypeError("this node runs only for meeting requests")
    return request


def decide(state: AgentState) -> PlanDecision:
    extraction = state["extraction"]
    if isinstance(extraction, NotAMeeting):
        return NotAMeetingRequest(kind="not_a_meeting_request")
    if isinstance(extraction, Unclear):
        return AskUser(kind="ask_user", question=extraction.question)
    if not state.get("calendar_ok"):
        return AskUser(kind="ask_user", question=CALENDAR_UNAVAILABLE)
    slots = state.get("slots", ())
    if not slots:
        return AskUser(kind="ask_user", question=NO_FREE_SLOTS)
    return ProposeSlots(
        kind="propose_slots",
        language=extraction.language,
        duration_minutes=extraction.duration_minutes,
        slots=slots,
        opening_line=extraction.opening_line,
    )


def run(
    graph: CompiledStateGraph[AgentState, None, AgentState, AgentState], task: EmailTask
) -> tuple[AgentPlan, Usage]:
    final = graph.invoke({"task": task})
    return final["plan"], final["usage"]
