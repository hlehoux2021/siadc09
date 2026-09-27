# Story 5.4: UDP & TCP Transport Layer

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a daemon architect,
I want to send and receive SIA frames over UDP and TCP,
So that the daemon can communicate with the CSR.

---

## Acceptance Criteria

1. **Transport Abstraction** — A new module `resources/siadc09d/sia_transport.py` defines `SIABaseTransport` (abstract), `SIAUDPTransport`, `SIATCPTransport`, and `_SIADatagramProtocol`. The daemon holds a `self._sia_transport: SIABaseTransport` and never contains socket I/O code.

2. **`SIATransportResult` TypedDict** — All transport methods return `SIATransportResult(TypedDict)` with keys `status: Literal['ack', 'nak', 'timeout', 'tcp_drop']` and `raw_nak: bytes | None`.

3. **Shared response parsing** — `SIABaseTransport._parse_response(raw: bytes) -> SIATransportResult` decodes CSR responses via `sia_protocol.decode_ack_nak()` and maps to `SIATransportResult`. Called by both UDP and TCP after receiving raw bytes — never duplicated.

4. **UDP Persistent Transport** — `SIAUDPTransport` creates one `asyncio.DatagramTransport` + `_SIADatagramProtocol` at `start()`, reused for all sends. Never creates a per-send socket.

5. **UDP Reply Gate** — `_SIADatagramProtocol.datagram_received()` sets an `asyncio.Future`; `SIAUDPTransport.send_frame()` awaits it with `asyncio.wait_for(..., timeout=receive_timeout_s)`. One `Future` per send, cleared after each reply. `asyncio.TimeoutError` → raises `SIATransportError`.

6. **TCP Per-Frame Connect** — `SIATCPTransport.send_frame()` opens a fresh TCP connection per frame (`asyncio.wait_for(open_connection(...), timeout=connect_timeout_s)`). Never bare `open_connection()` — hangs indefinitely on filtered ports (Review 11 F4).

7. **TCP Frame Boundary** — Response read uses `reader.readuntil(b'\x0D')` (not `reader.read(N)`). TCP is a stream; `read(N)` can return a partial SIA frame on congested networks, causing spurious CRC failures. `readuntil` guarantees a complete frame terminated by the SIA `<CR>` (§ 5.5.1.10).

8. **TCP Resource Cleanup** — `finally:` block always attempts `writer.close()` / `await writer.wait_closed()`. Cleanup `OSError` (e.g. from an already-reset connection) is silently swallowed — the connection is already gone and the original exception must not be replaced by a cleanup failure.

9. **TCP OS Error Classification** — `OSError` with errno `ECONNRESET`, `EPIPE`, `ENOTCONN`, `EBADF` → returns `SIATransportResult(status='tcp_drop', raw_nak=None)` (does not raise). All other `OSError` → raises `SIATransportError`.

10. **`SIATransportError` boundary** — All transport failures raise `SIATransportError(OSError)` from `sia_protocol.py`. Both transport classes never use bare `ValueError` or `OSError` for failures.

11. **Daemon wiring** — `SIADaemon._send_raw(frame: bytes) -> SIATransportResult` delegates entirely to `self._sia_transport.send_frame(frame)`. No socket logic on the daemon. Only `_queue_consumer()` may call `_send_raw()`.

12. **Lifecycle** — `on_start()` creates and starts the appropriate transport; `on_stop()` calls `await self._sia_transport.close()`.

---

## Tasks / Subtasks

### Task 1: Verify Exception Classes in `sia_protocol.py` (5.4.1)

- [x] 1.1 Ensure `SIATransportError` and `SIAProtocolError` are defined in `sia_protocol.py`:
  - [x] 1.1.1 If present: verify signatures match `class SIATransportError(OSError):` and `class SIAProtocolError(ValueError):` — then skip to Task 2
  - [x] 1.1.2 If absent: add both class definitions to `sia_protocol.py` immediately after the module imports block — **do NOT create a new file**:
    ```python
    class SIATransportError(OSError):
        """Network/socket failure — TCP timeout, UDP timeout, socket closed."""

    class SIAProtocolError(ValueError):
        """SIA DC-09 protocol violation — malformed frame, decode failure."""
    ```
  - [x] 1.1.3 Confirm both are importable in `sia_transport.py`

### Task 2: Create `sia_transport.py` — `SIATransportResult` and `SIABaseTransport` (5.4.2)

- [x] 2.1 Create `resources/siadc09d/sia_transport.py`
  - [x] 2.1.1 Module docstring: "SIA DC-09 transport layer. Separates socket I/O and SIA frame boundary handling from daemon state machine logic. Used exclusively by SIADaemon._send_raw()."
  - [x] 2.1.2 Imports: `asyncio`, `errno`, `abc`, `logging`, `typing` (`Literal`, `TypedDict`), `enum` (`Enum`); local: `sia_protocol`, `SIATransportError`

