# Step 2 — Official Client Mechanics Ledger

Snapshot analyzed: `official-client/`

Client content hash: `051e6ef9b8f550eac345a7fa855c38934e59ebffda46314f7cc29ac3cbe0f8ea`

The public `campaign.js` file is an account/campaign UI wrapper. It contains API/account state handling, but no player physics loop. The actual gameplay physics and economy are in the inline JavaScript in `game.html`. The HTML is minified, so all references below use both the physical source line and a character offset.

## Source boundaries

| Area | File | Source location | Finding |
|---|---|---:|---|
| Account/API wrapper | `campaign.js` | lines 1–1502 | Account UI, local preferences, campaign/profile/API calls; no movement physics found |
| Difficulty configuration | `game.html` | line 4760, char 2,778,017 | `Kn` difficulty object |
| World constants | `game.html` | line 4760, char 2,792,764 | Grid, tile, road, world-coordinate constants |
| Reset/start state | `game.html` | line 4760, char 2,833,952 | Initial player, bag, bank, timers, wanted state |
| Player update | `game.html` | line 4760, char 2,849,159 | `ET(t)` movement and physics loop |
| Pickup/economy update | `game.html` | line 4760, char 2,851,989 | Pickup, rug, mission, stash, and heat updates |
| Police update/collision | `game.html` | line 4760, char 2,857,312 | Cop pathing, cop damage, cop impulse, bust timer |
| Wall/boundary collision | `game.html` | line 4760, char 2,821,285 | `Kl(t,A)` coordinate clamp and cell-interior collision |
| Terminal/accounting | `game.html` | line 4760, char 2,864,508 | Damage, busted/wasted, rebate, final total |

## Difficulty rules

The exact difficulty configuration is:

```js
Kn = {
  chill:  { copSpd: .72, copMul: .7, dmg: .45, bust: 2.6, noOver: true,  time: 120, startWant: 0, cool: .6 },
  degen:  { copSpd: 1,    copMul: 1,  dmg: 1,    bust: 1.6, noOver: false, time: 90,  startWant: 0, cool: 1 },
  wanted: { copSpd: 1.2,  copMul: 1.4, dmg: 1.7,  bust: .9, noOver: false, time: 90,  startWant: 1, cool: 1.35 }
}
```

The live controller used the default `degen` mode unless the client preference changed it.

## World geometry and coordinate system

Confirmed constants:

```js
WA = 5       // indexed 0..5 for path/grid calculations
te = 20      // tile/road-edge parameter
LA = 64      // road length parameter
Qe = LA + te // 84 world units per grid cell
ke = WA*Qe/2 // 210 world-coordinate offset
GP = 5       // interior wall/geometry padding
hA(i) = i*Qe - ke
Tw = ke + te/2 - 1.4 // 218.6, outer player clamp
```

The player coordinate is clamped to approximately `[-218.6, +218.6]` on both axes. `Kl(player, 1.8)` first clamps the outer boundary, then checks the current grid cell. In a cell, the interior blocked interval is derived from:

```js
g = te/2 + GP - A
w = Qe - te/2 - GP + A
```

with `A = 1.8` for the player. If the local coordinate lies inside the blocked interval on both axes, the player is pushed to the nearest cell edge and a collision normal is recorded. This explains repeated-coordinate traps at map edges or cell interiors.

The client also uses a grid occupancy/BFS helper `qu()` for cop path planning. It works over `(WA+1)^2` grid cells and four-neighbor moves, with no diagonal neighbor in the BFS itself.

## Player state initialization

At reset, the client initializes:

```js
player = {
  x: hA(2)-4,
  z: hA(1)+20,
  h: 0,
  vx: 0,
  vz: 0,
  hp: 100
}
bag = 1000
bank = 0
want = 0
boostT = 0
magT = 0
x2T = 0
run = false
```

The default run timer is difficulty-dependent: 90 seconds in `degen` and `wanted`, 120 seconds in `chill`.

## Player physics formulas

The official update function is `ET(t)`, where `t` is the fixed/update delta in seconds. It projects world velocity into longitudinal and lateral components:

