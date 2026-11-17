"""Database models and migrations for the scheduling agent.

Tables live in the `app` schema, owned by `scheduling_owner`. Services connect with their
own roles (`api_service`, `gateway_service`) and get access table by table, column by
column, through explicit GRANTs in the migrations (invariant 7, ADR-005).
"""