- [x] 2.2 Define module-level constants:
  ```python
  ON_STOP_TASK_TIMEOUT_S: float = 5.0  # Hard timeout for task cancellation in on_stop()
  ```

- [x] 2.3 Define `TransportType(Enum)` — strong-typed transport selector (code-style.md: prefer Enum over bare strings):
  ```python
  class TransportType(Enum):
      UDP = "UDP"
      TCP = "TCP"
  ```
  - `CSRPreset.transport` is typed `TransportType`. String values from JSON config (`"UDP"`, `"TCP"`) are converted via `TransportType(value)` in `CSRPreset.__post_init__()` — this is the **single conversion boundary**. All code beyond `CSRPreset` uses `TransportType.*`, never raw strings.

- [x] 2.4 Define `SIATransportResult(TypedDict)`:
  ```python
  class SIATransportResult(TypedDict):
      status: Literal['ack', 'nak', 'timeout', 'tcp_drop']
      raw_nak: bytes | None
  ```

- [x] 2.5 Define `SIABaseTransport(ABC)`:
  - [x] 2.5.1 `__init__(self, crc_format: str) -> None` — stores `self._crc_format: str = crc_format`. All subclasses must call `super().__init__(crc_format)` — this is the single initialization point for `_crc_format`, enforced by the constructor chain.
  - [x] 2.5.2 Concrete default method: `async def start(self) -> None: pass` — no-op for TCP (per-frame connect needs no setup). `SIAUDPTransport` overrides this to create the persistent `DatagramTransport`. `on_start()` always calls `await t.start()` unconditionally — no transport-type branching needed for startup.
  - [x] 2.5.3 Abstract method: `async def send_frame(self, frame: bytes) -> SIATransportResult`
  - [x] 2.5.4 Abstract method: `async def close(self) -> None`
  - [x] 2.5.5 Shared concrete method: `def _parse_response(self, raw: bytes) -> SIATransportResult`
    - Calls `sia_protocol.decode_ack_nak(raw, crc_format=self._crc_format)` → maps `type` to `status`:
      - `'ACK'` → `{status: 'ack', raw_nak: None}`
      - `'NAK'` → `{status: 'nak', raw_nak: result['raw_nak']}`
      - `'unknown'` → `{status: 'timeout', raw_nak: None}`
  - [x] 2.5.6 Module-level logger: `_logger = logging.getLogger(__name__)`

### Task 3: Define `_SIADatagramProtocol` in `sia_transport.py` (5.4.3)

- [x] 3.1 Define `_SIADatagramProtocol(asyncio.DatagramProtocol)` at module level (before `SIAUDPTransport`):
  - [x] 3.1.1 `__init__`: `self._future: asyncio.Future[bytes] | None = None`
  - [x] 3.1.2 `datagram_received(data: bytes, addr: tuple[str, int]) -> None`:
    - If `self._future` is not None and not done: `self._future.set_result(data)`
    - Else: log DEBUG `"Unexpected datagram received — no pending future"` (stray reply guard)
  - [x] 3.1.3 `error_received(exc: Exception) -> None`:
    - If `self._future` is not None and not done: `self._future.set_exception(exc)`
    - Else: log WARNING `"UDP error received (no pending future): {exc!r}"`
  - [x] 3.1.4 `connection_lost(exc: Exception | None) -> None`:
    - Log DEBUG `"UDP connection lost: {exc!r}"`
    - If `self._future` is not None and not done: `self._future.set_exception(SIATransportError("UDP connection lost"))`

### Task 4: Implement `SIAUDPTransport` in `sia_transport.py` (5.4.4)

- [x] 4.1 Define `SIAUDPTransport(SIABaseTransport)`:
  - [x] 4.1.1 `__init__(self, host: str, port: int, receive_timeout_s: float, crc_format: str) -> None`
    - Call: `super().__init__(crc_format)` — initializes `self._crc_format` via `SIABaseTransport.__init__`
    - Store: `self._host`, `self._port`, `self._receive_timeout_s`
    - Init: `self._transport: asyncio.DatagramTransport | None = None`
    - Init: `self._protocol: _SIADatagramProtocol | None = None`
    - Init: `self._logger = logging.getLogger(__name__)`

- [x] 4.2 Implement `async def start(self) -> None`
  - [x] 4.2.1 Close any existing transport first: `if self._transport: self._transport.close()`
  - [x] 4.2.2 `loop = asyncio.get_running_loop()` — **not** `get_event_loop()` (deprecated in 3.10+ inside async context)
  - [x] 4.2.3 `transport, protocol = await loop.create_datagram_endpoint(lambda: _SIADatagramProtocol(), remote_addr=(self._host, self._port))`
  - [x] 4.2.4 Store: `self._transport, self._protocol = transport, protocol`
  - [x] 4.2.5 Log: INFO `"Transport UDP initialisé: {host}:{port}"` (French — INFO log per logging style)
  - [x] 4.2.6 Log: DEBUG `"UDP DatagramTransport created"`

