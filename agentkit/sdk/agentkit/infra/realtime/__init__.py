"""Realtime backbone: Redis stream/pub-sub helpers.

History, durable-delivery (outbox/DLQ), and safe-publish helpers used by the
agent runtime and the worker entrypoints. Sits beside ``infra/events`` (the
envelope layer).
"""
