# Pocketful, built by the CoolHackers delivery line

Team **CoolHackers**, WeAreDevelopers × BAND "Dark Factory" hackathon, **pocketful** track.

A band of five Band seats built this whole wallet service, all four stages. It worked in one
room, plus a continuation room after the first reached Band's message limit.
Humans wrote this README, `FACTORY.md`, and the setup that created the seats. Every file under
`stage-N/` and `specs/` came out of the room, and all 132 commits on `main` were made by a seat.

| Stage | Verified revision | Shipped checks (isolated mode) | Wall-clock |
|---|---|---|---|
| 1 | `1d76d56` | pass, `claimed stage: 1` | 16:16 → 20:26 (30 Sep) |
| 2 | `4011bc5` | stages 1–2 pass, `claimed stage: 2` | 20:38 → 02:59 |
| 3 | `5a4beac` | stages 1–3 pass, `claimed stage: 3` | 04:09 → 09:39 (1 Oct) |
| 4 | `9acfae4` | stages 1–4 pass, `claimed stage: 4` | 12:44 → 17:45 |

Times are CEST, from the dispatch message to the coordinator's stage report.

## What is here

| Path | What it is |
|---|---|
| `stage-1/` … `stage-4/` | The service at each stage: `Dockerfile`, `RUN.md`, source and unit tests |
| `specs/stage-N/` | Seat-written requirements, design and ADRs, task list, the tester's acceptance suite, the reviewer's probes, `verification.md`, `report.md` |
| `mandates/` | The standing instructions of each seat, with its harness and model |
| `room.json` | The Band room for stages 1–4 (until the room reached Band's message limit), as downloaded |
| `room-2.json` | The continuation room where stage 4 finished (see `FACTORY.md` § Human input) |
| `FACTORY.md` | How the factory works, what failed, cost and time, and how it catches bad results |

## Run a stage

Each stage folder is self-contained. Follow its `RUN.md`, for example:

```sh
cd stage-4 && docker build -t pocketful-stage4 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage4
curl -s http://localhost:8080/health   # {"status":"ok"}
```

The factory's source (the mandate generator, seat setup and timekeeper) lives in the team
repository: https://github.com/June24-optimize/Hercules-coolhackers