- [x] 4.3 Implement `async def send_frame(self, frame: bytes) -> SIATransportResult`
  - [x] 4.3.1 Guard: if `self._transport is None or self._protocol is None`: raise `SIATransportError("UDP transport not started")`
  - [x] 4.3.2 Set reply future: `loop = asyncio.get_running_loop(); future = loop.create_future(); self._protocol._future = future`
  - [x] 4.3.3 Send: `self._transport.sendto(frame)` — no remote_addr (already bound at `start()`)
  - [x] 4.3.4 Log: DEBUG `"UDP frame sent: {len(frame)} bytes"`
  - [x] 4.3.5 Await with timeout:
    ```python
    try:
        raw = await asyncio.wait_for(future, timeout=self._receive_timeout_s)
    except asyncio.TimeoutError:
        self._protocol._future = None
        raise SIATransportError("UDP response timeout")
    finally:
        self._protocol._future = None  # always clear — prevents stale future
    ```
  - [x] 4.3.6 Log: DEBUG `"UDP reply received: {len(raw)} bytes"`
  - [x] 4.3.7 Return `self._parse_response(raw)`
  - [x] 4.3.8 Exception handling order around entire body of `send_frame()` — **must appear in this exact order**:
    ```python
    except SIATransportError:
        raise  # re-raise before OSError catches it — SIATransportError inherits from OSError
               # (see daemon-design.md § Exception hierarchy)
    except OSError as e:
        raise SIATransportError(f"UDP socket error: {e!r}") from e
    ```

- [x] 4.4 Implement `async def close(self) -> None`
  - [x] 4.4.1 Close and clear both transport and protocol:
    ```python
    if self._transport:
        self._transport.close()
        self._transport = None
    self._protocol = None  # clear always — prevents stale protocol receiving late datagrams
    ```
    **Why:** after close, a late-arriving datagram could invoke `datagram_received()` on the orphaned protocol, which would call `set_result()` on a stale or garbage-collected future causing `InvalidStateError`.
  - [x] 4.4.2 Log: DEBUG `"UDP transport closed"`

### Task 5: Implement `SIATCPTransport` in `sia_transport.py` (5.4.5)

- [x] 5.1 Define `SIATCPTransport(SIABaseTransport)`:
  - [x] 5.1.1 `__init__(self, host: str, port: int, connect_timeout_s: float, receive_timeout_s: float, crc_format: str) -> None`
    - Call: `super().__init__(crc_format)` — initializes `self._crc_format` via `SIABaseTransport.__init__`
    - Store: `self._host`, `self._port`, `self._connect_timeout_s`, `self._receive_timeout_s`
    - Init: `self._logger = logging.getLogger(__name__)`
  - [x] 5.1.2 Docstring note: "Per-frame TCP transport: a new connection is opened, used, and closed for each `send_frame()` call. Not reentrant — `StreamReader/StreamWriter` are owned exclusively within `send_frame()`."

- [x] 5.2 Implement `async def send_frame(self, frame: bytes) -> SIATransportResult`
  - [x] 5.2.1 Initialize `writer: asyncio.StreamWriter | None = None` before try block
  - [x] 5.2.2 Connect with timeout guard:
    ```python
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=self._connect_timeout_s
        )
    except asyncio.TimeoutError:
        raise SIATransportError(f"TCP connect timeout ({self._connect_timeout_s}s)")
    ```
  - [x] 5.2.3 Log: DEBUG `"TCP connected to {host}:{port}"`
  - [x] 5.2.4 Send frame with drain timeout guard:
    ```python
    writer.write(frame)
    try:
        await asyncio.wait_for(writer.drain(), timeout=self._receive_timeout_s)
    except asyncio.TimeoutError:
        raise SIATransportError("TCP send buffer drain timeout")
    ```
    **Why:** bare `await writer.drain()` hangs indefinitely if the TCP send window is full (slow CSR or congested network). `receive_timeout_s` reused — if the CSR can't accept data within the response window, the connection is unusable.
  - [x] 5.2.5 Log: DEBUG `"TCP frame sent: {len(frame)} bytes"`
  - [x] 5.2.6 Read response with frame boundary guard (AC7 — the core fix):
    ```python
    try:
        raw = await asyncio.wait_for(
            reader.readuntil(b'\x0D'),          # SIA <CR> frame terminator § 5.5.1.10
            timeout=self._receive_timeout_s
        )
    except asyncio.IncompleteReadError:
        raise SIATransportError("TCP connection closed before SIA frame complete")
    except asyncio.LimitOverrunError:
        raise SIATransportError("TCP response exceeds StreamReader buffer limit — no frame terminator found")
    except asyncio.TimeoutError:
        raise SIATransportError("TCP response timeout")
    ```
    **Why `LimitOverrunError`:** `readuntil()` raises this when the buffer limit (default 64 KB) is exceeded without finding `\x0D`. It is not an `OSError` so it would bypass all other handlers and propagate uncaught to `_queue_consumer()`. Raised only by a rogue or badly misconfigured CSR — treated as a transport failure.
  <!-- raw == b"" guard removed: readuntil() never returns empty bytes — it either returns bytes
       including \x0D or raises IncompleteReadError / LimitOverrunError / TimeoutError.
       The empty-response path is structurally unreachable. -->
  - [x] 5.2.7 Log: DEBUG `"TCP reply received: {len(raw)} bytes"`
  - [x] 5.2.8 Return `self._parse_response(raw)`
  - [x] 5.2.9 Exception handling order — **must appear in this exact order** around the entire body of `send_frame()`:
    ```python
    except SIATransportError:
        raise  # re-raise specific errors from inner try blocks (connect timeout,
               # drain timeout, readuntil errors) before OSError catches them —
               # SIATransportError inherits from OSError (see daemon-design.md § Exception hierarchy)
    except OSError as e:
        if e.errno in (errno.ECONNRESET, errno.EPIPE, errno.ENOTCONN, errno.EBADF):
            self._logger.warning(f"TCP connection lost: {e!r}")
            return SIATransportResult(status='tcp_drop', raw_nak=None)
        raise SIATransportError(f"TCP socket error: {e!r}") from e
    ```
    **Why order matters:** `SIATransportError` inherits from `OSError`. Without the explicit re-raise first, the outer `except OSError` would catch `SIATransportError` instances raised by inner blocks (connect timeout, drain timeout, `readuntil` errors) and wrap them in the generic `"TCP socket error"` message, destroying the diagnostic detail.
  - [x] 5.2.10 Finally block — unconditional cleanup with exception guard:
    ```python
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass  # connection already reset — cleanup best-effort only
    ```
    **Why:** `writer.wait_closed()` can raise `OSError` (e.g. `ECONNRESET`) when the remote already closed the connection. An exception raised inside a `finally` block replaces the original exception being propagated, destroying the root cause. Cleanup is best-effort — the connection is already gone.

