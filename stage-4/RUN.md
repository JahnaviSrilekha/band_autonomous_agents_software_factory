# Pocketful — stage 4: build and run

## Build and start the service

From this directory (`stage-4/`):

```sh
docker build -t pocketful-stage4 .
docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage4
```

The service listens on `0.0.0.0:$PORT` (`PORT` defaults to `8080`). No manual setup,
no outbound network at runtime, no environment beyond the base image — fonts,
scripts and stylesheets are all bundled under `src/pocketful/ui/static/`.

## Smoke test

```sh
curl -s http://localhost:8080/health
# -> {"status":"ok"}
```

## Screens

The browser UI is served from the same port:

| Route | Screen |
|---|---|
| `/` | Balance, pay form, request form and the activity feed |
| `/requests` | Incoming and outgoing requests, with pay, decline and cancel |
| `/split` | Split form |
| `/authorizations` | Authorise form, holds list with capture and void |
| `/signup` | Signup |
| `/login` | Login |

`/requests` and `/authorizations` also speak the JSON API: with `Accept: text/html`
they render the page; without it they return JSON. Pages authenticate the browser
via the `pocketful_token` cookie, set by the UI's JavaScript after signup/login
(the JSON API itself keeps using `Authorization: Bearer`).

## Seed the service

`POST /_test/reset` with a fixture body replaces all state and returns `204`:

```sh
curl -s -X POST http://localhost:8080/_test/reset \
  -H 'Content-Type: application/json' -d @fixture.json
```

The stage-4 fixture is unchanged from stage 3: seeded payments and seeded
authorizations accept an optional RFC 3339 `created_at` (offset required; a future
value is rejected with `422` and no state change; omission uses the reset instant).
Openings equal the declared balances minus the net of the seeded payments (R180),
and a seeded history that would overdraw an account is rejected. A stage-1-,
stage-2- or stage-3-shaped fixture without any of this still resets cleanly. See
`specs/stage-4/requirements.md` for the fixture format and the full API.

## Stage 4 API additions

- `POST /payments/{payment_id}/refunds` — refund a payment (idempotency key
  required; original receiver only; a refund target must not itself be a refund;
  cumulative refunds may not exceed the payment's current corrected amount; moves
  existing money from the receiver's available funds atomically). A refund is a
  new payment in the opposite direction carrying `refund_of`.
- `POST /correction-batches` — correct 1-32 payments in one idempotent request
  (settlement operator required). Per-item validation runs in input order, then
  settlement completeness and shared effective instants, then combined current and
  historical funds checks; a rejected batch changes nothing. Correcting any
  settlement member requires including every member; captures and refunds remain
  immutable. Every revision created by a batch carries `correction_batch_id`, and
  all of a batch's revisions share one `recorded_at`.
- Single-payment corrections follow stage 4's extended rules: captures and refund
  payments are 422 `linked_payment_immutable`, and a correction may not reduce a
  payment below its already-refunded amount (422 `refund_exceeds_payment`).

## Still available from earlier stages

- `POST /payments/{payment_id}/corrections` — single-payment corrections.
- `GET /payments/{payment_id}/revisions` — full revision history, parties only.
- `GET /me?as_of=…&known_at=…` — temporal wallet view; `as_of` inclusive at the
  instant, `known_at` selects each payment's latest revision recorded at or before it.
- `GET /statement?from=…&to=…&limit=…&offset=…` — paginated statement, oldest
  first, with `opening_balance`/`closing_balance` over the half-open window; the
  first response also returns an opaque `snapshot` token that pages the frozen
  result (`GET /statement?snapshot=…&limit=…&offset=…`).
- `GET /_test/export` / `POST /_test/import` — export is `format_version: 4`
  (adds `refund_of` per payment and `correction_batch_id` per revision); import
  still accepts format versions 1, 2 and 3.

## Run the unit tests (host, no container)

```sh
python3 -m unittest discover -s tests
```
