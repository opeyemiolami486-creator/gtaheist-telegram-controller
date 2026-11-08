# GTA Heist Telegram Controller

A GTA Heist controller for `gtaheist.fun` that plays the hardest `wanted` mode through the real browser game, keeps the server-issued run code and nonce, binds `/play <username> <wallet address>` to that run, and sends the finished share card to Telegram.

## Commands

- `/play <username> <wallet address> [target_score] [time_limit_seconds]`
- `/stop`
- `/help`

`target_score` defaults to `6000000000` and `time_limit_seconds` defaults to the game's 90 seconds. The controller stops normally at the score target, game over, or the requested time limit. It never submits a client-supplied score: the GTA Heist API remains authoritative.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
python3 telegram_bot.py
```

For a headless smoke run without Telegram:

```bash
python3 runner.py --username sandboxbot --wallet <valid-solana-address> --target 10000 --time-limit 15 --headed false
```

The browser controller uses the game's public `window.__dc` state and its normal input path. It selects `wanted`, drives in PRO mode, targets coins, missions, Cold Stashes, the Vault/Rug Pull objectives when visible, and lets police avoidance override collection when risk is high. It does not patch the game score, rewrite the official duration, or call the score API with fabricated values. The requested limit is evaluated against the official decreasing simulation clock; a wall-clock watchdog only prevents a hung browser.

Each run writes `last-result.json`. Its `run` object contains per-frame telemetry (player motion, input state, target, police distance, threat, wanted level, bag/bank/pickups, simulation time and wall time) and the captured `/api/run` request payload and response. The diagnostic capture also records `S.time`, `S.t`, `S.ts`, `S.paused`, `window.__ghP`, visibility state, and frame timestamps, making clock mismatches reproducible without modifying the official request.

## Notes

GTA Heist currently issues a `GH-XXXXXX` run code and nonce from `POST https://api.gtaheist.fun/api/start`. The wallet is attached with `POST /api/bind` using the same code and nonce, then the browser submits the real run through `POST /api/run`. The Telegram bot sends the card captured from the game's own end screen.

## Validation

```bash
python3 -m py_compile planner.py runner.py telegram_bot.py
python3 -m unittest -v test_planner.py
python3 runner.py --username sandboxbot --wallet <valid-solana-address> --target 10000 --time-limit 10 --headed false --out-dir run-artifacts/diagnostic-10
```

Only treat a live run as successful when the captured `/api/run` response is verified by the game and `/api/bind` succeeds. Live runs require a valid wallet and network access; unit tests do not submit anything.

## Direct official-engine controller

`dc_controller.py` drives the public game's own `window.__dc` surface in a headless Chromium page. It sets only normal movement flags in `window.__dc.keys`, uses the official client update loop and terminal transitions, captures the untouched `/api/run` request/response, and never invents a score, nonce, or run code.

The default is an isolated dry run. It blocks `/api/start`, `/api/run`, and `/api/bind`, so it cannot create or submit a live score:

```bash
python3 dc_controller.py --time-limit 10 --out-dir run-artifacts/dc-dry-run
```

The live path is opt-in with `--submit`. In that mode the browser uses the site's normal server-issued `/api/start` code and nonce, then the official client submits its own `/api/run` payload:

```bash
python3 dc_controller.py --username Bigdawg \
  --wallet YOUR_WALLET \
  --target 7000000000 --time-limit 90 --submit \
  --out-dir run-artifacts/dc-live-90
```

`official_engine_probe.py` remains the non-submitting fixed-step probe for reproducibility experiments.

## Clean-room headless sandbox

`headless_sandbox.py` is an independent, offline approximation of the observed public state contract. It models movement, pickups, mission markers, stashes, cops, hazards, wanted level, banking, a simulation clock, and the controller's input flags. It contains no copied game source or assets and never contacts the official game or submits a score. This makes it suitable for deterministic policy comparisons before live validation:

```bash
python3 headless_sandbox.py
python3 -m unittest -v test_planner.py test_headless_sandbox.py
```

The sandbox's `over_7b_rate` is a synthetic benchmark under its explicitly configured reward model, not evidence of an official 7B run. Only an official `/api/run` response with `verified: true` can establish a real score.
