"""Standard ROS2 topic bridge — publishes alongside the Unitree DDS bridge.

Where `dds_bridge.py` speaks the Unitree `rt/lowstate` / `rt/api/sport/*`
vocabulary (needed so neon-runtime thinks it's talking to real hardware),
this bridge publishes the **standard ROS2 topics** every ROS2 tool in the
ecosystem expects:

    /joint_states   (sensor_msgs/JointState)   @ 50 Hz
    /odom           (nav_msgs/Odometry)        @ 50 Hz
    /tf             (tf2_msgs/TFMessage)       @ 50 Hz
    /imu            (sensor_msgs/Imu)          @ 100 Hz

Now any ROS2 consumer — rviz2, rqt, your `use_ros` tool on another
machine, Foxglove Studio — can discover and subscribe to the sim over
DDS multicast. No rclpy needed on either side: we speak raw CycloneDDS
with the IDL types bundled in devduck.tools._ros_msgs.

Usage (inside stage.py):
    from neon_sim.bridge.ros2_bridge import ROS2Bridge
    ros2 = ROS2Bridge(model, data, joint_names=[...])
    ros2.start()
    # ... per sim step:
    ros2.tick()
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

log = logging.getLogger(__name__)

# Topic name mapping: ROS2 `/joint_states` → DDS `rt/joint_states`
# (ROS2 always prefixes user topics with `rt/` on the wire.)
def _ros_to_dds_topic(name: str) -> str:
    n = name.lstrip("/")
    return f"rt/{n}"


class ROS2Bridge:
    """Publish sim state as standard ROS2 topics via raw CycloneDDS."""

    JOINT_STATE_HZ = 50.0
    ODOM_HZ = 50.0
    TF_HZ = 50.0
    IMU_HZ = 100.0

    def __init__(
        self,
        model,
        data,
        joint_names: Optional[List[str]] = None,
        base_frame: str = "base_link",
        odom_frame: str = "odom",
        imu_frame: str = "imu_link",
    ):
        self.model = model
        self.data = data
        self.base_frame = base_frame
        self.odom_frame = odom_frame
        self.imu_frame = imu_frame

        # Auto-extract joint names from MJCF if not provided
        if joint_names is None:
            import mujoco
            names = []
            for i in range(model.njnt):
                # Skip the free joint (type 0) at index 0
                if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE:
                    continue
                name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i)
                if name:
                    names.append(name)
            joint_names = names
        self.joint_names = joint_names
        log.info(f"[ros2_bridge] {len(joint_names)} joints: {joint_names[:5]}...")

        self._writers = {}
        self._last = {"joint": 0.0, "odom": 0.0, "tf": 0.0, "imu": 0.0}
        self._started = False

    def start(self):
        """Create DDS writers for each topic."""
        try:
            from devduck.tools.dds_peer import DDS_STATE, _STATE_LOCK, _start as dds_start
            from devduck.tools import _ros_msgs
            from cyclonedds.pub import Publisher, DataWriter
            from cyclonedds.topic import Topic
        except ImportError as e:
            log.warning(f"[ros2_bridge] dependencies missing: {e}")
            return

        # Ensure the shared DDS participant is up
        dds_start()
        with _STATE_LOCK:
            participant = DDS_STATE["participant"]
        if participant is None:
            log.warning("[ros2_bridge] no DDS participant — bridge disabled")
            return

        publisher = Publisher(participant)

        def mk_writer(ros_topic: str, idl_cls):
            dds_name = _ros_to_dds_topic(ros_topic)
            topic = Topic(participant, dds_name, idl_cls)
            self._writers[ros_topic] = {
                "writer": DataWriter(publisher, topic),
                "cls": idl_cls,
                "topic": topic,
            }
            log.info(f"[ros2_bridge]   publisher  {ros_topic}  ({dds_name})")

        mk_writer("/joint_states", _ros_msgs.JointState)
        mk_writer("/odom", _ros_msgs.Odometry)
        mk_writer("/tf", _ros_msgs.TFMessage)
        mk_writer("/imu", _ros_msgs.Imu)

        self._started = True
        log.info("[ros2_bridge] ✓ publishing on /joint_states /odom /tf /imu")

    def tick(self):
        """Call every sim step — rate-limits internally."""
        if not self._started:
            return
        now = time.time()
        if now - self._last["joint"] >= 1.0 / self.JOINT_STATE_HZ:
            self._pub_joint_states(now)
            self._last["joint"] = now
        if now - self._last["odom"] >= 1.0 / self.ODOM_HZ:
            self._pub_odom(now)
            self._last["odom"] = now
        if now - self._last["tf"] >= 1.0 / self.TF_HZ:
            self._pub_tf(now)
            self._last["tf"] = now
        if now - self._last["imu"] >= 1.0 / self.IMU_HZ:
            self._pub_imu(now)
            self._last["imu"] = now

    # ── helpers ──────────────────────────────────────────────────────
    def _header(self, frame: str, now: float):
        from devduck.tools._ros_msgs import Header, Time
        sec = int(now)
        nanosec = int((now - sec) * 1e9)
        return Header(stamp=Time(sec=sec, nanosec=nanosec), frame_id=frame)

    def _pub_joint_states(self, now: float):
        from devduck.tools._ros_msgs import JointState
        data = self.data
        model = self.model
        # skip 7-dof free base
        pos = [float(data.qpos[7 + i]) for i in range(len(self.joint_names))
               if 7 + i < model.nq]
        vel = [float(data.qvel[6 + i]) for i in range(len(self.joint_names))
               if 6 + i < model.nv]
        msg = JointState(
            header=self._header("base_link", now),
            name=list(self.joint_names[:len(pos)]),
            position=pos,
            velocity=vel,
            effort=[],
        )
        self._writers["/joint_states"]["writer"].write(msg)

    def _pub_odom(self, now: float):
        from devduck.tools._ros_msgs import (
            Odometry, Pose, PoseWithCovariance, Twist, TwistWithCovariance,
            Point, Quaternion, Vector3,
        )
        d = self.data
        pose = Pose(
            position=Point(x=float(d.qpos[0]), y=float(d.qpos[1]), z=float(d.qpos[2])),
            orientation=Quaternion(
                w=float(d.qpos[3]), x=float(d.qpos[4]),
                y=float(d.qpos[5]), z=float(d.qpos[6]),
            ),
        )
        lin = Vector3(x=float(d.qvel[0]), y=float(d.qvel[1]), z=float(d.qvel[2]))
        ang = Vector3(x=float(d.qvel[3]), y=float(d.qvel[4]), z=float(d.qvel[5]))
        msg = Odometry(
            header=self._header(self.odom_frame, now),
            child_frame_id=self.base_frame,
            pose=PoseWithCovariance(pose=pose, covariance=[0.0] * 36),
            twist=TwistWithCovariance(
                twist=Twist(linear=lin, angular=ang),
                covariance=[0.0] * 36,
            ),
        )
        self._writers["/odom"]["writer"].write(msg)

    def _pub_tf(self, now: float):
        from devduck.tools._ros_msgs import (
            TFMessage, TransformStamped, Transform, Vector3, Quaternion,
        )
        d = self.data
        tf = TransformStamped(
            header=self._header(self.odom_frame, now),
            child_frame_id=self.base_frame,
            transform=Transform(
                translation=Vector3(
                    x=float(d.qpos[0]), y=float(d.qpos[1]), z=float(d.qpos[2]),
                ),
                rotation=Quaternion(
                    w=float(d.qpos[3]), x=float(d.qpos[4]),
                    y=float(d.qpos[5]), z=float(d.qpos[6]),
                ),
            ),
        )
        msg = TFMessage(transforms=[tf])
        self._writers["/tf"]["writer"].write(msg)

    def _pub_imu(self, now: float):
        from devduck.tools._ros_msgs import Imu, Quaternion, Vector3
        d = self.data
        # MuJoCo doesn't expose IMU directly without a sensor — derive from base
        msg = Imu(
            header=self._header(self.imu_frame, now),
            orientation=Quaternion(
                w=float(d.qpos[3]), x=float(d.qpos[4]),
                y=float(d.qpos[5]), z=float(d.qpos[6]),
            ),
            orientation_covariance=[0.0] * 9,
            angular_velocity=Vector3(
                x=float(d.qvel[3]), y=float(d.qvel[4]), z=float(d.qvel[5]),
            ),
            angular_velocity_covariance=[0.0] * 9,
            linear_acceleration=Vector3(
                x=float(d.qacc[0]) if len(d.qacc) > 0 else 0.0,
                y=float(d.qacc[1]) if len(d.qacc) > 1 else 0.0,
                z=float(d.qacc[2]) if len(d.qacc) > 2 else 0.0,
            ),
            linear_acceleration_covariance=[0.0] * 9,
        )
        self._writers["/imu"]["writer"].write(msg)

    def stop(self):
        self._writers.clear()
        self._started = False
