"""Names of the Redis streams and keys the services talk through (ADR-004, ADR-011).

    google-gateway --EmailTask--------> EMAIL_TASKS ---------> agent
    agent ---------FreeBusyRequest----> FREE_BUSY_REQUESTS --> google-gateway
    google-gateway --FreeBusyReply----> free_busy_reply_key(request_id) --> agent
    agent ---------AgentPlan----------> AGENT_PLANS ---------> google-gateway

A free/busy reply goes to a key named after its request (read with BLPOP), so only the
agent that asked receives it, even with several agent replicas.
"""

from uuid import UUID

EMAIL_TASKS = "agent:email-tasks"
FREE_BUSY_REQUESTS = "gateway:free-busy-requests"
AGENT_PLANS = "gateway:agent-plans"
# Approximate cap on every stream, so a stuck consumer cannot grow Redis without limit.
STREAM_MAX_LENGTH = 10_000
# How long a reply waits to be picked up before Redis drops it.
REPLY_TTL_SECONDS = 60


def free_busy_reply_key(request_id: UUID) -> str:
    return f"free-busy-reply:{request_id}"