- [x] 5.3 Implement `async def close(self) -> None`
  - [x] 5.3.1 No persistent resource to release (per-frame connect)
  - [x] 5.3.2 Log: DEBUG `"TCP transport closed (no persistent resource)"`

### Task 6: Wire Transport into `SIADaemon` (5.4.6)

- [x] 6.1 Add import to `daemon.py`:
  `from .sia_transport import SIABaseTransport, SIAUDPTransport, SIATCPTransport, SIATransportResult, TransportType, ON_STOP_TASK_TIMEOUT_S`

- [x] 6.2 In `SIADaemon.__init__()`:
  - [x] 6.2.1 Add: `self._sia_transport: SIABaseTransport | None = None`
  - [x] 6.2.2 Document in `__init__` docstring under "Instance Variables (Transport)": `_sia_transport: Active SIABaseTransport instance (SIAUDPTransport or SIATCPTransport); None before on_start()`
  - [x] 6.2.3 Remove: `self._send_raw = self._send_raw_stub` assignment
  - [x] 6.2.4 Remove: `async def _send_raw_stub(self, frame: bytes) -> dict` stub method

- [x] 6.3 In `SIADaemon.on_start()`, create and start transport before launching queue consumer:
  ```python
  if self._preset.transport is TransportType.UDP:
      t = SIAUDPTransport(
          self._preset.host,
          self._preset.port,
          self._preset.receive_timeout_s,
          crc_format=self._preset.crc_format,
      )
  else:  # TransportType.TCP — exhaustive: TransportType only has UDP and TCP members
      t = SIATCPTransport(
          self._preset.host,
          self._preset.port,
          self._preset.connect_timeout_s,
          self._preset.receive_timeout_s,
          crc_format=self._preset.crc_format,
      )
  await t.start()  # no-op for TCP; creates DatagramTransport for UDP
  self._sia_transport = t
  ```
  **Note:** `await t.start()` is unconditional — `SIABaseTransport.start()` is a no-op for TCP, so no branching is needed. `CSRPreset.__post_init__()` already rejects unknown transport strings via `TransportType(value)`, so `self._preset.transport` is always a valid `TransportType` member by this point.
  - [x] 6.3.1 Then enqueue first supervision: `await self._enqueue_supervision()` — `on_start()` enqueues the first one; `_supervision_loop()` starts with `asyncio.sleep()` to avoid duplicate (daemon-design.md Task 1.8)

- [x] 6.4 Replace `_send_raw()` stub with real delegation method:
  ```python
  async def _send_raw(self, frame: bytes) -> SIATransportResult:
      """Send one SIA frame via the active transport. Only _queue_consumer() may call this.

      Returns:
          SIATransportResult with status 'ack'|'nak'|'timeout'|'tcp_drop'

      Raises:
          SIATransportError: if transport not initialized or network failure
      """
      if self._sia_transport is None:
          raise SIATransportError("Transport not initialized — on_start() not called")
      return await self._sia_transport.send_frame(frame)
  ```

### Task 6.5: Update `presets.py` — `CSRPreset.transport` Field (5.4.6-presets)

