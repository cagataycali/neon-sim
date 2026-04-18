"""DDS bridge: Isaac Sim ↔ neon-runtime.

Publishes to the exact DDS topics neon-runtime subscribes to, and
subscribes to the RPC topics neon-runtime publishes to.

This means from neon-runtime's perspective, it's talking to a real G1.

Topics (all in `unitree_hg` IDL namespace for G1 HG variants):

Published by this bridge → consumed by neon-runtime:
  rt/lowstate       (LowState_)    @ 500 Hz — joint state + IMU
  rt/bmsstate       (BmsState_)    @ 1 Hz   — battery state (constant in sim)

Consumed by this bridge ← published by neon-runtime:
  rt/api/sport/request   (Request_)        — LocoClient commands
  rt/api/arm/request     (Request_)        — G1ArmActionClient
  rt/api/voice/request   (Request_)        — AudioClient (LEDs, TTS)
  rt/api/motion_switcher/request (Request_)— mode switcher

This bridge translates those RPC requests into Isaac Sim articulation
commands (low-level joint targets).
"""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    from unitree_sdk2py.core.channel import (
        ChannelPublisher,
        ChannelSubscriber,
        ChannelFactoryInitialize,
    )
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import (
        LowState_,
        LowCmd_,
        BmsState_,
    )
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Request_, Response_
    from unitree_sdk2py.idl.default import (
        unitree_hg_msg_dds__LowState_,
        unitree_hg_msg_dds__BmsState_,
        unitree_api_msg_dds__Response_,
    )
except ImportError as e:
    log.warning(f"unitree_sdk2py not available: {e}")
    log.warning("Bridge will run in stub mode (no real DDS)")
    LowState_ = LowCmd_ = BmsState_ = Request_ = Response_ = None


# LocoClient FSM IDs (from unitree_sdk2py/g1/loco/g1_loco_client.py)
FSM_ZERO_TORQUE = 0
FSM_DAMP = 1
FSM_SIT = 3
FSM_START = 200
FSM_LIE_TO_STAND = 702
FSM_SQUAT_TO_STAND = 706
FSM_STANDUP_TO_SQUAT = 706  # same ID, context-dependent

# LocoClient API IDs (from unitree_sdk2py/g1/loco/g1_loco_api.py)
LOCO_API_SET_FSM_ID = 7101
LOCO_API_SET_VELOCITY = 7103
LOCO_API_SET_STAND_HEIGHT = 7102


@dataclass
class BridgeState:
    """Runtime state for the bridge."""
    network_interface: str = "lo"
    domain_id: int = 0
    running: bool = False
    # Counters for monitoring
    lowstate_msgs_sent: int = 0
    loco_requests_handled: int = 0
    last_fsm_id: int = FSM_START
    last_velocity: tuple = (0.0, 0.0, 0.0)  # (vx, vy, vyaw)


