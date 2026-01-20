"""
Data Models Module
==================
This module contains all data structures used throughout the Profile Builder application.

Classes:
    - PositionConfig: Configuration for a single test position
    - ScheduledEvent: A single waveform event in the timeline
    - Profile: Complete profile including all waveforms, events, and positions

Constants:
    - UNIT_TO_MS: Time unit conversion factors
    - EVENTS: List of all available waveform event types
    - Event classification sets for waveform generation
"""

from dataclasses import dataclass, asdict
from typing import List, Tuple


# ----------------------------
# Time Unit Conversions
# ----------------------------
# Conversion factors from various time units to milliseconds
# Used for converting user-specified time values to the internal millisecond representation
UNIT_TO_MS = {
    "ms": 1.0,        # Milliseconds (no conversion needed)
    "sec": 1000.0,    # Seconds to milliseconds
    "min": 60_000.0,  # Minutes to milliseconds
}


# ----------------------------
# Event Type Definitions
# ----------------------------
# All possible waveform event types that can be scheduled
# These events define the timing and behavior of isolator and DUT signals
EVENTS = [
    "Isolator On",         # Steady-state isolator HIGH period
    "Isolator Rise Time",  # Isolator transition from LOW to HIGH (displayed as ramp)
    "Isolator Fall Time",  # Isolator transition from HIGH to LOW (displayed as ramp)
    "DUT Hold Time",       # Steady-state DUT HIGH period
    "DUT Rise Time",       # DUT transition from LOW to HIGH (displayed as ramp)
    "DUT Fall Time",       # DUT transition from HIGH to LOW (displayed as ramp)
    "Isolator Off Time",   # Steady-state isolator LOW period
    "DUT Off Time",        # Steady-state DUT LOW period
    "Cycle Delay",         # Delay between cycles (isolator and DUT both LOW)
]


# ----------------------------
# Event Classification Sets
# ----------------------------
# These sets classify events by their function in waveform generation
# Used to determine signal states at any given time in the waveform

# Isolator signal is HIGH (steady state) during these events
ISO_ON_STEADY = {"Isolator On"}

# Isolator signal is LOW (steady state) during these events
ISO_OFF_STEADY = {"Isolator Off Time", "Cycle Delay"}

# DUT signal is HIGH (steady state) during these events
DUT_ON_STEADY = {"DUT Hold Time"}

# DUT signal is LOW (steady state) during these events
DUT_OFF_STEADY = {"DUT Off Time", "Cycle Delay"}

# Isolator transitions from LOW to HIGH (for display visualization only)
ISO_RISE = {"Isolator Rise Time"}

# Isolator transitions from HIGH to LOW (for display visualization only)
ISO_FALL = {"Isolator Fall Time"}

# DUT transitions from LOW to HIGH (for display visualization only)
DUT_RISE = {"DUT Rise Time"}

# DUT transitions from HIGH to LOW (for display visualization only)
DUT_FALL = {"DUT Fall Time"}


# ----------------------------
# Data Classes
# ----------------------------

@dataclass
class PositionConfig:
    """
    Configuration for a single test position.
    
    A position represents one physical location in the test setup where
    both an isolator and a DUT (Device Under Test) can be controlled.
    
    Attributes:
        position (int): Position number (1-indexed for display)
        enabled (bool): Whether this position is active in the test
        isolator_gpio (int): GPIO pin number controlling the isolator for this position
        dut_gpio (int): GPIO pin number controlling the DUT for this position
        dut_offset_ms (float): Time offset in milliseconds for the DUT waveform
                               relative to the isolator waveform (allows phase shifting)
    
    Example:
        >>> pos = PositionConfig(position=1, enabled=True, isolator_gpio=1, 
        ...                      dut_gpio=21, dut_offset_ms=10.0)
    """
    position: int
    enabled: bool
    isolator_gpio: int
    dut_gpio: int
    dut_offset_ms: float = 0.0  # Default: no offset


@dataclass
class ScheduledEvent:
    """
    A single scheduled event in the waveform timeline.
    
    Events define time blocks where specific signal behaviors occur.
    Multiple events can be scheduled and may overlap, with the most
    recent event taking precedence at any given time.
    
    Attributes:
        event (str): Event type (must be one of EVENTS list)
        start (float): Start time of the event (in user-specified units)
        duration (float): Duration of the event (in user-specified units)
    
    Example:
        >>> event = ScheduledEvent(event="Isolator On", start=0.0, duration=100.0)
    """
    event: str
    start: float
    duration: float


