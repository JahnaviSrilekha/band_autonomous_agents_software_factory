# ADR-003: `hashlib.scrypt` for password hashing, run outside `STATE_LOCK`

## Context

R47: passwords must be stored using bcrypt/scrypt/Argon2/equivalent, never plaintext. The
technical direction separately requires "password hashing happens outside that critical
section" (the global lock, ADR-002) — scrypt with reasonable cost parameters takes tens of
milliseconds, and holding the global lock for that long on every signup/login would stall
every other in-flight request (payments, reads) for the same duration, which risks the 5s
timeout under concurrent auth traffic.

## Options

1. `hashlib.scrypt` (stdlib, no dependency) with fixed cost parameters (`n=2**14, r=8, p=1`,
   a 16-byte random salt per user, stored as `salt:hash` hex).
2. A vendored pure-Python bcrypt/Argon2 implementation — extra code to audit, no stdlib
   support, contradicts ADR-001's no-third-party-dependency stance without a recorded reason
   to override it.

## Decision

Use option 1. Sequencing:
- **Signup**: compute `scrypt(password, salt=new random salt)` *before* acquiring
  `STATE_LOCK`. Then acquire the lock, re-check email/handle uniqueness (an in-memory dict
  lookup, not the hash), and either commit the new user (with the pre-computed hash) or fail
  with `409 email_taken`/`409 handle_taken` — the hash computed for a signup that turns out to
  lose the uniqueness race is simply discarded.
- **Login**: acquire the lock only long enough to look up the user by email and copy out
  their stored hash, release the lock, then verify the candidate password against that hash
  outside the lock, then return the token (token lookup, if any, does not require the lock —
  the token itself is generated fresh and inserted under a second short lock acquisition).

## Consequences

- The global lock is only ever held for cheap dict/list operations, never for a scrypt call,
  so a burst of signups cannot starve concurrent payment traffic.
- Signup does a small amount of wasted hashing work when two concurrent signups race for the
  same email/handle (at most one loses); this is the accepted cost of keeping the lock
  short-held, and is invisible to the API (the loser still gets the correct `409`).
