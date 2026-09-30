# ADR-007: Server-rendered pages + one vanilla-JS file, no framework/build step

## Context

Stage 2 must deliver a browser UI (§ Routes) that: shares routes with the JSON API via
`Accept` negotiation (R95/R152); works with no outbound network at runtime (spec §2 —
"Bundle every runtime asset... No CDN links"); implements client-side idempotency-key
reuse, latest-wins sequencing, and uncertain-outcome retry entirely in the browser
(R102/R111/R113); and must not require a page reload for in-page state updates (R110). The
run's technical direction restricts stage 1 to "Python 3.12 standard library unless the
coordinator records a better reason"; that direction is scoped to the service, and nothing
in stage-2.md asks for a specific frontend stack.

## Options

1. A frontend framework (React/Vue/etc.) with a build step, bundled into the image at
   `docker build` time (network available then, per spec §2) and served as static output.
2. Server-rendered HTML via stdlib string templates, one hand-written vanilla JS file for
   the interactive behavior, no build step, no framework dependency.

## Decision

Option 2. Every required page is rendered server-side as a plain HTML document (Python
string templates, no third-party templating library — consistent with the stack's existing
"standard library only" bias, ADR-001). A single static `/static/app.js` file implements
the client behaviors enumerated in design.md §11 (idempotency-key derivation, sequence
numbers, uncertain-outcome retry, decimal parsing, split preview).

## Consequences

- No build step means no risk of a build-time dependency (npm registry, etc.) becoming
  unavailable and no extra image-size/attack-surface from a bundler; `docker build`'s
  network window (spec §2) is unused, keeping the build simple and reproducible.
- All runtime assets are trivially "bundled" (R"Bundle every runtime asset... No CDN
  links") by construction — there is exactly one JS file and it ships in the image.
- Server-rendering means each route's HTML and its JSON sibling share a handler (R95/R152),
  reducing the chance the two drift apart on visibility/shape rules.
- Cost: no component reactivity system — the JS file manages DOM updates directly (e.g.
  replacing `activity-list`'s children after a successful refresh). This is judged
  acceptable at stage 2's scope (a handful of pages, no complex client-side state beyond
  what design.md §11 already lists); revisit only if a later stage's UI requirements grow
  substantially past this.
- Visual/CSS quality (R97-R99) is achieved with hand-written CSS shipped alongside
  `app.js`, not a design-system library — consistent with "no CDN links" and "bundle every
  runtime asset."
