# Pocketful — stage 1: build and run

## Build and start the service

From this directory (`stage-1/`):

```sh
docker build -t pocketful-stage1 .
docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage1
```

The service listens on `0.0.0.0:$PORT` (`PORT` defaults to `8080`). No manual setup,
no outbound network at runtime, no environment beyond the base image.

## Smoke test

```sh
curl -s http://localhost:8080/health
# -> {"status":"ok"}
```

## Seed the service

`POST /_test/reset` with a fixture body replaces all state and returns `204`:

```sh
curl -s -X POST http://localhost:8080/_test/reset \
  -H 'Content-Type: application/json' -d @fixture.json
```

See `specs/stage-1/requirements.md` §4 for the fixture format and the full API.

## Run the unit tests (host, no container)

```sh
python3 -m unittest discover -s tests
```
