# Batch 1 (T1-T4) review probes — reviewer, 2026-09-30

Reviewed at dev-stage1 @ 29692bf77d6cb9c101a927cd88f9d40f42638ead (fresh clone,
`/Users/jahnavisrilekhamolleti/Documents/Hackathon/band-work/review-batch1`).

## Ran
- `python3 -m unittest discover -s stage-1/tests` → 44 tests OK (matches developer's report).
- `docker build -t pocketful-review-batch1 stage-1` → clean build, no network.
- `docker run --rm -p 8098:8080 pocketful-review-batch1` → `GET /health` → `200
  {"status":"ok"}` within 2s.

## Independent black-box probes (curl against a live instance)

| # | Check | Requirement | Request | Result |
|---|---|---|---|---|
| 1 | Array top-level body on reset | A8 | `POST /_test/reset` body `[1,2,3]` | `400 malformed_request` ✓ |
| 2 | `null` top-level body | A8 | `POST /_test/reset` body `null` | `400 malformed_request` ✓ |
| 3 | Missing `currency` in fixture | A13 | `POST /_test/reset` fixture w/o `currency` | `422 validation_failed` ✓, prior state untouched (verified via a following valid reset not needed — build happens before swap) |
| 4 | Negative seeded balance | R15 | fixture `balance: -5` | `422 validation_failed` ✓ |
| 5 | Seeded balance not replayed against seeded payments | R33 | fixture `balance: 500` + a seeded payment of `100` between the same user | reset returns `204`; balance field stored verbatim (code path confirmed by reading `reset.py`: `balance` assigned directly from fixture, payments recorded separately, never netted) |

## Code-level verification (read, not run)
- `idempotency.py::json_equal` — bool/number branch checked first, so `True != 1`; numeric
  branch does cross-type `int`/`float` comparison so `1000 == 1000.0`. Matches design §6.
- `run_idempotent` holds `STATE_LOCK` across the entire claim+execute+commit sequence, so
  R52 ("exactly one 201, rest 200 identical body") holds trivially — no other request can
  observe the `in_flight` state. Confirmed by reading `test_concurrent_identical_requests_execute_once`.
- Processing order in `server.py::_handle` matches design's fixed order: parse body →
  authenticate → (idempotency resolution happens inside the handler, before field validation,
  since `route.handler` — which does field validation — is only invoked from inside
  `run_idempotent` after the existing-record check). Matches R54.

## Findings (non-blocking)
- `__pycache__/*.pyc` files were committed under `stage-1/src/pocketful/__pycache__` and
  `stage-1/tests/__pycache__`. Not a requirement violation and not a nested-repo/link issue,
  but repo hygiene — flagged to developer to add a `.gitignore` and stop tracking these in a
  future commit.
- If `route.handler` raises a non-`ApiError` exception while holding an idempotency claim,
  the record is left `in_flight` with `response_body=None` and a same-key-same-body retry
  would incorrectly get `200 None` instead of re-executing. Not covered by any R48-R54
  acceptance text (only 4xx-frees-key is specified) and no code path in this batch can trigger
  it (T1-T4 endpoints don't call `run_idempotent`), so not a blocker — worth a defensive fix
  before idempotent write endpoints land in a later batch.

## Verdict
Accept. Fast-forward merged dev-stage1 → main.
