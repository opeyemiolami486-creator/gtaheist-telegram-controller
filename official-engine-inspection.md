# Official GTA Heist Engine Inspection

Inspection date: 2026-11-08

This is a read-only inspection of the public client at `https://www.gtaheist.fun/game/`. No score submission or live run was performed as part of this inspection.

## Pinned public assets

| Asset | URL | SHA-256 | Size |
|---|---|---:|---:|
| Game HTML, including inline engine and Three.js bundle | https://www.gtaheist.fun/game/ | `a328e728da7a705a600d648839b8288f214cd6b7fbc5f6e7ea792e943031b3cd` | 2,933,195 bytes |
| `campaign.js` account/campaign wrapper | https://www.gtaheist.fun/game/campaign.js | `ff7eb566745a5a2a1316f65637c8e1996f0089aebd3c43b86aee03f7344581e0` | 95,697 bytes |
| `share-card.mjs` card renderer | https://www.gtaheist.fun/game/share-card.mjs | `411c6bbf34722c6fa8174d0177bb38aeae37a1ba22e9ee973a4876b504cb4453` | 9,762 bytes |

The HTML contains the playable engine inline. The page's external scripts are the campaign wrapper and share-card module; the game engine is not exposed as a separate importable simulation module.

## Findings

The inline engine publishes a development/debug surface as `window.__dc`. Relevant public functions and state include:

- `__dc.S`: mutable game state, including player position/velocity, bag, wanted level, timer, run state, mission state, and terminal state.
- `__dc.keys`: normal input flags such as `up`, `down`, `left`, `right`, `drift`, `boost`, and touch steering flags.
- `__dc.update(dt)`: the official simulation update function.
- `__dc.go()`: starts a normal run through the same client path as the Play button.
- `__dc.reset()`: resets the official game state.
- `__dc.finish()` and `__dc.wasted()`: official terminal transitions.
- `__dc.coins`, `__dc.rugs`, `__dc.cops`, `__dc.marker`, and `__dc.stashes`: live world objects useful for telemetry and controller decisions.
- `__dc.ghGeo()`: geometry and heist-location information.

The client uses a request-before-play flow. A normal run calls `POST https://api.gtaheist.fun/api/start` with a player ID, mode, and optional wallet. The server returns a run `code` and secret `nonce`. At the end, the client calls `POST /api/run` with the final result, including bag, duration, pause time, mode, code, nonce, and activity/card metadata. The observed client does not send an input-frame transcript or action journal.

## Feasibility assessment

A browser-based headless harness is feasible. A first non-submitting probe is implemented in `official_engine_probe.py`. It blocks `/api/start` and `/api/run`, starts offline through the normal `__dc.go()` path, pauses the animation loop, and advances the official `__dc.update(1/60)` function for controlled fixed steps. A five-second probe produced 300 official steps, reached `t=4.9833`, and recorded live player, bag, wanted, cop, pickup, rug, and input state. No score endpoint was called.

A pure Node-style clean-room replay engine is not currently feasible from the public client alone. The engine is embedded in a browser page, relies on DOM/canvas/Three.js globals, and uses `requestAnimationFrame` frame deltas. It also contains ordinary `Math.random()` calls during gameplay and object/effect generation. The public `/api/start` response observed by the current controller provides a code and nonce, not a deterministic world seed or rules-version contract.

Therefore, headless predictions will only be trustworthy if the prediction and the submitted run occur in the same loaded page state, or if the page's random and timing inputs are fully controlled and shown to reproduce the same world. Two uncontrolled five-second probes diverged, including bag and position, despite identical input. With an injected test-only PRNG seed of `12345`, two independent probes produced byte-for-byte identical telemetry traces. This demonstrates that randomness is controllable for offline experiments, but it does not prove that the live server supplies or accepts a client-selected seed. Running a separate local simulation and then submitting an unrelated browser result would not provide a reliable match.

## Safe implementation path

1. Pin the HTML and wrapper hashes above and fail closed when they change.
2. Load the pinned official page in headless Chromium.
3. Wait for `window.__dc` and call `__dc.reset()` before each local diagnostic.
4. Start with `__dc.go()` and feed normal key flags only.
5. Advance the exact official `__dc.update(dt)` function while recording state and object telemetry.
6. Compare headless telemetry against the existing browser runner over short offline runs.
7. Only after matching positions, bag, pickups, wanted transitions, and terminal duration should the harness be allowed to use the unchanged official `/api/start` and `/api/run` flow.
8. Treat `/api/run` responses as authoritative; never synthesize final score fields or bypass the nonce/code flow.

## Bottom line

The official client exposes enough of its own engine to build a stronger headless controller, but the correct implementation is a browser-based official-engine harness, not a standalone replay submitter. The immediate next engineering task is a local, non-submitting Chromium harness that drives `window.__dc.keys` and `window.__dc.update(dt)` and proves telemetry equivalence with the existing runner.
