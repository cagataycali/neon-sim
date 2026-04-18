#!/usr/bin/env python3
"""Send a sequence of LocoClient commands. Meant to prove the Sim's
Sport Server receives them end-to-end.

Run on Thor (or any host with DDS access to Isaac Sim):
    CYCLONEDDS_HOME=/usr/local python3 scripts/dds_smoketest.py
"""
import os
import sys
import time

# Default to loopback — change via G1_NETWORK_INTERFACE
iface = os.getenv("G1_NETWORK_INTERFACE", "lo")

try:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
except ImportError:
    print("unitree_sdk2py not found — install from ~/unitree_sdk2_python")
    sys.exit(1)

print(f"[dds] Init on iface={iface}")
ChannelFactoryInitialize(0, iface)

cli = LocoClient()
cli.SetTimeout(2.0)
cli.Init()
print("[dds] LocoClient connected")

print("[dds] Move(0.3, 0, 0)  — walk forward 1s")
cli.Move(0.3, 0.0, 0.0)
time.sleep(1.5)

print("[dds] Move(0, 0, 0.5) — turn left 1s")
cli.Move(0.0, 0.0, 0.5)
time.sleep(1.5)

print("[dds] StopMove()")
cli.StopMove()
time.sleep(0.5)

print("[dds] HighStand()")
cli.HighStand()
time.sleep(0.5)

print("[dds] done.")