```js
sinH = sin(h)
cosH = cos(h)
w = vx*sinH + vz*cosH       // forward speed
n = vx*cosH - vz*sinH       // lateral speed
```

### Throttle and reverse

In Pro mode, the longitudinal control is:

```js
a = (IP.up ? 1 : 0) - (IP.down ? 1 : 0)
```

If reverse/brake is held (`a < 0`):

```js
if (w > 1.2)
  w -= min(w, 36*t*(-a))
else
  revHold += t
  if (revHold > .15) {
    w -= 15*t*(-a)
    w = max(w, -14)
  } else {
    w *= pow(.02, t)
  }
```

Thus braking removes forward velocity at up to 36 units/s² while moving forward; reverse engages after approximately 0.15 seconds and is capped at -14 longitudinal units/s.

When accelerating (`a > 0`):

```js
if (w < -1)
  w += min(-w, 36*t*a)
else
  w += a * (w < 12 ? 24 : w < 26 ? 15 : 8)
       * (boostT > 0 ? 1.8 : 1) * t
```

The no-throttle drag branch is:

```js
w *= pow(w < 0 ? .3 : .62, t)
```

### Drift and lateral dynamics

Drift/handbrake is active when `IP.drift`, touch drift, or gamepad handbrake is active. It applies longitudinal damping:

```js
w *= pow(abs(w) > 12 ? .75 : .2, t)
```

The steering state is smoothed and then heading changes by:

```js
h += sm*t
     * (drift ? 2.6 : 1.85)
     * min(1, M/7)
     * (w < -.2 ? -1 : 1)
     * (1 - min(.48, M/85))
```

where `M = abs(w)`. Steering is speed-scaled, reverses sign while moving backward, and is reduced at high speed.

Lateral velocity is damped by:

```js
n *= pow(drift ? .35 : M > 28 ? .03 : .004, t)
```

While drifting with meaningful steering, an additional lateral term is applied:

```js
n += -sm*M*.9*t
```

World velocity is reconstructed as:

```js
vx = sinH*w + cosH*n
vz = cosH*w - sinH*n
```

### Speed caps and boost

The ordinary forward cap is:

```js
v = (drift ? 36 : running ? boostInput ? 44 : 35 : 40)
    + (boostT > 0 ? 18 : 0)
```

When a speed power-up timer is active (`boostT > 0`), the cap gains 18 and acceleration receives the 1.8 multiplier above. A held boost input also adds:

```js
if (boostInput && w > 0) w += 8*t
```

The resulting longitudinal speed is clamped to `v`. The final world velocity magnitude is capped at 75:

```js
p = hypot(vx, vz)
if (p > 75) {
  vx *= 75/p
  vz *= 75/p
}
```

A speed power-up sets `boostT = 4.5` seconds. This is distinct from the controller's `keys.boost` input: the input controls the boost behavior, while `boostT` is the temporary power-up timer.

## Boundary and obstacle collision

After velocity integration:

```js
x += vx*t
z += vz*t
```

`Kl(player, 1.8)` clamps the player to the world bounds and resolves cell-interior collisions. If the player hits the outer boundary, the corresponding velocity component is damped. If the player hits an interior cell wall, the nearest edge is selected and the player is moved to it. The update then applies collision response approximately as:

```js
if (normalX) {
  vx *= -.05
  vz *= .92
} else {
  vz *= -.05
  vx *= .92
}
```

When the pre-collision speed exceeds 22, the client emits a rug/collision visual effect. The geometry function is deterministic given the generated map, but object placement is randomized during world creation.

## Police movement and contact

A cop's path update uses a target grid cell and a bounded heading adjustment:

```js
relative = atan2(targetX-copX, targetZ-copZ) - copHeading
relative = atan2(sin(relative), cos(relative))
copHeading += clamp(relative*3, -1, 1) * t * 2.6
```

Cop speed approaches its target using first-order smoothing:

```js
accelTarget = (24 + wantedLevel*2.6)
              * difficulty.copSpd
              * (abs(relative) > 1 ? .55 : 1)
copV += (accelTarget - copV) * t * 1.3
copX += sin(copHeading) * copV * t
copZ += cos(copHeading) * copV * t
```

A cop collision is processed when distance is below approximately 3.9 units and its hit cooldown is clear. Relative-speed damage is:

```js
relativeImpact = hypot(
  player.vx - sin(copHeading)*copV,
  player.vz - cos(copHeading)*copV
)
damage = (6 + relativeImpact*.45) * difficulty.dmg
```

The player receives an impulse away from the cop:

```js
player.vx += (player.x - cop.x)/distance * 6
player.vz += (player.z - cop.z)/distance * 6
copV *= .3
```

The player is considered in the bust proximity zone when an active cop is within 7.5 units. The bust timer grows only when the player's absolute speed is below 5:

```js
if (distance < 7.5) {
  if (abs(player.speed) < 5) bustT += t
  else bustT = max(0, bustT - 2*t)
}
```

The threshold is difficulty-specific: 1.6 seconds in `degen`, 0.9 seconds in `wanted`, and 2.6 seconds in `chill`. This confirms an important controller rule: maintaining speed near a cop materially reduces bust accumulation, while getting pinned near a cop is especially dangerous.

## Pickups and economy

The initial bag is 1,000. A cash pickup is collected below approximately 3.8 units. The exact raw increment is:

```js
combo = comboTimer > 0 ? combo + 1 : 1
comboTimer = 2.5
D = (120 + bag*.06) * min(5, combo)
```

Then power-up and map modifiers apply:

```js
cash power:   D *= 3
magnet power: magT = 7
speed power:  boostT = 4.5
x2 power:     x2T = 8
x2 active:    D *= 2
special zone: D *= 2  // exact `ju()` region predicate
D = round(D)
bag += D
picks += 1
```

Therefore the pickup value is not a fixed token price. It depends on current bag, combo, power-up, x2 state, and a map-region modifier. The token label/color is display metadata and is not itself the raw valuation formula.

A rug collision below approximately 3.4 units removes half the bag:

```js
loss = floor(bag/2)
bag -= loss
```

Pay 'n' Spray can be used below approximately 4.6 units while wanted. It removes:

```js
min(round(bag*.1), 500)
```

and clears wanted level while restoring HP.

Mission completion occurs within approximately 4 units of the marker and awards:

```js
missionReward = round(1500 + bag*.5)
bag += missionReward
```

A mission has 25 seconds before failure.

Cold Stash banking occurs within approximately 5.2 units, when bag > 0 and wanted level is below 3:

```js
banked = round(bag * holderMultiplier)
bank += banked
bag = 0
```

The holder multiplier is 1.0 without the relevant holder tier, or approximately 1.05/1.10/1.15 for available tiers. Banking is therefore the mechanism that protects bag value from busts and rugs.

## Terminal accounting

In normal `degen` and `wanted` modes, `noOver` is false, so busted/wasted transitions terminate the run. In `chill`, the client can continue after a loss.

When the run produces its final summary, the client separates hot bag and bank:

```js
hot = max(0, bag)
bank = max(0, bank)
```

If caught/wasted without leverage, the final total is bank plus the rebate. The seized bag and rebate are calculated approximately as:

```js
lostBag = hot
rebate = round(lostBag * holderRebateRate)
total = bank + rebate
```

The holder rebate rate is 0.10, 0.20, or 0.30 depending on the available holder tier. If the player survives normally, total is `hot + bank`. With leverage, the total is approximately 0.7x when caught or 1.5x when surviving the leveraged extension.

This confirms that raw `bag`, `bank`, and final official total must be reported as separate values.

## Randomness and reproducibility

The client uses ordinary `Math.random()` during object generation and gameplay effects. It also has a local seeded/random helper used by map/path generation. The public client does not expose a server-provided deterministic world seed in the observed start flow. A deterministic local browser harness is possible only when the same page state and random source are controlled; a separate clean-room replay cannot be assumed to match a future live run.

## Campaign wrapper conclusion

`campaign.js` is not the source of vehicle physics. Its role is account/profile/campaign integration and API-facing UI. The physics formulas above come from the pinned inline engine in `game.html`. Step 2 is complete for the formulas statically identifiable from the public client. Collision geometry placement, power-up configuration values in `window.CFG`, and the exact `ju()` special-region predicate remain items for browser instrumentation in Step 3.