- [x] 6.5.1 Add import to `presets.py`: `from .sia_transport import TransportType`
- [x] 6.5.2 Change `transport` field annotation from `str` to `TransportType`:
  ```python
  transport: TransportType
  ```
- [x] 6.5.3 In `CSRPreset.__post_init__()`, convert the raw config string to `TransportType` — this is the single string→enum conversion boundary:
  ```python
  object.__setattr__(self, 'transport', TransportType(self.transport))
  # Raises ValueError if value is not 'UDP' or 'TCP' — caught by on_start() caller
  ```
  **Note:** `object.__setattr__` is required because `CSRPreset` is `@dataclass(frozen=True)` — direct assignment raises `FrozenInstanceError`.

### Task 7: Implement `SIADaemon.on_stop()` Shutdown Sequence (5.4.7)

- [x] 7.1 Implement `async def on_stop(self) -> None` per daemon-design.md Task 1.11 (not yet implemented):
  - [x] 7.1.1 Step 1 — Terminal INFO push (best-effort):
    ```python
    try:
        await self._update_info_commands()
    except asyncio.CancelledError:
        raise  # never swallow cancellation (daemon-design.md § CancelledError safety rule)
    except Exception as e:
        self._logger.error(f"on_stop: terminal INFO push failed: {e!r}")
    ```
  - [x] 7.1.2 Step 2 — Queue drain (discard pending items, no callbacks):
    ```python
    while not self._queue.empty():
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    ```
  - [x] 7.1.3 Step 3 — Cancel all tracked tasks:
    ```python
    for task in list(self._tasks):
        task.cancel()
    ```
  - [x] 7.1.4 Step 4 — Await task completion with hard timeout:
    ```python
    try:
        await asyncio.wait_for(
            asyncio.gather(*self._tasks, return_exceptions=True),
            timeout=ON_STOP_TASK_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        self._logger.error(f"on_stop: tasks did not complete within {ON_STOP_TASK_TIMEOUT_S}s timeout")
    ```
  - [x] 7.1.5 Step 5 — Close transport (guaranteed None reset via finally):
    ```python
    if self._sia_transport is not None:
        try:
            await self._sia_transport.close()
        except OSError:
            self._logger.warning("on_stop: transport close raised OSError — ignoring")
        finally:
            self._sia_transport = None
    ```
    **Why:** if `close()` raises, `self._sia_transport = None` must still execute — otherwise the next `on_start()` finds a stale broken transport object and `_send_raw()` would call `send_frame()` on it.
  - [x] 7.1.6 Log: INFO `"Démon SIA DC-09 arrêté"` (French — INFO per logging style)

### Task 8: Tests — `SIATransportResult` and `SIABaseTransport` (5.4.8)

Create `tests/level2/test_sia_transport_base.py`:

- [x] 8.0 Fixture: define a minimal concrete subclass to instantiate `SIABaseTransport` for testing `_parse_response()` in isolation — `SIABaseTransport` is abstract and cannot be instantiated directly:
  ```python
  class _ConcreteTransport(SIABaseTransport):
      async def send_frame(self, frame: bytes) -> SIATransportResult:
          raise NotImplementedError
      async def close(self) -> None:
          pass
      # start() inherited from SIABaseTransport — no-op, no override needed

  @pytest.fixture
  def transport() -> _ConcreteTransport:
      return _ConcreteTransport(crc_format='hex')
  ```

- [x] 8.1 TC1: `SIATransportResult` has correct keys and types

**For TC2–TC4:** mock `sia_protocol.decode_ack_nak` to return a controlled `AckNakResponse` — the unit under test is the mapping logic in `_parse_response()`, not the CRC parser. Use `unittest.mock.patch`:
```python
from unittest.mock import patch

with patch('resources.siadc09d.sia_transport.sia_protocol.decode_ack_nak',
           return_value={'type': 'ACK', 'seq': 1, 'raw_nak': None}):
    result = transport._parse_response(b'any_bytes')
```
Pass `b'any_bytes'` as raw — its content is irrelevant since `decode_ack_nak` is mocked.

- [x] 8.2 TC2: `_parse_response()` maps `decode_ack_nak` `type='ACK'` → `status='ack'`, `raw_nak=None`
- [x] 8.3 TC3: `_parse_response()` maps `type='NAK'` → `status='nak'`, `raw_nak=<bytes>`
- [x] 8.4 TC4: `_parse_response()` maps `type='unknown'` → `status='timeout'`, `raw_nak=None`

### Task 9: Tests — `SIAUDPTransport` (5.4.9)

Create `tests/level2/test_sia_transport_udp.py`:

- [x] 9.1 Fixture: mock `asyncio.DatagramTransport` + `_SIADatagramProtocol` (no real socket); mock `loop.create_datagram_endpoint()` to inject them

