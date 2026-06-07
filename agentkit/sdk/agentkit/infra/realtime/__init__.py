"""Realtime backbone: Redis stream/pub-sub helpers above core.redis.

History, durable-delivery (outbox/DLQ), and safe-publish helpers used by the
agent runtime and the worker entrypoints. Sits beside ``infra/events`` (the
envelope layer) and above ``core.redis`` (the connection layer).
"""