@dataclass
class Block:
    """
    A waveform block representing a complete waveform definition with independent cycles.
    
    Blocks are the fundamental building units of a test sequence. Each block contains
    its own waveform definition (scheduled events) and runs for a specified number
    of cycles before moving to the next block.
    
    Blocks enable:
        - Initialization sequences (run once at start)
        - Main test patterns (run multiple times)
        - Conditional or alternate behaviors
        - Shutdown sequences (run once at end)
    
    There is no functional difference between blocks - they are all executed
    identically in the order they appear in the block list.
    
    Attributes:
        block_name (str): Human-readable name for this block (e.g., "Initialization", "Main Test")
        scheduled_events (List[ScheduledEvent]): List of waveform events defining this block's behavior
        cycles (int): Number of times to repeat this block's waveform (must be >= 1)
    
    Example:
        >>> init_block = Block(
        ...     block_name="Initialization",
        ...     scheduled_events=[
        ...         ScheduledEvent("Isolator On", 0.0, 100.0),
        ...         ScheduledEvent("DUT Hold Time", 20.0, 60.0)
        ...     ],
        ...     cycles=1  # Run once at start
        ... )
        >>> main_block = Block(
        ...     block_name="Main Test",
        ...     scheduled_events=[...],
        ...     cycles=100  # Repeat 100 times
        ... )
    """
    block_name: str
    scheduled_events: List[ScheduledEvent]
    cycles: int


@dataclass
class AuxiliaryOutput:
    """
    Configuration for an auxiliary GPIO output.
    
    Auxiliary outputs are user-defined GPIO pins that can be controlled independently
    of test positions. Common uses include:
        - Power supply control (multiple supplies with make-break sequencing)
        - Relay control
        - Valve control
        - LED indicators
        - Any other GPIO-controlled device
    
    Each auxiliary output automatically generates two event types:
        - "{name} On" - Sets the GPIO HIGH
        - "{name} Off" - Sets the GPIO LOW
    
    These events can then be scheduled in the waveform timeline like any other event.
    
    Attributes:
        name (str): Human-readable name for this output (e.g., "Power Supply 1", "Relay A")
                   Used to generate event names ("{name} On", "{name} Off")
        gpio (int): GPIO pin number controlling this output
        enabled (bool): Whether this output is active (disabled outputs don't generate events)
    
    Example:
        >>> aux = AuxiliaryOutput(name="Power Supply 1", gpio=15, enabled=True)
        # This generates events: "Power Supply 1 On" and "Power Supply 1 Off"
    """
    name: str
    gpio: int
    enabled: bool = True


@dataclass
class Profile:
    """
    Complete test profile containing all configuration and waveform data.
    
    A profile defines a complete multi-position test sequence using a list
    of blocks that execute sequentially. Each block has its own waveform
    definition and cycle count, enabling complex test patterns with
    initialization, main testing, and shutdown phases.
    
    Execution Model:
        1. Profile starts with first block
        2. Block runs for its specified number of cycles
        3. Upon completion, execution moves to next block
        4. Process repeats until all blocks complete
        5. Test ends after final block finishes
    
    Attributes:
        profile_name (str): Human-readable name for this profile
        waveform_time_units (str): Time units used for all timing values ("ms", "sec", or "min")
        blocks (List[Block]): Ordered list of waveform blocks to execute sequentially
        isolator_waveform_points (List[Tuple[float, int]]): 
            Precomputed isolator waveform for all blocks as (time_ms, state) pairs
            where state is 0 (LOW) or 1 (HIGH)
        dut_waveform_points (List[Tuple[float, int]]): 
            Precomputed DUT waveform for all blocks as (time_ms, state) pairs
            where state is 0 (LOW) or 1 (HIGH)
        row_delay_ms (float): Delay in milliseconds between starting each position
                              (allows sequential activation of positions)
        positions (List[PositionConfig]): Configuration for all test positions
        auxiliary_outputs (List[AuxiliaryOutput]): Configuration for auxiliary GPIO outputs
                                                   (power supplies, relays, etc.)
        auxiliary_waveforms (dict): Precomputed auxiliary waveforms as dict of 
                                   {output_name: [(time_ms, state), ...]}
    
    Example:
        >>> profile = Profile(
        ...     profile_name="Complete Test Sequence",
        ...     waveform_time_units="ms",
        ...     blocks=[
        ...         Block("Init", [...], cycles=1),
        ...         Block("Main", [...], cycles=100),
        ...         Block("Shutdown", [...], cycles=1)
        ...     ],
        ...     isolator_waveform_points=[(0.0, 0), (10.0, 1), ...],
        ...     dut_waveform_points=[(0.0, 0), (20.0, 1), ...],
        ...     row_delay_ms=50.0,
        ...     positions=[...],
        ...     auxiliary_outputs=[
        ...         AuxiliaryOutput("Power Supply 1", 15, True),
        ...         AuxiliaryOutput("Power Supply 2", 16, True)
        ...     ],
        ...     auxiliary_waveforms={
        ...         "Power Supply 1": [(0, 0), (100, 1), ...],
        ...         "Power Supply 2": [(150, 0), (200, 1), ...]
        ...     }
        ... )
    """
    profile_name: str
    waveform_time_units: str
    blocks: List[Block]
    isolator_waveform_points: List[Tuple[float, int]]
    dut_waveform_points: List[Tuple[float, int]]
    row_delay_ms: float
    positions: List[PositionConfig]
    auxiliary_outputs: List[AuxiliaryOutput] = None  # Optional for backward compatibility
    auxiliary_waveforms: dict = None  # Optional for backward compatibility
    
    def __post_init__(self):
        """Initialize optional fields with defaults if not provided."""
        if self.auxiliary_outputs is None:
            self.auxiliary_outputs = []
        if self.auxiliary_waveforms is None:
            self.auxiliary_waveforms = {}