- [x] 9.2 TC5: `start()` creates transport and protocol; stores both; logs INFO + DEBUG
- [x] 9.3 TC6: `send_frame()` happy path — sets future, calls `sendto`, awaits future, calls `_parse_response`, clears future
- [x] 9.4 TC7: `send_frame()` timeout — `asyncio.TimeoutError` → raises `SIATransportError("UDP response timeout")`; future cleared
- [x] 9.5 TC8: `send_frame()` returns NAK — `{status: 'nak', raw_nak: bytes}`
- [x] 9.6 TC9: `send_frame()` before `start()` → raises `SIATransportError`
- [x] 9.7 TC10: `send_frame()` 3 consecutive sends — reuses same `DatagramTransport` object (persistent, never recreated)
- [x] 9.8 TC11: `close()` calls `transport.close()`, sets `_transport = None`
- [x] 9.9 TC12: stray datagram arrives with no pending future → logs DEBUG, does not raise

### Task 10: Tests — `SIATCPTransport` (5.4.10)

Create `tests/level2/test_sia_transport_tcp.py`:

- [x] 10.1 Fixture: mock `asyncio.open_connection` to return mock reader/writer pair

- [x] 10.2 TC13: `send_frame()` happy path — connects, writes, `readuntil(b'\x0D')`, `_parse_response`, `writer.close()`
- [x] 10.3 TC14: `readuntil` returns complete frame with `\x0D` — `_parse_response` called with full bytes
- [x] 10.4 TC15: `reader.read(N)` is NOT used anywhere in `SIATCPTransport` — assert `readuntil` is the only read call
- [x] 10.5 TC16: TCP connect timeout → `SIATransportError("TCP connect timeout...")`
- [x] 10.6 TC17: `reader.readuntil` response timeout → `SIATransportError("TCP response timeout")`
- [x] 10.7 TC18: `asyncio.IncompleteReadError` → `SIATransportError("TCP connection closed before SIA frame complete")`
- [x] 10.8 TC18b: `asyncio.LimitOverrunError` → `SIATransportError("TCP response exceeds StreamReader buffer limit...")`
- [x] 10.9 TC19: `OSError(errno.ECONNRESET)` → returns `SIATransportResult(status='tcp_drop', raw_nak=None)` (does not raise)
- [x] 10.10 TC20: `OSError(errno.ENOMEM)` → raises `SIATransportError`
- [x] 10.11 TC21: `finally` block always executes — `writer.close()` + `await writer.wait_closed()` called on every path (exception, timeout, success)
- [x] 10.12 TC21b: `writer.wait_closed()` raises `OSError` in `finally` — original exception still propagates (not replaced by cleanup error)
- [x] 10.13 TC22: `writer = None` guard — if connect raises before `writer` assigned, `finally` block does not crash
- [x] 10.14 TC23b: `drain()` timeout → raises `SIATransportError("TCP send buffer drain timeout")`; specific message preserved (not wrapped by outer `except OSError`)

### Task 11: Tests — Daemon Integration (5.4.11)

Create `tests/level2/test_sia_transport_daemon_wiring.py`:

- [x] 11.1 TC23: `on_start()` with UDP preset — creates `SIAUDPTransport` with `crc_format=preset.crc_format`, calls `start()`, stores in `_sia_transport`
- [x] 11.2 TC24: `on_start()` with TCP preset — creates `SIATCPTransport` with `crc_format=preset.crc_format`, stores in `_sia_transport`
- [x] 11.3 TC29: `CSRPreset` constructed with unknown transport string (e.g. `'udp'`) → `__post_init__()` raises `ValueError` before `on_start()` is ever called
- [x] 11.4 TC25: `_send_raw()` delegates to `_sia_transport.send_frame()` — mock transport, assert forwarded
- [x] 11.5 TC26: `_send_raw()` before `on_start()` (transport None) → raises `SIATransportError`
- [x] 11.6 TC27: `on_stop()` calls `await _sia_transport.close()`
- [x] 11.7 TC28: End-to-end supervision (UDP): `_supervision_loop()` → `_enqueue_supervision()` → `_queue_consumer()` → `_send_supervision()` → `_send_raw()` → mock transport ACK → `SM1=HEALTHY`

---

## Dev Notes

### Architecture Decision: Transport Classes in `sia_transport.py`

**Why separate module, not daemon methods:**
The previous design had `_send_raw_tcp()` / `_send_raw_udp()` as methods on `SIADaemon`. This conflated three distinct concerns: (1) socket I/O, (2) SIA frame boundary handling, and (3) state machine orchestration. The refactored design:

```
sia_transport.py              daemon.py
────────────────              ─────────
_SIADatagramProtocol          SIADaemon._send_raw()
SIABaseTransport                └─ delegates entirely to
SIAUDPTransport                    self._sia_transport.send_frame()
SIATCPTransport
```

`sia_transport.py` classes have no knowledge of SM1/SM2, strikes, or retries. `SIADaemon` has no socket I/O code. Tests for transport classes can be written without instantiating the daemon.

### Critical: TCP Frame Boundary — `readuntil(b'\x0D')` not `read(N)`

