"""
Profile Builder - Waveform profile builder for Raspberry Pi Pico testing.

Main exports:
    - ProfileBuilderApp: Main GUI application class
    - Profile, Block, ScheduledEvent, PositionConfig: Data models
    - PicoLink: Serial communication with Pico hardware
"""

__version__ = "2.0.0"

from pc_app.models import Profile, Block, ScheduledEvent, PositionConfig, EVENTS, UNIT_TO_MS
from pc_app.waveform_profile_builder import ProfileBuilderApp
from pc_app.pico_serial import PicoLink

__all__ = [
    "ProfileBuilderApp",
    "Profile",
    "Block", 
    "ScheduledEvent",
    "PositionConfig",
    "PicoLink",
    "EVENTS",
    "UNIT_TO_MS",
]
