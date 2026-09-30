# ADR-001: Python 3.12 standard library only, `http.server.ThreadingHTTPServer`

## Context

The run's technical direction states: "Python 3.12 standard library unless the coordinator
records a better reason in a decision record." The service must run with no outbound network
at runtime (R9), within 2 vCPU / 2 GiB, healthy within 60s, handling up to 50 concurrent
requests with a 5s per-request timeout (R10).

## Options

1. Python 3.12 stdlib `http.server` — no external dependencies to vendor into the image, no
   build-time package resolution to fail without network, smallest image and fastest cold
   start.
2. A third-party framework (FastAPI/Flask + an ASGI/WSGI server) — better ergonomics, but
   every dependency must be `pip install`ed at build time (fine, network is available during
   `docker build`) and vendored into the final layer; more moving parts to keep working
   without any runtime network access, larger image, slower cold start against the 60s budget.

## Decision

Use option 1: Python 3.12 stdlib only, no third-party packages. No recorded reason to deviate
from the default direction — stdlib's `http.server.ThreadingHTTPServer` plus manual JSON
routing is sufficient for this API's surface (16 endpoints), and `hashlib.scrypt` (stdlib,
since Python 3.6) satisfies the password-hashing requirement (R47) without an external
dependency.

## Consequences

- No `requirements.txt`/`pip install` step; `Dockerfile` just copies source and runs it —
  smaller surface for the "no outbound network at runtime" constraint to break.
- Routing, JSON validation and content negotiation are hand-written rather than
  framework-provided; design.md §5 fixes one shared write-path algorithm so this isn't
  reimplemented five times.
- `ThreadingHTTPServer` spawns one thread per connection; combined with the single global
  lock (ADR-002) this is simple to reason about at 50 concurrent requests, though it would not
  scale to a much larger fleet — acceptable at this stage's stated resource limits.