class DDSBridge:
    """Translates Isaac Sim state to DDS, and DDS commands to Isaac Sim.

    Usage (inside Isaac Sim):
        bridge = DDSBridge(world=world, robot=g1_articulation)
        bridge.start()
        while kit.is_running():
            world.step(render=True)
            bridge.tick()  # publishes lowstate + handles requests
        bridge.stop()
    """

    def __init__(
        self,
        world: Any,
        robot: Any,
        network_interface: str = "lo",
        domain_id: int = 0,
    ):
        self.world = world
        self.robot = robot
        self.state = BridgeState(network_interface=network_interface, domain_id=domain_id)

        # Publishers
        self.lowstate_pub: Optional[ChannelPublisher] = None
        self.bmsstate_pub: Optional[ChannelPublisher] = None

        # Subscribers
        self.sport_sub: Optional[ChannelSubscriber] = None

        # Rate control
        self._last_lowstate_time = 0.0
        self._last_bmsstate_time = 0.0
        self.lowstate_period = 1.0 / 500  # 500 Hz
        self.bmsstate_period = 1.0        # 1 Hz

        # Command state
        self._cmd_lock = threading.Lock()
        self._pending_fsm: Optional[int] = None
        self._pending_velocity: Optional[tuple] = None

    def start(self):
        if ChannelFactoryInitialize is None:
            log.warning("DDS not available — running without bridge")
            return

        log.info(f"🌉 Initializing DDS on interface {self.state.network_interface}")
        ChannelFactoryInitialize(self.state.domain_id, self.state.network_interface)

        # Publishers
        self.lowstate_pub = ChannelPublisher("rt/lowstate", LowState_)
        self.lowstate_pub.Init()

        self.bmsstate_pub = ChannelPublisher("rt/bmsstate", BmsState_)
        self.bmsstate_pub.Init()

        # Subscribers
        self.sport_sub = ChannelSubscriber("rt/api/sport/request", Request_)
        self.sport_sub.Init(self._on_sport_request, queueLen=10)

        self.state.running = True
        log.info("✅ DDS bridge started")

    def stop(self):
        self.state.running = False
        if self.lowstate_pub:
            self.lowstate_pub.Close()
        if self.bmsstate_pub:
            self.bmsstate_pub.Close()
        if self.sport_sub:
            self.sport_sub.Close()
        log.info("🛑 DDS bridge stopped")

    # ------------------------------------------------------------------
    # Publish side: sim → DDS
    # ------------------------------------------------------------------

    def tick(self):
        """Call once per sim step — publishes state at the right rate.

        Also applies any pending commands from the last request.
        """
        if not self.state.running:
            return

        now = time.time()

        # Publish lowstate at 500 Hz
        if now - self._last_lowstate_time >= self.lowstate_period:
            self._publish_lowstate()
            self._last_lowstate_time = now

        # Publish bmsstate at 1 Hz
        if now - self._last_bmsstate_time >= self.bmsstate_period:
            self._publish_bmsstate()
            self._last_bmsstate_time = now

        # Apply pending commands
        self._apply_commands()

    def _publish_lowstate(self):
        """Build a LowState_ message from Isaac Sim articulation state."""
        if LowState_ is None:
            return

        msg = unitree_hg_msg_dds__LowState_()

        # Fill motor_state from robot joint state
        try:
            joint_positions = self.robot.get_joint_positions()
            joint_velocities = self.robot.get_joint_velocities()
            # G1 has 29 motor slots (even if only 23 active); fill what we can
            for i in range(min(len(joint_positions), 29)):
                msg.motor_state[i].q = float(joint_positions[i])
                msg.motor_state[i].dq = float(joint_velocities[i])
                msg.motor_state[i].mode = 0x01  # healthy
                msg.motor_state[i].temperature[0] = 35  # fake temp
                msg.motor_state[i].vol = 48.0
        except Exception as e:
            log.debug(f"Could not read joint state: {e}")

        # IMU
        try:
            orient = self.robot.get_world_pose()  # may differ per API
            # TODO: fill msg.imu_state.quaternion / gyroscope / accelerometer
        except Exception:
            pass

        # FSM state
        msg.mode_machine = 1  # Standard variant (29-DoF locked waist)
        # We don't have a direct mapping to LowState fsm_id, but neon-runtime
        # reads it from request/response cycles, so this is ok.

        self.lowstate_pub.Write(msg)
        self.state.lowstate_msgs_sent += 1

    def _publish_bmsstate(self):
        """Publish fake battery state (always at 85%)."""
        if BmsState_ is None:
            return
        msg = unitree_hg_msg_dds__BmsState_()
        msg.soc = 85  # 85% state of charge
        msg.current = 0
        msg.cycle = 100
        msg.bq_ntc[0] = 30  # battery temp
        msg.bq_ntc[1] = 30
        self.bmsstate_pub.Write(msg)

    # ------------------------------------------------------------------
    # Receive side: DDS → sim
    # ------------------------------------------------------------------

    def _on_sport_request(self, msg: Request_):
        """Handle a LocoClient RPC request from neon-runtime."""
        api_id = msg.header.identity.api_id
        log.info(f"📨 LocoClient request: api_id={api_id}")

        with self._cmd_lock:
            if api_id == LOCO_API_SET_FSM_ID:
                # Parse FSM id from parameter JSON
                # Parameter format: {"data": <int>}
                import json
                try:
                    params = json.loads(msg.parameter)
                    self._pending_fsm = int(params.get("data", 0))
                    log.info(f"  → FSM {self._pending_fsm}")
                except Exception as e:
                    log.warning(f"Could not parse FSM request: {e}")

            elif api_id == LOCO_API_SET_VELOCITY:
                # Parameter: {"x": vx, "y": vy, "z": vyaw}
                import json
                try:
                    params = json.loads(msg.parameter)
                    self._pending_velocity = (
                        float(params.get("x", 0)),
                        float(params.get("y", 0)),
                        float(params.get("z", 0)),
                    )
                    log.info(f"  → Velocity {self._pending_velocity}")
                except Exception as e:
                    log.warning(f"Could not parse velocity: {e}")

            self.state.loco_requests_handled += 1

    def _apply_commands(self):
        """Apply pending commands to the Isaac Sim articulation."""
        with self._cmd_lock:
            fsm = self._pending_fsm
            vel = self._pending_velocity
            self._pending_fsm = None
            self._pending_velocity = None

        if fsm is not None:
            self._apply_fsm(fsm)
        if vel is not None:
            self._apply_velocity(*vel)

    def _apply_fsm(self, fsm_id: int):
        """Drive the articulation to a pose that matches the FSM target.

        This is the hard part — Isaac's physics needs a joint trajectory,
        but LocoClient is a black box that abstracts that away. For MVP,
        we'll just snap to pre-authored poses and let physics sort it out.
        """
        self.state.last_fsm_id = fsm_id

        # TODO: Load pre-authored joint targets for each FSM state
        # For now, just log
        poses = {
            FSM_ZERO_TORQUE: "limp",
            FSM_DAMP: "damp (falls)",
            FSM_SIT: "sit",
            FSM_START: "idle stand",
            FSM_LIE_TO_STAND: "lie→stand",
            FSM_SQUAT_TO_STAND: "squat↔stand",
        }
        pose_name = poses.get(fsm_id, f"unknown FSM {fsm_id}")
        log.info(f"🤸 FSM transition → {pose_name}")

    def _apply_velocity(self, vx: float, vy: float, vyaw: float):
        """Drive the base at a given velocity.

        In real G1, sport_mode handles all the bipedal locomotion. In sim,
        we cheat for MVP: directly set the base velocity and let physics
        figure out feet. A real implementation would use a learned policy
        or Unitree's controller.
        """
        self.state.last_velocity = (vx, vy, vyaw)
        log.info(f"🏃 Set velocity: vx={vx:.2f} vy={vy:.2f} vyaw={vyaw:.2f}")

        # TODO: Plug into Isaac's articulation controller
