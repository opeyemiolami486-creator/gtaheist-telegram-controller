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

The browser controller uses the game's public `window.__dc` state and its normal input path. It selects `wanted`, drives in PRO mode, targets coins, missions, Cold Stashes, the Vault/Rug Pull objectives when visible, and avoids cops/rugs with steering and braking. It does not patch the game score or call the score API with fabricated values.

## Notes

GTA Heist currently issues a `GH-XXXXXX` run code and nonce from `POST https://api.gtaheist.fun/api/start`. The wallet is attached with `POST /api/bind` using the same code and nonce, then the browser submits the real run through `POST /api/run`. The Telegram bot sends the card captured from the game's own end screen.
