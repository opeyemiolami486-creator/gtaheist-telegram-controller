# GTA Heist Controller Evidence Report

Inspection and testing date: 2026-11-08

## Scope and safety boundary

This report covers repository inspection, offline tests, a pinned-asset API-blocked browser dry run, the clean-room simulator benchmark, and one explicitly approved live account attempt. No wallet binding or manually constructed `/api/run` request was performed. The live attempt used the supplied account only through the official client flow.

The official client asset preflight succeeded for the pinned game HTML, `campaign.js`, and `share-card.mjs` hashes recorded in `official-engine-inspection.md`. The browser harness refuses to continue if those bytes or the configured site change.

## Baseline repository behavior

The checkout was clean at the start. The existing controller drove the public `window.__dc.keys` surface and allowed the official client to own state transitions. Its default dry-run route aborted `/api/start`, `/api/run`, and `/api/bind`, but its in-page fetch wrapper retained raw request and response content and the browser was closed immediately after the controller returned.

The pre-change offline suite contained 37 tests and passed. The 20-seed clean-room benchmark produced:

| Metric | Baseline |
|---|---:|
| Episodes | 20 |
| Mean score | 165,000,000 |
| Score standard deviation | 275,726,313.6 |
| Minimum / maximum score | 0 / 1,050,000,000 |
| Survival to 90 seconds | 95% |
| Mean bank | 5,000,000 |
| Mean bag | 160,000,000 |
| Mean pickups | 1.0 |
| Mean missions | 0.1 |
| Synthetic over-7B rate | 0% |

These numbers are simulator-only and are not evidence about the official game.

## Implemented changes

`dc_controller.py` now registers Playwright `request` and `response` listeners, in addition to the existing in-page fetch observation. This covers browser-level fetch/XHR-style traffic and does not depend on monkey-patching one JavaScript API. The recorded request data is limited to endpoint path, method, resource type, and whether a body exists. Response data is limited to endpoint path, HTTP status, resource type, and safe JSON fields (`ok`, `verified`, `error`, and `status`). Wallets, nonces, codes, score payloads, and raw bodies are not retained.

The controller now waits two seconds after the official controller reaches a terminal state, then drains pending response observers. It still does not manufacture or manually call any endpoint. This bounded wait exists only to observe the official client’s own terminal behavior.

Four redaction and endpoint-filtering regression tests were added. The full suite now contains 41 tests, all passing, and the modified Python files compile successfully.

## Official-engine dry-run evidence

Command used:

```bash
python3 dc_controller.py --time-limit 10 \
  --out-dir run-artifacts/dc-dry-run-redacted
```

This run was API-blocked and used the pinned public client. Observed browser-level API traffic:

```json
[
  {"path": "/api/start", "method": "POST", "resource_type": "fetch", "has_body": true}
]
```

Observed API responses: none. In particular, no `/api/run` request or response was observed in the blocked dry run. The client reached the controller’s bounded simulation time-limit terminal path; the captured state reported `run: false`, `over: true`, and `verified: null` after the terminal wait. Because `/api/start` was aborted, this run cannot establish what the server would return for a real run.

The same dry run recorded one blocked `/api/start`, zero run requests, zero run responses, zero observed missions, and zero pickups in that particular randomized layout. Its closest sampled cop approach was 37.18 world units. The earlier baseline dry run, before the diagnostic change, demonstrated the unsafe failure mode more directly: a cop reached a sampled distance of about 0.30 and the official state ended as `busted` at about 9.4 simulation seconds, with one pickup and no missions. These are sampled telemetry values, not authoritative collision callbacks.

## Mechanics ledger

| Mechanic | Evidence | Confidence | Status |
|---|---|---:|---|
| Normal movement is controllable through `window.__dc.keys` and official updates | Pinned-client inspection and successful dry run | High | Observed |
| Official state exposes player, bag, wanted/stars, pickups, cops, mission, stashes, and terminal flags | `official-engine-inspection.md` and dry-run telemetry | High | Observed |
| `/api/start` is requested before a normal run | Browser-level dry-run request listener | High | Observed |
| `/api/run` is not guaranteed to occur in an API-blocked offline terminal path | No `/api/run` request in the blocked dry run | Medium | Observed for this path only |
| Terminal callback may need a post-terminal observation window | Controller previously closed immediately; updated harness waits two seconds | Medium | Engineering safeguard, not yet validated against an allowed live response |
| Cop slots can be tracked across adjacent frames | Trace analyzer behavior | Medium | Approximation; no authoritative entity IDs |
| Cop collision radius, exact spawn rules, banking rules, and mission rules | No local prior artifacts; one short dry run is insufficient | Low | Unresolved |
| Clean-room simulator dynamics match the official engine | No differential telemetry set exists | Low | Not established |

## Calibration conclusion

The simulator must not currently be used to predict an official score or select a submission policy. There are no prior `run-artifacts/` traces in this checkout, and the single new dry-run trace is too short and randomized to calibrate acceleration, braking, boost, collision, pickup radius, banking, or police rules. The trace analyzer correctly reports three first-observed cop appearances, a recorded-speed mean of 18.65, a maximum of 35.81, and no collision candidate under its 1.5-unit threshold, but those are telemetry summaries rather than engine rules.

## Current diagnosis and next justified step

The strongest evidence-backed diagnosis is that early survival is the dominant gap: in the approved live run, police proximity escalated rapidly and the official client ended as `busted`; the current simulator’s much stronger 95% survival result cannot be treated as predictive. The new diagnostics established that `/api/start` returned successfully, but no `/api/run` request or response was observed before terminal state.

No claim of 6,000,000,000 capability is justified. Only an official server response with verified success could establish a submitted score.

## Approved live attempt

One live attempt was run after explicit approval, using the supplied account and wallet, a 90-second limit, and a 6,000,000,000 target. The controller used the official client flow and did not manually call `/api/run` or `/api/bind`.

Safe browser-level lifecycle evidence from that attempt:

| Endpoint | Method | Status | Safe fields |
|---|---|---:|---|
| `/api/start` | POST/fetch | 200 | `ok: true` |
| `/api/run` | not observed | — | — |

The official client ended as `busted` after about 11.7 simulation seconds, with 2 pickups, 0 missions, 0 banked, and 0 bag remaining. The sampled minimum cop distance was about 0.335 world units and maximum threat was about 0.996. The controller therefore reports `submitted: false`; there is no verified score response and no basis for a 6B claim.

After the attempt, the saved artifact was scrubbed and verified to contain no wallet, nonce, or server-code fields. The serializer was also tightened so future artifacts and CLI output remove those fields before persistence.
