# ARS Proofread Checklist

Use this checklist during Phase 4 to ensure the implementation is fully aligned with the requirements.

## 1. Documentation
- [ ] `.skills/telelink/ARS.md` matches exactly the CLI contract.
- [ ] `ars next --raw` JSON schema is documented.
- [ ] `agent context` ARS block exists and is correct.
- [ ] `help ars` text matches `ARS.md` outline.
- [ ] `AGENTS.md` task table has the auto-reply row.

## 2. CLI Accuracy
- [ ] `ars start <session> <contact>` normalizes session name correctly.
- [ ] `ars next <session> --raw` returns valid JSON with `action` and `commands` keys.
- [ ] `ars status <session> --raw` returns state without advancing.
- [ ] `ars stop` works with and without session name.
- [ ] `ars list --raw` includes all active sessions.

## 3. Needs Tending Logic (Fixtures)
- [ ] `empty_thread` -> waiting
- [ ] `no_inbound` -> waiting
- [ ] `never_replied` -> need_reply
- [ ] `inbound_after_last_outbound` -> need_reply
- [ ] `already_replied` -> waiting
- [ ] `tapback_only` -> waiting
- [ ] Burst coalescing works (multiple inbound within window).

## 4. TeleLink Integration
- [ ] Outbound detection via `sent_log` works.
- [ ] Outbound detection via `fetch_conversation` works.
- [ ] `telelink/session.py` skips calendar daemon when `TELELINK_ARS=1`.

## 5. Tests
- [ ] `pytest tests/test_ars_logic.py` passes.
- [ ] `pytest tests/test_ars_state.py` passes.
- [ ] `pytest tests/test_ars_detect.py` passes.
- [ ] `pytest tests/test_ars_store.py` passes.
- [ ] `pytest tests/test_ars_tick.py` passes.