TCP is a stream protocol — `read(1024)` can return a partial SIA frame if the OS delivers data in two segments (common on residential connections with asymmetric MTU). Every SIA DC-09 frame is terminated by `0x0D` (CR) per § 5.5.1.10. `asyncio.StreamReader.readuntil(b'\x0D')` reads until this delimiter is found and returns the complete frame. Partial-frame reads would produce spurious CRC failures, which map to `'timeout'` status, which increment the SM1 strike counter — potentially triggering a false `SUPERVISION_DISCONNECTED` T3 alert in production.

### Critical: `asyncio.get_running_loop()` not `get_event_loop()`

Task 4.2.2 uses `asyncio.get_running_loop()`. The deprecated `asyncio.get_event_loop()` raises `DeprecationWarning` in Python 3.10+ when called from a coroutine and will raise `RuntimeError` in a future version. Since this project targets Python 3.10+ (declared in `info.json`), always use `get_running_loop()` inside `async def` contexts.

### `SIATransportResult` Satisfies code-style.md TypedDict Rule

The original story used bare `dict` as the return type. `SIATransportResult(TypedDict)` gives:
- Static type checking on `result['status']` accesses
- Literal type on `status` — type checker catches invalid values
- No runtime overhead (TypedDict is a typing-only construct)

### `asyncio.Future` Cleanup in UDP

The `finally: self._protocol._future = None` in `SIAUDPTransport.send_frame()` is unconditional — runs on timeout, on `OSError`, and on success. This prevents a stale `Future` from a previous call being set_result'd by a late-arriving datagram, which would cause `InvalidStateError` on the next send.

### TCP Per-Frame Connect Pattern

`SIATCPTransport` connects, sends, reads, and closes for every frame. The spec (§ 5.3) permits this: "The PE may optionally close the socket connection." IMA Protect is confirmed to support ephemeral TCP per the project design decisions. No persistent `StreamReader/StreamWriter` is held between frames, which avoids half-open socket state entirely (eliminating the need for TCP stall detection at the transport layer — that's still SM1's job via the strike counter).

### File Structure

```
resources/siadc09d/
├── sia_transport.py    ← CREATE: TransportType, ON_STOP_TASK_TIMEOUT_S,
│                                  SIATransportResult, _SIADatagramProtocol,
│                                  SIABaseTransport, SIAUDPTransport, SIATCPTransport
├── daemon.py           ← MODIFY: import sia_transport, wire _sia_transport,
│                                  replace _send_raw_stub with real delegation,
│                                  implement on_stop(), update on_start()
├── presets.py          ← MODIFY: transport field str → TransportType; __post_init__ conversion
└── sia_protocol.py     ← VERIFY/ADD: SIATransportError, SIAProtocolError

tests/level2/
├── test_sia_transport_base.py        ← CREATE (TC1–TC4)
├── test_sia_transport_udp.py         ← CREATE (TC5–TC12)
├── test_sia_transport_tcp.py         ← CREATE (TC13–TC22)
└── test_sia_transport_daemon_wiring.py  ← CREATE (TC23–TC28)
```

### Existing Daemon Code to Touch

| Location | Action |
|----------|--------|
| `daemon.py:319` | Remove `self._send_raw = self._send_raw_stub` |
| `daemon.py:322–324` | Remove `_send_raw_stub()` method |
| `daemon.py:__init__` | Add `self._sia_transport: SIABaseTransport \| None = None` |
| `daemon.py:on_start()` | Add transport construction + first supervision enqueue |
| `daemon.py` | Add real `_send_raw()` delegation method |
| `daemon.py` | Add `on_stop()` (currently missing) |
| `presets.py` | Change `transport` field type `str` → `TransportType`; add `TransportType(value)` conversion in `__post_init__()` |

### `CSRPreset` Attributes Used by Transport Classes

`SIAUDPTransport` and `SIATCPTransport` take plain constructor arguments (not the preset directly) — the daemon passes individual values from `self._preset`:
- `self._preset.host` → `host: str`
- `self._preset.port` → `port: int`
- `self._preset.transport` → `TransportType` enum — selects which class to instantiate. **Typed `TransportType`, not `str`.** The raw JSON string (`"UDP"` / `"TCP"`) is converted to `TransportType` once in `CSRPreset.__post_init__()` via `TransportType(value)` — `ValueError` raised immediately if value is unknown. All daemon code uses `TransportType.*` only.
- `self._preset.crc_format` → `crc_format: str` — **both** UDP and TCP (required for `_parse_response()` → `decode_ack_nak()` CRC validation)
- `self._preset.connect_timeout_s` → TCP only (default 10s)
- `self._preset.receive_timeout_s` → both UDP and TCP

**`TransportType` import chain:** defined in `sia_transport.py`, imported in `daemon.py` and `presets.py`. `CSRPreset` is defined in `presets.py` alongside `SUPPORTED_SCHEMA_VERSION`.

