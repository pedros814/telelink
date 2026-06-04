# ARS Fixtures

Test fixtures for ARS Phase 3 development and testing.

## Thread Fixtures
- `thread-empty.json`: Empty thread.
- `thread-needs-reply.json`: Thread where the last message is inbound.
- `thread-already-replied.json`: Thread where the last message is outbound.
- `thread-never-replied.json`: Thread with only an inbound message.
- `thread-tapback-only.json`: Thread where the last inbound message is just a tapback reaction.
- `thread-burst.json`: Thread with multiple consecutive inbound messages (burst).
- `thread-supersede.json`: Thread with a new inbound message that supersedes a pending reply.

## Session Fixtures
- `session-waiting.json`: Session state when waiting for an inbound message.
- `session-awaiting.json`: Session state when waiting for an agent to reply.

## Other
- `sent-log-tail.json`: Mock of `sent.jsonl` data for outbound message detection.
