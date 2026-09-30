# Stage 1 design — pocketful

Implements requirements.md (this commit). See `adr/` for the significant decisions.

## 1. Stack

Python 3.12, standard library only (`http.server`, `json`, `hashlib`, `hmac`, `secrets`,
`threading`, `time`, `re`, `uuid`). See ADR-001 for why, and why not a third-party framework.

## 2. Process model

One process, one `http.server.ThreadingHTTPServer` (a thread per connection, stdlib), backed
by a request queue (`ThreadingHTTPServer.request_queue_size = 256`, meeting the "server request
queue of at least 256" direction). All mutable service state lives in one Python object graph
in process memory (no disk persistence — assumption A4); it is guarded by one
`threading.RLock` (`STATE_LOCK`). See ADR-002.

Rule enforced everywhere: **every state-changing HTTP handler acquires `STATE_LOCK` exactly
once, does all of its reads, checks and writes while holding it, and releases it only after the
response body is fully computed.** This is the "one uninterrupted critical section" the
technical direction requires. Read-only handlers (`GET /me`, `GET /requests`, `GET /activity`)
also take the lock for the duration of building their response, so they see a consistent
snapshot and never race a concurrent write.

**Exception, per the technical direction ("password hashing happens outside that critical
section")**: `hashlib.scrypt` calls (signup: hash the new password; login: verify a candidate
password against a stored hash) run *before* acquiring the lock for signup, and read the
stored hash via a short separate lock acquisition for login, then verify outside the lock. See
ADR-003 for the exact sequencing and the race it avoids.

## 3. Data model (in-memory)

```
State:
  currency: str
  minor_units: int
  settlement_operator_ids: set[str]
  users: dict[user_id -> User]
  handles: dict[handle -> user_id]        # uniqueness index
  emails: dict[email -> user_id]          # uniqueness index
  tokens: dict[token -> user_id]          # every valid bearer token, never expires
  payments: list[Payment]                 # append-only ledger, insertion order
  requests: dict[request_id -> Request]
  splits: dict[split_id -> Split]
  settlements: dict[settlement_id -> Settlement]
  idempotency: dict[(user_id, method, path, key) -> IdempotencyRecord]
  seq: int                                 # monotonic counter feeding all generated ids

User:      id, email, password_hash, display_name, handle, balance (int, minor units)
Payment:   id, from_user_id, to_user_id, amount, note, visibility, request_id | None,
           settlement_id | None, effective_at, recorded_at    # see ADR-005 on the two times
Request:   id, requester_id, payer_id, amount, note, status, payment_id | None, created_at
Split:     id, caller_id, amount, note, participant_handles (ordered), shares (ordered),
           request_ids (ordered, excludes caller), created_at
Settlement: id, operator_id, transfers (input order), payment_ids (input order), committed_at
IdempotencyRecord: key, user_id, method, path, request_body (canonical JSON value),
           status ("in_flight" | "done" | "failed"), response_status, response_body
```

`Payment.effective_at` and `Payment.recorded_at` are always equal in stage 1 (money moves
immediately, nothing is backdated or corrected). Carrying both fields now — not exposed in any
stage-1 API response beyond `created_at` (`= effective_at`) — means the single balance
function stage 3 needs ("as of" vs "as known at") can be added later without a data migration.
No stage-1 endpoint or behavior depends on the two ever differing.

## 4. Invariants and where they are enforced

| Invariant | Enforcement |
|---|---|
| Conservation (R1) | The only way balances change is `_debit(a, amt)` + `_credit(b, amt)` called together inside one lock acquisition (§5). No code path calls one without the other. Sum of balances is therefore invariant under every operation. |
| No negative balance, ever (R2) | `_debit` raises (mapped to `409 insufficient_funds`) if `balance - amt < 0`, checked and applied atomically under `STATE_LOCK`; the caller never sees an intermediate state because the whole check+apply happens before any other thread can acquire the lock. |
| Exactly once (R3, R52) | The idempotency table (§6) is the single chokepoint every one of the five write paths goes through before touching money; a slot is claimed (as `in_flight`) under the same lock acquisition used to do the work, so two concurrent identical requests can never both pass the claim step. |
| All-or-nothing (R58, R90) | Each write handler computes every check first, and only mutates state in a final block with no early return possible; settlements compute every wallet's net delta first, reject if any would go negative, then apply all deltas in one loop before releasing the lock. |
| Rounding (R76) | `compute_shares(amount, n)` (`design §7`) is a pure function used by both `/splits` and documented directly against the stage-1 table; unit-tested against all five example rows. |

## 5. Write-path algorithm (applies to all five idempotent endpoints)

Fixed order, matching §7 and R54 exactly:

1. Read and parse the JSON body. Unparseable → `400 malformed_request` (no lock, no
   idempotency interaction — R54 only starts after the body parses as an object).
2. Authenticate the bearer token. Missing/unknown → `401 unauthenticated`.
3. Require and read `Idempotency-Key`. Absent/empty → `400 missing_idempotency_key`.
4. Acquire `STATE_LOCK`. Look up `(user_id, method, path, key)`:
   - Not present → claim it as `in_flight` with the canonicalized request body attached,
     keep the lock, proceed to step 5 in the same critical section.
   - Present, `done`/`failed`-now-superseded is impossible (failed keys are deleted, see
     R51) and body matches (canonical JSON equality) → return the stored response
     (`200`, or `201` demoted to `200`; body identical) and release the lock. This is a
     replay; nothing else runs.
   - Present and body differs → `409 idempotency_key_reuse`, release the lock.
5. (Still under the same lock acquisition.) Run endpoint-specific field validation, then
   resource/state checks, then the mutation (see assumption A1/A2 for the fixed
   sub-order, and R88 for settlements' explicit order). On success: commit the mutation,
   store the response on the idempotency record as `done`, return `201`. On a 4xx
   failure: delete the claimed idempotency record (frees the key per R51's last row),
   return the error; no state mutation from this attempt persists.
6. Release the lock; write the HTTP response.

Because steps 4-5 are one lock acquisition, no other thread can observe the key as claimed
without the corresponding state mutation already applied (or fully rolled back on failure).

`POST /requests/{id}/decline` and `/cancel` skip steps 3-4's key handling entirely (no
idempotency key, per §8) but still run under `STATE_LOCK` for their state transition.

## 6. Canonical body comparison

The claimed request body is stored as the parsed JSON value (Python `dict`/`list`/scalar
tree), not as a string. "Same body" (R50) is Python structural equality (`==`) on that parsed
value — this already ignores key order and whitespace, and treats `1000`, `1000.0`, `1e3` as
equal (all parse to the numeric value `1000`) consistent with R18.

## 7. Rounding function (R76)

```
def compute_shares(amount: int, n: int) -> list[int]:
    base, remainder = divmod(amount, n)
    return [base + 1 if i < remainder else base for i in range(n)]
```
`amount=1000,n=3` → `divmod=333,1` → `[334,333,333]`. `amount=1,n=3` → `[1,0,0]`.
`amount=10,n=3` → `[4,3,3]`. `amount=999,n=3` → `[333,333,333]`. `amount=5,n=5` →
`[1,1,1,1,1]`. Matches the table exactly.

## 8. IDs, tokens, timestamps

- IDs: `f"{prefix}_{uuid4().hex}"` (`u_`, `p_`, `rq_`, `sp_`, `st_`), always ≤64 chars.
- Tokens: `secrets.token_urlsafe(32)`, opaque, never expire, map stored in `tokens`.
- Timestamps: `datetime.now(timezone.utc).isoformat()` → always carries an explicit `+00:00`
  offset, RFC 3339 compliant.

## 9. Export/import — format v1 (R78-R85)

`GET /_test/export` (under `STATE_LOCK`, so it is an atomic snapshot per R81) returns:

```json
{ "track": "pocketful", "format_version": 1, "state": { <opaque serialized State> } }
```

`state` is the JSON-serializable form of every field in §3's `State`, including:
`password_hash` (not plaintext — safe only because the harness treats exports as private test
artifacts, per spec), every entry of `tokens`, and every `IdempotencyRecord` (key, caller,
method, path, body, original response) so a replay after import still returns the original
response and moves nothing (R82). `POST /_test/import` validates `track=="pocketful"` and
`format_version==1` (else `422 validation_failed`, no change — R80), then, under
`STATE_LOCK`, discards the current `State` entirely and rebuilds it from `state` (R83).
`POST /_test/reset` discards `State` and rebuilds from the reset fixture the same way (R84),
including clearing any imported data.

`format_version` is carried explicitly so a later stage's export can be rejected by this
stage (and this stage's export accepted, unchanged, by a later stage) without guessing — this
is the version-negotiation seam the technical direction asks stage 1 to leave open, without
stage 1 implementing any multi-version logic itself.

## 10. Validation order per endpoint (assumption A1/A2)

For `/payments`, `/requests`, `/requests/{id}/pay`, `/splits` (after the idempotency step,
§5 step 5): field-shape errors (missing/wrong-type/out-of-range `amount`, `note`, `visibility`,
`participant_handles`) are checked first, in the order fields are listed in the spec's table
for that endpoint; then handle-resolution (`404 not_found`); then same-handle checks
(`self_payment`/`self_request`, which need the resolved handle); then resource-state
(`409 request_not_pending`); then balance (`409 insufficient_funds`) last, since it is the
one check the spec explicitly allows to depend on "money arriving later" (R24). Settlements
follow R88's explicit order instead (per-entry shape/handle/self-transfer errors, in input
order, before the batch's collective affordability check).

## 11. What stage 1 deliberately does not build

No HTML/UI (stage 2), no historical "as of"/"as known at" query endpoint (stage 3 — but the
ledger already carries the two timestamp fields it will need, §3), no correction/refund
endpoints (stage 3+), no multi-currency (out of scope entirely per §4). `settlement_operator_ids`
is read from the fixture and enforced, but no operator-management endpoint is added (out of
scope — spec only requires the permission to exist).
