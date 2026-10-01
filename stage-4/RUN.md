# Pocketful — stage 3: build and run

## Build and start the service

From this directory (`stage-3/`):

```sh
docker build -t pocketful-stage3 .
docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage3
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

The stage-3 fixture is the stage-2 fixture plus timestamps: seeded payments accept
an optional RFC 3339 `created_at` (offset required; a future value is rejected with
`422` and no state change; omission uses the reset instant), and seeded
authorizations do the same. Openings equal the declared balances minus the net of
the seeded payments (R180), and a seeded history that would overdraw an account is
rejected. A stage-1- or stage-2-shaped fixture without any of this still resets
cleanly. See `specs/stage-3/requirements.md` for the fixture format and the full API.

## Stage 3 API additions

- `POST /payments/{payment_id}/corrections` — append an immutable revision to an
  eligible payment (idempotency key required; sender only; linked payments
  immutable; funds checked against current and historical balances).
- `GET /payments/{payment_id}/revisions` — full revision history, parties only.
- `GET /me?as_of=…&known_at=…` — temporal wallet view; `as_of` inclusive at the
  instant, `known_at` selects each payment's latest revision recorded at or before it.
- `GET /statement?from=…&to=…&limit=…&offset=…` — paginated statement, oldest
  first, with `opening_balance`/`closing_balance` over the half-open window; the
  first response also returns an opaque `snapshot` token that pages the frozen
  result (`GET /statement?snapshot=…&limit=…&offset=…`).

## Run the unit tests (host, no container)

```sh
python3 -m unittest discover -s tests
```
