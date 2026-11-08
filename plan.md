# GTA Heist Controller Plan

## Objective

Replace the legacy bot with a GTA Heist controller for `gtaheist.fun` that runs the hardest `wanted` level, obeys `/Play <username> <wallet address>`, stops at a requested score or time limit, and sends the game-generated result card to Telegram.

## Design

The runner uses Playwright against the real public game. It selects `wanted` and PRO controls, reads only the game’s exposed controller state, and writes normal input flags. The planner prioritizes active missions, token pickups, heist markers, and Cold Stashes while steering away from police threats. The server remains the source of truth for scores and run verification.

The browser captures the server-issued `GH-XXXXXX` ticket and nonce. After the game submits the completed run through its own `/api/run` flow, the runner follows the official verification/share sequence and calls `/api/bind` with the same code, nonce, and Telegram-provided wallet. The card is captured from the game’s own end screen and uploaded by Telegram as a photo.

## Project structure

- `planner.py`: pure target-selection and steering decisions.
- `runner.py`: real browser automation, game lifecycle, verification, wallet binding, and card capture.
- `telegram_bot.py`: `/play`, `/stop`, and Telegram photo delivery.
- `test_planner.py`: deterministic unit tests.

## Acceptance status

Implemented: GTA Heist-only support, wanted mode, wallet/run-code path, score/time termination, official card capture, Telegram integration, no fabricated score submission, and planner tests.

Open tuning: a legitimate high-score run needs longer live trials and iterative steering/path improvements. Short smoke runs intentionally end before they can qualify for server verification.
