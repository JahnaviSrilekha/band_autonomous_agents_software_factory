# timekeeper

Harness: Band CLI script
Model: none

This seat is a program, not a model. It never reads, decides or replies.

- While a stage runs, it sends `@coordinator` one short message every 15 minutes: a clock
  tick with the current time. The tick carries no task and asks no question.
- It is started with each stage's dispatch and stopped when the stage report is posted.

## Your band, by name

| Seat | Handle | Owns |
|---|---|---|
| coordinator | `@coordinator` | requirements list, design, task list, routing, stage and final reports |
| tester | `@tester` | completeness review, black-box acceptance suite, interface checks |
| developer | `@developer` | implementation of assigned tasks, with unit tests |
| reviewer | `@reviewer` | task review, merges, stage verification; can block |
| timekeeper | `@timekeeper` — you | sends @coordinator a clock tick every 15 minutes (a program, not a model) |

Use only these seats and their literal handles. If the human configured different names, update this table and every handle in this file. Do not search for, recruit or substitute other agents.
