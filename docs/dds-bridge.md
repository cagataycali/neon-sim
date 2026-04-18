# DDS Bridge

The bridge lives in `neon_sim/bridge/dds_bridge.py` and is shared between
Isaac and MuJoCo backends.

## Topics

| Topic | Schema | Direction | Rate |
|---|---|---|---|
| `rt/lowstate` | `unitree_hg.LowState_` | sim→neon | 500 Hz |
| `rt/bmsstate` | `unitree_hg.BmsState_` | sim→neon | 1 Hz |
| `rt/api/sport/request` | `unitree_api.Request_` | neon→sim | event |
| `rt/api/sport/response` | `unitree_api.Response_` | sim→neon | reply |
| `rt/api/arm/request` | `unitree_api.Request_` | neon→sim | event |
| `rt/api/voice/request` | `unitree_api.Request_` | neon→sim | event |

The bridge currently implements `rt/lowstate`, `rt/bmsstate`, and
`rt/api/sport/request`. Arm and voice RPCs are TODO.

## LocoClient request translation

When neon-runtime calls `g1_walk_forward(0.5, 0.3)`, under the hood it:

1. Calls `LocoClient.Move(0.3, 0, 0)` at 20 Hz for some duration
2. `Move()` sets api_id=7103 with `{"x": 0.3, "y": 0, "z": 0}` as JSON
3. Publishes to `rt/api/sport/request`

The bridge:

1. Receives the `Request_`
2. Parses api_id + JSON parameter
3. Calls `_apply_velocity(0.3, 0, 0)` which sets the articulation's
   base velocity target

```python
LOCO_API_SET_FSM_ID    = 7101  # Damp, StandUp, Sit, etc.
LOCO_API_SET_STAND_HEIGHT = 7102  # HighStand, LowStand
LOCO_API_SET_VELOCITY  = 7103  # Move
```

## FSM translation

LocoClient commands are "black-box" intents — the real sport_mode runs a
complex policy internally to execute them. In sim, we approximate:

| FSM ID | Name | Sim action |
|---|---|---|
| 0 | ZeroTorque | Release all joint actuators |
| 1 | Damp | Soft joint hold (robot falls slowly) |
| 3 | Sit | Interpolate to pre-authored sit pose |
| 200 | Start | Stand idle |
| 702 | Lie2StandUp | Play lie→stand animation |
| 706 | Squat2StandUp / StandUp2Squat | Play squat↔stand animation |

For MVP, transitions are instantaneous (snap to target pose). A v2 would
add joint-space trajectory interpolation or use a learned policy.

## Articulation limitation

Real G1's sport_mode is a **full bipedal controller** — balance, foot
placement, CoM tracking, the works. Our bridge doesn't reimplement that;
it uses Isaac Sim or MuJoCo's built-in physics and cheats where needed
(e.g., direct base velocity for `Move()`).

This means:

- ✅ Can test high-level agent logic (when to arm, when to stop, safety gates)
- ⚠️ Motor-dynamics-level testing requires hardware or a learned sim policy

Future work: integrate [unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym)
policies for realistic walking.
