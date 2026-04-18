"""Isaac Sim ↔ DDS Sport Server.

Subscribes to `rt/api/sport/request` (what LocoClient.Move/SetVelocity/...
publish) and acks on `rt/api/sport/response`. Neon-runtime can't tell
whether it's talking to the real G1 or this sim endpoint.

API IDs we handle (from unitree_sdk2py.g1.loco.g1_loco_api):
  7101  SetFsmId        (posture state: 3=sit 200=stand 702=lie→stand 706=squat↔stand)
  7102  SetBalanceMode
  7104  SetStandHeight  (UINT32_MAX=high, 0=low)
  7105  SetVelocity     (vx, vy, omega, duration)
  7106  SetTaskId       (arm gestures)

SetVelocity parameter JSON (validated against real SDK):
  {"velocity": [vx, vy, omega], "duration": <s>}
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict

try:
    from unitree_sdk2py.core.channel import (
        ChannelFactoryInitialize, ChannelSubscriber, ChannelPublisher,
    )
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Request_ as DDSRequest
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Response_ as DDSResponse
    from unitree_sdk2py.g1.loco.g1_loco_api import (
        ROBOT_API_ID_LOCO_SET_FSM_ID,
        ROBOT_API_ID_LOCO_SET_VELOCITY,
        ROBOT_API_ID_LOCO_SET_STAND_HEIGHT,
        ROBOT_API_ID_LOCO_SET_BALANCE_MODE,
        ROBOT_API_ID_LOCO_SET_ARM_TASK,
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


class SportServer:
    """Thread-safe command state container with DDS wiring."""

    def __init__(self, dds_iface: str = "lo", domain_id: int = 0):
        self.state: Dict[str, Any] = {
            "vx": 0.0, "vy": 0.0, "vyaw": 0.0,
            "vel_until": 0.0,
            "fsm_id": 200,       # 200 = Start (standing)
            "stand_height_m": 0.75,
            "task_id": -1,
            "req_count": 0,
            "last_api_id": None,
        }
        self.lock = threading.Lock()
        self.dds_iface = dds_iface
        self.domain_id = domain_id
        self._pub = None
        self._sub = None

    def start(self) -> bool:
        if not SDK_AVAILABLE:
            return False
        ChannelFactoryInitialize(self.domain_id, self.dds_iface)
        self._sub = ChannelSubscriber("rt/api/sport/request", DDSRequest)
        self._sub.Init(self._handle, 10)
        self._pub = ChannelPublisher("rt/api/sport/response", DDSResponse)
        self._pub.Init()
        return True

    # ---- Public getters (the render loop reads these) -------------
    def current_velocity(self) -> tuple[float, float, float]:
        """Return (vx, vy, vyaw) after applying duration expiry."""
        with self.lock:
            if time.time() > self.state["vel_until"]:
                return (0.0, 0.0, 0.0)
            return (self.state["vx"], self.state["vy"], self.state["vyaw"])

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.state)

    # ---- DDS handler ----------------------------------------------
    def _handle(self, req) -> None:
        try:
            api_id = req.header.identity.api_id
            params_str = req.parameter

            with self.lock:
                self.state["req_count"] += 1
                self.state["last_api_id"] = api_id

                p = json.loads(params_str) if params_str else {}

                if api_id == ROBOT_API_ID_LOCO_SET_VELOCITY:  # 7105
                    vel = p.get("velocity", [0.0, 0.0, 0.0])
                    self.state["vx"] = float(vel[0])
                    self.state["vy"] = float(vel[1])
                    self.state["vyaw"] = float(vel[2])
                    duration = float(p.get("duration", 1.0))
                    self.state["vel_until"] = time.time() + duration

                elif api_id == ROBOT_API_ID_LOCO_SET_FSM_ID:  # 7101
                    self.state["fsm_id"] = int(p.get("data", 200))
                    self.state["vx"] = self.state["vy"] = self.state["vyaw"] = 0.0

                elif api_id == ROBOT_API_ID_LOCO_SET_STAND_HEIGHT:  # 7104
                    raw = float(p.get("data", 0))
                    self.state["stand_height_m"] = 0.85 if raw > 1_000_000 else 0.65

                elif api_id == ROBOT_API_ID_LOCO_SET_ARM_TASK:  # 7106
                    self.state["task_id"] = int(p.get("data", -1))

            # Ack so LocoClient._Call() returns promptly (avoids 2s timeout)
            resp = DDSResponse()
            resp.header.identity.id = req.header.identity.id
            resp.header.identity.api_id = api_id
            resp.header.status.code = 0
            resp.data = ""
            if self._pub:
                self._pub.Write(resp)
        except Exception as e:
            print(f"[sport-server] handler error: {type(e).__name__}: {e}")
