# Walkthrough: commit e0732f5, story 17-2 (configurable supervision frame)

Current block: none (all accepted)

- [x] **1. Intent** (accepted)
- [x] **2. Broad strokes** (accepted)
- [x] **3. Frame builder: clear NULL and real `*NULL`** (accepted)
- [x] **4. Loop timing: first frame at start, period from end of exchange** (accepted)
- [x] **5. Tests** (accepted)
- [x] **6. Periphery** (accepted)

## 1. Intent

Source: the `## Intent` section of [the plan](../plan-17-2-configurable-supervision-frame.md), verbatim.

**Problem:** Story 17.1 carries `supervision_format` into `CSRPreset`, but the daemon always sends the `sia-dcs` frame, and the first frame waits one full interval (D-42). A CSR that expects a true Null Message cannot be served.

**Approach:** Make `_supervision_loop` act on `supervision_format` (`sia-dcs` | `null` | `none`). It sends its first frame at daemon start and counts each period from the end of the previous supervision exchange. Add a clear `"NULL"0000L0#acct[]_ts` builder path (§ 5.5.2.1). No wizard, no RP, no PHP change.

## 2. Broad strokes

- [make_supervision_message](../../resources/siadc09d/sia_protocol.py#L310): new `supervision_format` parameter; `null` builds the clear or encrypted Null Message, `sia-dcs` is unchanged.
- [_send_supervision](../../resources/siadc09d/daemon.py#L1108): passes the preset's format to the builder.
- [_supervision_loop](../../resources/siadc09d/daemon.py#L2312): enqueue, wait for the exchange to end, then sleep.
- [_queue_consumer finally](../../resources/siadc09d/daemon.py#L2307): releases the loop's wait for every outcome.
- [on_start](../../resources/siadc09d/daemon.py#L2597): no supervision task for `none`.

## 3. Frame builder: clear NULL and real `*NULL`

The format picks the token. `null` always uses seq `0000` and never draws from the sequence tracker; in clear it is `"NULL"0000L0#acct[]_ts`, encrypted it is the real `*NULL`. `sia-dcs` keeps its frame, including the encrypted `*SIA-DCS` 0000 fallback, because `ENCRYPTED_SUPERVISION_TOKEN` is pinned by an existing test. An unknown format raises `SIAProtocolError`.

- [format check and branch](../../resources/siadc09d/sia_protocol.py#L352)
- [clear Null Message](../../resources/siadc09d/sia_protocol.py#L369)

## 4. Loop timing: first frame at start, period from end of exchange

The loop used to sleep first, then enqueue. Now it enqueues, awaits an `asyncio.Event`, then sleeps. The event starts set, `_enqueue_supervision` clears it, and the consumer sets it in a `finally` after any supervision item (ACK, NAK, timeout, drop, NO_NETWORK drop). Nothing enqueues on an INITIALIZING transition, so a reconnect does not double-send.

- [event creation](../../resources/siadc09d/daemon.py#L503)
- [clear on enqueue](../../resources/siadc09d/daemon.py#L2196)
- [set in finally](../../resources/siadc09d/daemon.py#L2307)
- [loop](../../resources/siadc09d/daemon.py#L2312)

## 5. Tests

Level 1 pins the frames: clear golden frame, no tracker use, encrypted `*NULL`, `sia-dcs` unchanged, decoder and simulator accept it. Level 2 covers the matrix: null clear, NAK re-send with seq 0000, encrypted null versus fallback, `none`, end-of-exchange timing, NO_NETWORK release, no enqueue on INITIALIZING.

- [level 1 frames](../../tests/level1/test_supervision_null_format.py)
- [level 2 behaviour](../../tests/level2/test_supervision_default_preset.py)
- [one-line fix outside the plan](../../tests/level2/test_ipc_daemon_wiring.py): the start-of-run frame disturbed the consumer test, so it now uses format `none`.

## 6. Periphery

- [the plan, with triage log](../plan-17-2-configurable-supervision-frame.md): 8 review findings, all rejected.
