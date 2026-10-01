# Pocketful — stage 2: build and run

## Build and start the service

From this directory (`stage-2/`):

```sh
docker build -t pocketful-stage2 .
docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage2
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

The stage-2 fixture adds `authorization_ttl_seconds` (default 600) and an
`authorizations` array; a stage-1-shaped fixture without them still resets cleanly.
See `specs/stage-2/requirements.md` for the fixture format and the full API.

## Run the unit tests (host, no container)

```sh
python3 -m unittest discover -s tests
```