This keeps transport classes free of `CSRPreset` dependency (clean layer boundary).

### References

- [Source: internal-docs/design/daemon-design.md § Task 1.3 — `_send_raw()`] — UDP persistent transport, TCP per-frame rules, OS errno classification
- [Source: internal-docs/design/daemon-design.md § Task 1.11 — `on_stop()`] — 5-step shutdown sequence
- [Source: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.10] — `0x0D` CR frame terminator
- [Source: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.3] — TCP socket close is optional
- [Source: _bmad-output/implementation-artifacts/5-3-priorityqueue-task-coordination.md] — `_track_task()`, test fixture patterns, `daemon_factory`

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (1M context)

### Debug Log References

- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Daemon design: `internal-docs/design/daemon-design.md` Tasks 1.2, 1.3, 1.11
- Supervision design: `internal-docs/design/supervision-design.md` Group A
- Architecture: `_bmad-output/planning-artifacts/architecture.md` ADR-01, ADR-02
- Previous story: `_bmad-output/implementation-artifacts/5-3-priorityqueue-task-coordination.md`

### Completion Notes List

- Task 1: `SIATransportError(OSError)` added to `sia_protocol.py`; `SIAProtocolError` base class corrected from `Exception` to `ValueError` per daemon-design.md spec
- Tasks 2-5: Created `sia_transport.py` with full transport hierarchy: `TransportType` enum, `SIATransportResult` TypedDict, `SIABaseTransport` (ABC with `__init__`, `start()`, `_parse_response()`), `_SIADatagramProtocol`, `SIAUDPTransport` (persistent datagram), `SIATCPTransport` (per-frame connect with readuntil frame boundary)
- Task 6: Daemon wired — import chain, `_sia_transport` instance variable, `_send_raw()` delegation (replaced stub), transport creation in `on_start()`
- Task 6.5: Created `presets.py` with `CSRPreset` frozen dataclass; `transport` field converted from string to `TransportType` in `__post_init__()`
- Task 7: Implemented `on_stop()` 5-step shutdown: terminal INFO push, queue drain, task cancel, await with `ON_STOP_TASK_TIMEOUT_S`, transport close with finally/None reset
- Tasks 8-11: 32 tests across 4 test files — all pass. Pre-existing failures in `test_error_handler.py` (7) and `test_sm1_extended_suite.py` (2) confirmed identical on previous commit
- Edge case review findings applied to story spec before dev: F1(crc_format), F3(LimitOverrunError), F4(SIATransportError/OSError order), F5(drain timeout), F6(finally cleanup guard), F7(TransportType enum)
- Adversarial review findings applied: 11 findings (F5 withdrawn), all others fixed in spec and implemented
- Code review (adversarial): 6 HIGH/MEDIUM findings resolved — H1(TC28 missing, added + encryption_enabled field added to CSRPreset), H2(_handle_supervision_nak used stale 'nak_data' key → fixed to 'raw_nak'), H3(_handle_supervision_ack used non-existent 'raw_hex' → fixed to None), M1(crc_format bare str → CrcFormat Literal type), M2(hasattr guard → isinstance(CSRPreset)), M3(CancelledError guard added to _send_supervision). L1/L2 cosmetic — not fixed.

### File List

**Created:**
- `resources/siadc09d/sia_transport.py` — Transport layer: TransportType, SIATransportResult, SIABaseTransport, _SIADatagramProtocol, SIAUDPTransport, SIATCPTransport, ON_STOP_TASK_TIMEOUT_S
- `resources/siadc09d/presets.py` — CSRPreset frozen dataclass with TransportType conversion
- `tests/level2/test_sia_transport_base.py` — TC1–TC4 + crc_format pass-through test
- `tests/level2/test_sia_transport_udp.py` — TC5–TC12
- `tests/level2/test_sia_transport_tcp.py` — TC13–TC23b
- `tests/level2/test_sia_transport_daemon_wiring.py` — TC23–TC29

**Modified:**
- `resources/siadc09d/sia_protocol.py` — Added `SIATransportError(OSError)`; changed `SIAProtocolError` base from `Exception` to `ValueError`
- `resources/siadc09d/daemon.py` — Import chain, `_sia_transport` instance variable, `_send_raw()` delegation, transport creation in `on_start()`, `on_stop()` shutdown sequence; code review fixes: `nak_data`→`raw_nak`, `raw_hex`→`None`, `hasattr`→`isinstance(CSRPreset)`, `CancelledError` guard in `_send_supervision`, `CSRPreset` import
- `resources/siadc09d/presets.py` — Added `encryption_enabled: bool` field; `CrcFormat` type for `crc_format` field
- `resources/siadc09d/sia_transport.py` — `CrcFormat = Literal['hex','bin']` type alias; all `crc_format: str` → `crc_format: CrcFormat`
- `tests/level2/test_sia_transport_daemon_wiring.py` — Added TC28 (end-to-end supervision); added `encryption_enabled` to all CSRPreset fixtures
