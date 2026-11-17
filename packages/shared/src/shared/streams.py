"""Names of the Redis streams and keys the services talk through (ADR-004, ADR-011).

    google-gateway --EmailTask--------> EMAIL_TASKS ---------> agent
    agent ---------FreeBusyRequest----> FREE_BUSY_REQUESTS --> google-gateway
    google-gateway --FreeBusyReply----> free_busy_reply_key(request_id) --> agent
    agent ---------AgentPlan----------> AGENT_PLANS ---------> google-gateway
    api -----------approved action id-> APPROVED_ACTIONS ----> google-gateway (executes)
    google-gateway --new action id----> NOTIFICATIONS -------> api (tells the user on WhatsApp)

A free/busy reply goes to a key named after its request (read with BLPOP), so only the
agent that asked receives it, even with several agent replicas.
"""

from uuid import UUID

EMAIL_TASKS = "agent:email-tasks"
FREE_BUSY_REQUESTS = "gateway:free-busy-requests"
AGENT_PLANS = "gateway:agent-plans"
# Only an action id and a user id: the gateway re-reads the action and its approval from
# the database and re-checks both before executing (invariants 3 and 4).
APPROVED_ACTIONS = "gateway:approved-actions"
# A new pending action, by id only: the api reads it from the database before telling the
# user, so nothing on the stream decides what the user sees.
NOTIFICATIONS = "api:notifications"
# Approximate cap on every stream, so a stuck consumer cannot grow Redis without limit.
STREAM_MAX_LENGTH = 10_000
# How long a reply waits to be picked up before Redis drops it.
REPLY_TTL_SECONDS = 60


# Consumers wait up to 5 seconds for new messages (XREADGROUP BLOCK). redis-py 8 gives up
# on any read after 5 seconds by default, the same moment, so an idle queue raced into a
# TimeoutError and crashed its process. Every client reads with this longer timeout.
REDIS_SOCKET_TIMEOUT_SECONDS = 30


def free_busy_reply_key(request_id: UUID) -> str:
    return f"free-busy-reply:{request_id}"
