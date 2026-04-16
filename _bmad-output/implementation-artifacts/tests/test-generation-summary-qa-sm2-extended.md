# Test Automation Summary — SM2 Extended Coverage

**Generated:** 2026-04-15
**Agent:** Quinn (QA Engineer)
**Target:** Story 5-2 SM2 Alarm Event State Machine
**Scope:** Challenge and extend baseline test suite (`test_sm2_alarm_event_suite.py`)

---

## Generated Tests

### New Test File

- [x] `tests/level2/test_sm2_extended_coverage.py` — 29 tests (28 pass, 1 xfail documented)

### Test Classes

| Class | Tests | Focus |
|---|---|---|
| `TestEventItemDataclass` | 3 | EventItem fields, callback contract |
| `TestRetryMechanics` | 6 | Call counts, exit conditions, asyncio.TimeoutError path |
| `TestSequenceNumberBehavior` | 3 | Seq increment, wrap at 9999, **known spec bug (xfail)** |
| `TestInfoCommandPayloads` | 2 | `_update_info_commands` exact payload on ACK and FAILED |
| `TestAllAlarmTypes` | 6 | Parametrized BA/FA/PA × confirmed + failed |
| `TestLoggingQuality` | 4 | Exact French strings, ctx=None fallback |
| `TestEdgeCases` | 5 | Empty zone, attempt count reset, PENDING-first invariant, notify ctx |

---

## Coverage Added (gaps vs. baseline)

| Gap | Test Added |
|---|---|
| `_update_info_commands` payload not verified | `test_update_info_on_confirmed`, `test_update_info_on_max_retries_failed` |
| Only 1 alarm type tested at a time | 6 parametrized tests for BA/FA/PA × confirmed/failed |
| `asyncio.TimeoutError` path untested | `test_asyncio_timeout_error_triggers_failed` |
| Call count not verified | `test_send_raw_called_once_on_immediate_ack`, `test_send_raw_called_max_retries_plus_one_on_timeout`, `test_nak_stops_retry_immediately` |
| `_event_attempt_count` reset between events | `test_attempt_count_resets_per_new_event` |
| PENDING-first invariant not verified during send | `test_sm2_starts_pending_on_send` (state captured during _send_raw) |
| Notification context payloads not inspected | `test_notify_context_contains_zone_and_sia_code_on_event_failed`, `test_bad_csr_notification_context_on_undecodable_nak` |
| Logging: only loose string matching | 4 tests with exact French phrases from messages.py |
| `EventItem.callback` field not tested | `test_event_item_callback_not_invoked_by_send_with_retry` (documents deferred invocation) |
| Empty string zone vs. None | `test_empty_string_zone_treated_as_present` |
| max_retries=0 edge case | `test_max_retries_zero_single_attempt_on_timeout` |

---

## Bugs Discovered

### 🐛 BUG-001: Sequence number increments on every retry (SIA DC-09 spec violation)

**Severity:** Medium
**Test:** `TestSequenceNumberBehavior::test_seq_does_not_increment_on_retry` (marked `@pytest.mark.xfail`)

**Description:**
Per SIA DC-09 § 5.5.1.5: *"The PE shall NOT increment the sequence number when repeating a message due to a communication failure or no response from a CSR."*

**Current behavior:** `_build_event_frame()` is called inside the retry loop and calls `self._sia_seq = (self._sia_seq + 1) % 10000` on **every call**. With 2 timeouts + 1 ACK (3 total sends), `_sia_seq` increments 3 times instead of 1.

**Impact:** A real CSR may reject repeated frames because they have different sequence numbers than expected for a retry. The CSR should receive the same seq on a retry.

**Recommended fix:**
```python
# In _send_with_retry: increment seq ONCE before the loop
self._sia_seq = (self._sia_seq + 1) % 10000
for attempt in range(max_retries + 1):
    frame = self._build_event_frame_with_seq(event_item, self._sia_seq)  # No increment
    ...
```
Or use a `is_retry` flag in `_build_event_frame`.

**Reference story for fix:** Story 5-3 or targeted bugfix after code review.

---

### ℹ️ GAP-001: EventItem.callback never invoked by _send_with_retry

**Severity:** Low (deferred by design)
**Test:** `TestEventItemDataclass::test_event_item_callback_not_invoked_by_send_with_retry`

**Description:** `EventItem` has a `callback: Optional[Any] = None` field documented as "called when event completes". However, `_send_with_retry()` never calls it. The callback invocation is expected to happen in `_queue_consumer()` (story 5-3).

**Status:** Documented, test confirms current behavior. No action needed until 5-3.

---

## Test Results

```
SM2 extended coverage (test_sm2_extended_coverage.py):
  28 passed, 1 xfailed

Full regression suite:
  486 passed, 9 pre-existing failures (NotImplementedError stubs unrelated to SM2), 1 xfailed
  No new failures introduced
```

---

## Next Steps

1. **Fix BUG-001** (seq on retry): Update `_build_event_frame` to not increment seq on retries. Can be fixed in current story 5-2 before code review, or deferred to 5-3.
2. **Implement EventItem.callback invocation** in story 5-3 `_queue_consumer()`.
3. **Fix `sia_protocol.py._format_data_field`** to include zone in primary data block `[#ACCT|CODE zone]` per SIA DC-09 § 5.5.1.7 (noted by sia-dc09-expert).
4. **Deferred SM2 tests** (TC6, TC9, TC10) to be implemented in story 5-3 with PriorityQueue.
