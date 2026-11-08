# Early-Survival Analysis

Date: 2026-11-08

## Confirmed live-attempt failure

The approved live attempt ended with the official terminal state `busted` / `caught` at approximately 11.7 simulation seconds. The strongest evidence is police contact: the minimum sampled cop distance was approximately 0.335 world units, with 13 sampled or interpolated candidates below the analyzer's 1.5-unit threshold. Exact collision radius is not exposed, so this remains telemetry-supported rather than an authoritative collision callback.

The important precursor was loss of mobility. The player reached roughly 37.5 speed early, then became nearly stationary around a repeated `z = -28.8` coordinate. Low speed and repeated position persisted before the cop reached danger range. The controller continued objective-oriented steering until the cop was already close, then entered hard escape only at the existing `<22`-unit threshold. During the closing phase it also switched `coin -> vault -> coin`, which is undesirable target thrashing during a pursuit.

## Interpretation of boost and police phasing

The user's observation that boost can move the player away faster is consistent with using boost during an escape lane, so the new controller allows boost during escape when the nearest cop is not already inside an approximately 3-unit emergency distance and the heading is aligned. This is an engineering hypothesis, not a measured official rule.

The observation that the player sometimes phases through police cars is retained as a hypothesis for future analysis. The controller does not intentionally seek police contact or assume phasing is reliable. It records close approaches and uses escape steering; only repeated official traces can determine whether a sub-collision-distance crossing sometimes survives.

## Implemented offline changes

The browser controller now has three escape states:

- `clear`: normal objective selection.
- `escape`: entered when a cop is within approximately 55 units, closing rapidly, or projected to contact within about 3 seconds.
- `hard_escape`: entered below approximately 28 units or with projected contact within about 1.2 seconds.

Escape mode clears the active target, freezes objective switching, and uses a cop-repulsion heading. It releases only after the nearest cop is beyond approximately 75 units and no longer closing for about one second.

Stuck recovery now begins after 8 low-displacement frames rather than 12 and cycles through short recovery phases. It records recovery attempts and uses reverse/turn or forward/turn maneuvers with drift; during an escape it may use boost when the lane is not at immediate contact distance.

New telemetry fields include `escapeState`, `copClosingSpeed`, `timeToContact`, `recoveryAttempts`, `belowSpeed`, escape-state events, and recovery-start events. Summary metrics now include first escape time, low-speed fraction, maximum cop closing speed, minimum projected time to contact, recovery-attempt count, and target switches during threat.

## Tests and synthetic benchmark

The complete offline suite passes: **41 tests**, with Python compilation successful.

The fixed 20-seed clean-room benchmark remains:

| Metric | Post-change synthetic result |
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

This is unchanged from baseline because the clean-room simulator is not yet calibrated to the official engine and does not execute the browser controller's new JavaScript state machine. It must not be interpreted as evidence that the official controller improved or failed to improve.

## API-blocked official-engine probes

All successful probes used the pinned official client, blocked `/api/start`, `/api/run`, and `/api/bind`, and did not submit anything. A transient page-load failure occurred in one parallel attempt; it was retried once successfully.

| Probe | Terminal | Minimum cop distance | First escape | Low-speed fraction | Recovery attempts | Threat target switches | Minimum TTC |
|---|---|---:|---:|---:|---:|---:|---:|
| A | time limit, not busted | 67.09 | 6.25s | 0.381 | 11 | 0 | 7.56s |
| C | time limit, not busted | 8.44 | 3.90s | 0.009 | 0 | 0 | 1.24s |
| B retry | time limit, not busted | 67.67 | 6.85s | 0.348 | 14 | 0 | 8.26s |

Probe C is the strongest early-survival result: the player maintained movement, entered escape early, reached hard escape at approximately 9.05 seconds, and still reached the 10-second time limit without an official `busted` terminal. Probes A and B maintained large cop separation but spent a substantial fraction of frames below the speed threshold and triggered recovery repeatedly. This means the new escape state is working, but the recovery controller is still too eager or too repetitive in some layouts.

The `caught_flag` field was true in some time-limit snapshots even though the terminal kind was `time limit`; those runs are classified by terminal kind as time-limit runs, not busted runs. This appears to be a stale or overloaded official state field and should not be used alone to classify terminal cause.

## Next improvements justified by evidence

1. Add recovery hysteresis and a cooldown. After a recovery maneuver, require a displacement test before starting another attempt. Cap repeated attempts and rotate to a substantially different heading instead of cycling the same maneuver.
2. Record the repeated-coordinate region and penalize its heading for several seconds. The live run's repeated `z = -28.8` position is the clearest evidence of a local trap.
3. Couple recovery to predicted cop contact. If the player is stuck while time-to-contact is falling, prioritize a forward boost-and-turn escape phase rather than repeated reverse-only phases.
4. Keep boost enabled through a validated escape lane, including when the cop is close enough that phasing might occur, but do not deliberately aim for police until repeated official traces establish that phasing is reliable.
5. Add a differential official-probe report over more fixed-length samples before considering another live submission. The next gate should be lower low-speed fraction and fewer recovery retries without increasing close approaches.

No second live attempt is justified yet. The current evidence supports more API-blocked official probes and recovery tuning, not another submission.

## Second approved live attempt with tuned controller

After explicit approval, one new live 90-second attempt was run with the recovery cooldown and displacement-based recovery changes. The official `/api/start` returned HTTP 200 with `ok: true`; no `/api/run` request or response was observed, and the run was not reported as submitted or verified.

The tuned attempt lasted approximately **38.8 simulation seconds**, compared with approximately **11.7 seconds** in the previous live attempt. It collected 1 pickup, completed 0 missions, banked 0, and ended with 0 remaining bag. It used only 1 recovery attempt, had a low-speed fraction of approximately 9.2%, and recorded 0 target switches during threat. These are meaningful improvements over the previous live trace's early loss of mobility and target thrashing.

The run still ended `busted` / `caught`. A second police wave became visible around 41.5–42.5 seconds, cop distance fell from about 78.9 to 27.5, projected time-to-contact reached approximately 0.084 seconds, and the closest sampled approach was approximately 0.276 units. The controller entered `hard_escape` at about 45.7 seconds, but the cop was already effectively at contact range. The current remaining gap is therefore late-pursuit interception after an otherwise much longer survival period, not the original immediate startup trap.

The result is encouraging but not sufficient to claim reliable survival or score capability. No additional live attempt is justified without another explicit approval.
