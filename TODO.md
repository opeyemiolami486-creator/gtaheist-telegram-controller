# Delivery checklist

- [x] Use GTA Heist naming and API paths throughout the controller.
- [x] Support `/Play <username> <wallet address> [target score] [time limit seconds]`.
- [x] Run the hardest `wanted` mode through the real browser game.
- [x] Stop normally at the target score or time limit through the game’s own end-state methods.
- [x] Keep server-issued run code and nonce; follow the official verification flow before wallet binding.
- [x] Capture the official end card and send it to Telegram.
- [x] Unit-test the planner and run a real headless smoke session.
- [ ] Tune and validate a legitimate >6B live run; do not mark complete until the server reports it as verified.
