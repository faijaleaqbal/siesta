"""Nap policy — when is it rude to wake the agent up?

Sloths conserve energy. So does Siesta.

Two policies, both conservative and both optional:

* **Idle gate** — only wake up once the human has been away for a while.
  That is what makes the "runs while you sleep" mode possible on a shared
  machine: if you are actively using the laptop, Siesta stays quiet.
* **Energy gate** — while on battery or on a metered connection, Siesta
  defers. Local inference is free but it is not free in watts, and hammering
  the CPU at 3% battery is rude.

Everything degrades gracefully: on platforms where we cannot read the idle
time, Siesta simply does not use that gate.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass

log = logging.getLogger("siesta.energy")


@dataclass
class NapDecision:
    should_run: bool
    reason: str
    idle_seconds: int | None = None
    on_battery: bool = False


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def _windows_idle_seconds() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount()
        return int(tick - info.dwTime)
    except Exception:  # pragma: no cover - platform specific
        return None


def _windows_on_battery() -> bool:
    try:
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return False
        # 1 = on battery, 255 = unknown
        return status.ACLineStatus == 1
    except Exception:  # pragma: no cover - platform specific
        return False


# --------------------------------------------------------------------------- #
# macOS
# --------------------------------------------------------------------------- #
def _macos_idle_seconds() -> int | None:
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get idle time'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return None
        return int(float(out.stdout.strip()))
    except Exception:  # pragma: no cover - platform specific
        return None


def _macos_on_battery() -> bool:
    try:
        out = subprocess.run(
            ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5
        )
        return "Battery Power" in out.stdout
    except Exception:  # pragma: no cover - platform specific
        return False


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def idle_seconds() -> int | None:
    """Seconds since the last human input, or None if we cannot tell."""
    system = platform.system()
    if system == "Windows":
        return _windows_idle_seconds()
    if system == "Darwin":
        return _macos_idle_seconds()
    return None


def on_battery() -> bool:
    system = platform.system()
    if system == "Windows":
        return _windows_on_battery()
    if system == "Darwin":
        return _macos_on_battery()
    try:
        with open("/sys/class/power_supply/BAT0/status", "r", encoding="utf-8") as fh:
            return fh.read().strip() == "Discharging"
    except Exception:
        return False


def nap_decision(config, force: bool = False) -> NapDecision:
    """Decide whether this is a good moment to do work."""
    if force:
        return NapDecision(True, "forced")

    idle = idle_seconds()
    if config.energy_aware and on_battery():
        return NapDecision(False, "on battery — staying quiet to save power", idle, True)

    if config.idle_seconds and idle is not None and idle < config.idle_seconds:
        remaining = config.idle_seconds - idle
        return NapDecision(
            False,
            f"you have been active for the last {remaining // 60} min — waking up later",
            idle,
        )

    return NapDecision(True, "ok", idle)
