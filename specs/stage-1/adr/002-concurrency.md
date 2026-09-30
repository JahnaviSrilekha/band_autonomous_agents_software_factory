# ADR-002: One global lock as the sole state-mutation chokepoint

## Context

The technical direction requires: "Every write runs as one uninterrupted critical section,
from claiming the idempotency key to commit (one global lock, or a single-threaded event
loop)." The service must also serve up to 50 requests concurrently within a 5s timeout, and
must never produce a 5xx or a negative/lost balance under that concurrency (R1-R3, R42).

## Options

1. Single-threaded event loop (`asyncio`, one worker) — no lock needed by construction, but
   `hashlib.scrypt` (synchronous, CPU-bound) would block the entire event loop for every
   signup/login, and 50 concurrent requests would serialize behind whichever CPU-bound
   operation... plus `http.server` has no async request handling in stdlib without
   reimplementing a chunk of `asyncio` HTTP handling.
2. Thread pool (`ThreadingHTTPServer`) + one process-wide `threading.RLock` guarding all
   mutable state, acquired for the full duration of every handler (read or write) as
   described in design.md §2.

## Decision

Use option 2. It maps directly onto the direction's "one global lock" alternative, keeps
`http.server` usable as-is, and lets password hashing (ADR-003) run on its own thread outside
the lock so a slow signup/login never blocks unrelated payments.

## Consequences

- Every handler is trivially serializable with respect to every other handler that touches
  state: there is exactly one lock, acquired in one place per request (design.md §5), so no
  code path can partially apply a mutation while another thread observes it.
- Throughput is bounded by how long the lock is held per request; because state is a plain
  in-memory object graph (dict/list operations), each critical section is microseconds, so 50
  concurrent requests queueing briefly behind the lock comfortably fits the 5s timeout.
- `RLock` (reentrant) rather than plain `Lock` is used so a handler that calls an internal
  helper which itself acquires the lock (e.g. `/requests/{id}/pay` reusing the same commit
  helper as `/payments`) cannot deadlock itself.
