# Concurrency and Ordering

## Turn coordination

Turns for the same session serialize FIFO. Turns for different sessions may
run concurrently. The default coordinator is shared by runtimes that use the
same event-store object, but it is process-local. Separate processes do not
coordinate unless the application injects a distributed `TurnCoordinator` or
`SessionTurnCoordinator`.

Cancellation while waiting for the session lease removes the waiter. A
cancelled waiter must not block later turns.

## Event ordering

Persisted events have a contiguous, session-local `sequence`. Read, replay, and
subscription order is sequence order, never timestamp order. Timestamps remain
observability data and may be equal or move backward.

New writes use `NewKajiEvent` and become `StoredKajiEvent` only after the
journal assigns a sequence. Every runtime event from a turn carries the same
non-empty turn ID. Use `(session_id, sequence)` as the durable cursor and
`turn_id` for correlation.

## Bounded replay and context

A cold runtime pages the retained store once. A warm runtime reads only the
suffix after its projector cursor. Provider context keeps complete turns only:
at most 32 turns and 100,000 characters by default. It never slices through a
pending tool
request/result group. If the current turn alone exceeds the character bound,
the runtime raises `ContextWindowOverflowError` instead of sending partial
context.

History is cursor-paged and defaults to 1,024 events:

```python
page = await runtime.history("session", after_sequence=cursor, limit=128)
cursor = page[-1].sequence if page else cursor
```

```ts
const page = await runtime.history("session", { afterSequence: cursor, limit: 128 });
cursor = page.at(-1)?.sequence ?? cursor;
```

## Subscriber overflow

Subscriber queues hold 1,024 events by default. Overflow terminates only the
lagging subscriber with `EventBufferOverflowError` and reports its last and
latest sequence. The agent turn continues. Resume through the journal from the
reported cursor; do not restart the turn or infer a timestamp boundary.

## Legacy logs

Stable replay accepts only stored, sequenced events. Fully unsequenced legacy
logs must use `replay_legacy_session()` or `replayLegacySession()`. That named
compatibility path warns and orders by stable `(timestamp, input index)`.
Mixed sequenced and unsequenced logs are rejected. Migrate offline by assigning
contiguous sequence values in the legacy compatibility order while preserving
the original timestamps.
