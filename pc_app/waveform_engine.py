"""
Waveform Generation Engine
===========================
This module handles all waveform generation logic for the Profile Builder.

The waveform engine takes scheduled events and converts them into digital
waveforms that can be sent to hardware controllers or visualized in the GUI.

Key Concepts:
    - Scheduled events define time blocks with specific behaviors
    - Events can overlap; the most recent event determines the state
    - Digital waveforms are step functions (0 or 1)
    - Display waveforms can include ramps for visualization
    - Multiple cycles repeat the base waveform pattern

Functions:
    - state_last_start_wins: Determine signal state at a given time
    - build_digital_step_waveform: Generate digital step waveform from events
    - apply_directed_ramps_on_display: Add visual ramps to display waveform
    - build_waveforms_from_schedule: Main entry point for waveform generation
    - shift_series: Apply time offset to display waveform points
    - shift_step_points: Apply time offset to digital waveform points
    - build_preview_channels: Generate multi-channel preview data
"""

from typing import List, Dict, Tuple
# ----------------------------
# Local Module Imports
# ----------------------------
from models import (
    ScheduledEvent, PositionConfig, Block,
    ISO_ON_STEADY, ISO_OFF_STEADY, DUT_ON_STEADY, DUT_OFF_STEADY,
    ISO_RISE, ISO_FALL, DUT_RISE, DUT_FALL, EVENTS
)
from utils import to_ms, merge_duplicate_times_keep_last, normalize_step_points


# ----------------------------
# State Determination Functions
# ----------------------------

def state_last_start_wins(t_ms: float, blocks: List[Tuple[float, float, int]], default: int = 0) -> int:
    """
    Determine the signal state at a specific time based on overlapping blocks.
    
    When multiple blocks overlap at a given time, the block that started most
    recently wins. This implements a "last writer wins" policy for overlapping
    events, which is intuitive for users defining complex waveforms.
    
    Args:
        t_ms (float): The time in milliseconds to query
        blocks (List[Tuple[float, float, int]]): List of (start, end, state) tuples
                                                   defining time blocks
        default (int): Default state to return if no block covers t_ms (default: 0)
    
    Returns:
        int: The state (0 or 1) at time t_ms
    
    Example:
        >>> blocks = [(0.0, 100.0, 1), (50.0, 150.0, 0)]
        >>> state_last_start_wins(75.0, blocks)
        0  # The block starting at 50.0 wins over the one starting at 0.0
        >>> state_last_start_wins(200.0, blocks)
        0  # No block covers 200.0, return default
    
    Note:
        - Uses half-open intervals [start, end) for block coverage
        - If multiple blocks start at exactly the same time, the last one
          in the list takes precedence
    """
    best = None  # Track (start_time, state) of the winning block
    
    for start, end, state in blocks:
        # Check if this block covers the query time
        if start <= t_ms < end:
            # If no winner yet, or this block started more recently
            if best is None or start > best[0]:
                best = (start, state)
    
    # Return the winning state, or default if no block covers t_ms
    return best[1] if best else default


# ----------------------------
# Digital Waveform Generation
# ----------------------------

def build_digital_step_waveform(
    steady_blocks: List[Tuple[float, float, int]], 
    boundaries: List[float]
) -> List[Tuple[float, int]]:
    """
    Build a digital step waveform from steady-state blocks and boundary times.
    
    This function creates a step waveform by sampling the state at each boundary
    time. Boundaries typically include the start and end times of all events,
    ensuring that state changes are captured.
    
    Args:
        steady_blocks (List[Tuple[float, float, int]]): List of (start, end, state)
                                                         tuples defining when the
                                                         signal should be HIGH (1)
                                                         or LOW (0)
        boundaries (List[float]): List of time points where the waveform should
                                  be sampled (includes all event start/end times)
    
    Returns:
        List[Tuple[float, int]]: Normalized waveform as (time, state) tuples,
                                 with redundant points removed
    
    Example:
        >>> steady_blocks = [(10.0, 100.0, 1), (150.0, 200.0, 1)]
        >>> boundaries = [0.0, 10.0, 100.0, 150.0, 200.0]
        >>> build_digital_step_waveform(steady_blocks, boundaries)
        [(0.0, 0), (10.0, 1), (100.0, 0), (150.0, 1), (200.0, 1)]
    
    Note:
        - Returns a minimal waveform with at least 2 points
        - Automatically handles overlapping blocks using last-start-wins logic
    """
    # Handle edge case: no boundaries provided
    if not boundaries:
        return [(0.0, 0), (0.0, 0)]
    
    # Remove duplicates and sort boundaries
    b = sorted(set(boundaries))
    
    # Sample the state at each boundary time
    pts: List[Tuple[float, int]] = []
    for t in b:
        state = state_last_start_wins(t, steady_blocks, default=0)
        pts.append((t, state))
    
    # Add final point at the last boundary (ensures proper waveform termination)
    final_state = state_last_start_wins(b[-1], steady_blocks, default=0)
    pts.append((b[-1], final_state))
    
    # Normalize to remove redundant points
    return normalize_step_points(pts)


# ----------------------------
# Display Waveform with Ramps
# ----------------------------

def apply_directed_ramps_on_display(
    base_step_points: List[Tuple[float, int]],
    ramp_up_windows: List[Tuple[float, float]],
    ramp_down_windows: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """
    Apply visual ramps to a step waveform for display purposes.
    
    While digital waveforms are pure step functions, it's useful to visualize
    rise and fall times as ramps. This function overlays ramp transitions onto
    a base step waveform, creating a smooth display representation.
    
    Args:
        base_step_points (List[Tuple[float, int]]): Base step waveform as
                                                      (time, state) tuples
        ramp_up_windows (List[Tuple[float, float]]): List of (start, end) tuples
                                                       defining LOW->HIGH ramps
        ramp_down_windows (List[Tuple[float, float]]): List of (start, end) tuples
                                                         defining HIGH->LOW ramps
    
    Returns:
        List[Tuple[float, float]]: Display waveform with ramps, as (time, value)
                                   tuples where value ranges from 0.0 to 1.0
    
    Example:
        >>> base = [(0.0, 0), (10.0, 1), (100.0, 0)]
        >>> ramps_up = [(10.0, 15.0)]
        >>> ramps_down = [(100.0, 105.0)]
        >>> apply_directed_ramps_on_display(base, ramps_up, ramps_down)
        [(0.0, 0.0), (10.0, 0.0), (15.0, 1.0), (100.0, 1.0), (105.0, 0.0)]
    
    Note:
        - Ramps are purely for visualization; hardware uses digital step waveform
        - Multiple ramps at the same location are processed in order
        - Duplicate times are merged, keeping the last value
    """
    if not base_step_points:
        return []
    
    # Convert integer states to float values for display
    display = [(t, float(s)) for t, s in base_step_points]
    display = sorted(display, key=lambda x: x[0])
    display = merge_duplicate_times_keep_last(display)
    
    def overlay_ramp(ramp_start: float, ramp_end: float, v0: float, v1: float):
        """
        Overlay a single ramp onto the display waveform.
        
        This inner function removes any points within the ramp window and
        adds the ramp endpoints, creating a linear transition.
        """
        nonlocal display
        
        # Skip invalid ramps
        if ramp_end <= ramp_start:
            return
        
        # Keep only points outside the ramp window
        new_disp: List[Tuple[float, float]] = []
        for t, v in display:
            if t < ramp_start or t > ramp_end:
                new_disp.append((t, v))
        
        # Add ramp start and end points
        new_disp.append((ramp_start, v0))
        new_disp.append((ramp_end, v1))
        
        # Re-sort and merge duplicates
        new_disp = sorted(new_disp, key=lambda x: x[0])
        new_disp = merge_duplicate_times_keep_last(new_disp)
        display = new_disp
    
    # Apply all ramp-up transitions (0.0 -> 1.0)
    for rs, re in sorted(ramp_up_windows, key=lambda x: x[0]):
        overlay_ramp(rs, re, 0.0, 1.0)
    
    # Apply all ramp-down transitions (1.0 -> 0.0)
    for rs, re in sorted(ramp_down_windows, key=lambda x: x[0]):
        overlay_ramp(rs, re, 1.0, 0.0)
    
    return display


# ----------------------------
# Main Waveform Building Function
# ----------------------------

def build_waveforms_from_schedule(
    schedule: List[ScheduledEvent],
    unit: str,
    cycles: int,
) -> Tuple[
    List[Tuple[float, int]],     # Isolator digital waveform (expanded for all cycles)
    List[Tuple[float, int]],     # DUT digital waveform (expanded for all cycles)
    List[Tuple[float, float]],   # Isolator display waveform (with ramps, expanded)
    List[Tuple[float, float]],   # DUT display waveform (with ramps, expanded)
    bool,                         # True if isolator has ramp events
    bool,                         # True if DUT has ramp events
    float,                        # Length of a single cycle in milliseconds
]:
    """
    Generate complete waveforms from a schedule of events.
    
    This is the main entry point for waveform generation. It takes a schedule
    of events (which may overlap) and generates both digital step waveforms
    (for hardware) and display waveforms (with ramps for visualization).
    
    The function performs these steps:
    1. Convert all event times to milliseconds
    2. Classify events by type (isolator/DUT, on/off/rise/fall)
    3. Expand events across all cycles
    4. Build digital step waveforms
    5. Add visual ramps to display waveforms
    
    Args:
        schedule (List[ScheduledEvent]): List of scheduled waveform events
        unit (str): Time unit for event times ("ms", "sec", or "min")
        cycles (int): Number of times to repeat the waveform (must be >= 1)
    
    Returns:
        Tuple containing:
            - Isolator digital waveform points
            - DUT digital waveform points
            - Isolator display waveform points (with ramps)
            - DUT display waveform points (with ramps)
            - Boolean indicating if isolator has ramp events
            - Boolean indicating if DUT has ramp events
            - Single cycle length in milliseconds
    
    Raises:
        ValueError: If schedule is empty, cycles < 1, or invalid event parameters
    
    Example:
        >>> schedule = [
        ...     ScheduledEvent("Isolator On", 0.0, 100.0),
        ...     ScheduledEvent("DUT Hold Time", 20.0, 60.0),
        ...     ScheduledEvent("Cycle Delay", 100.0, 50.0)
        ... ]
        >>> iso_dig, dut_dig, iso_disp, dut_disp, iso_ramps, dut_ramps, cycle_ms = \
        ...     build_waveforms_from_schedule(schedule, "ms", 2)
    
    Note:
        - Cycle Delay events in the last cycle are automatically skipped
        - Overlapping events use "last start wins" logic
        - All times are converted to milliseconds internally
    """
    # Validate inputs
    if not schedule:
        raise ValueError("Add at least one schedule block.")
    if cycles < 1:
        raise ValueError("Cycles must be >= 1")
    
    # Step 1: Convert all events to milliseconds and collect boundaries
    base_events_ms: List[Tuple[str, float, float]] = []  # (event_name, start_ms, end_ms)
    base_boundaries: List[float] = [0.0]  # Always include t=0
    
    for ev in schedule:
        # Validate event type
        if ev.event not in EVENTS:
            raise ValueError(f"Unknown event '{ev.event}'")
        
        # Validate timing parameters
        if ev.start < 0:
            raise ValueError("Start must be >= 0")
        if ev.duration < 0:
            raise ValueError("Duration must be >= 0")
        
        # Convert to milliseconds
        s = to_ms(ev.start, unit)
        e = s + to_ms(ev.duration, unit)
        
        base_events_ms.append((ev.event, s, e))
        base_boundaries.extend([s, e])
    
    # Calculate the length of a single cycle
    cycle_length_ms = max(base_boundaries) if base_boundaries else 0.0
    
    # Step 2: Initialize data structures for waveform building
    boundaries: List[float] = [0.0]  # All time boundaries across all cycles
    
    # Steady-state blocks: (start, end, state)
    iso_steady_blocks: List[Tuple[float, float, int]] = []
    dut_steady_blocks: List[Tuple[float, float, int]] = []
    
    # Ramp windows: (start, end)
    iso_ramp_up: List[Tuple[float, float]] = []
    iso_ramp_down: List[Tuple[float, float]] = []
    dut_ramp_up: List[Tuple[float, float]] = []
    dut_ramp_down: List[Tuple[float, float]] = []
    
    # Step 3: Expand events across all cycles
    for c in range(cycles):
        # Calculate time shift for this cycle
        shift = c * cycle_length_ms
        
        for event, s0, e0 in base_events_ms:
            # Special case: skip Cycle Delay in the final cycle
            if event == "Cycle Delay" and c == cycles - 1:
                continue
            
            # Apply cycle time shift
            s = s0 + shift
            e = e0 + shift
            boundaries.extend([s, e])
            
            # Classify event and add to appropriate collections
            
            # Isolator events
            if event in ISO_ON_STEADY:
                iso_steady_blocks.append((s, e, 1))  # HIGH
            if event in ISO_OFF_STEADY:
                iso_steady_blocks.append((s, e, 0))  # LOW
            
            # DUT events
            if event in DUT_ON_STEADY:
                dut_steady_blocks.append((s, e, 1))  # HIGH
            if event in DUT_OFF_STEADY:
                dut_steady_blocks.append((s, e, 0))  # LOW
            
            # Ramp events (for display only)
            if event in ISO_RISE:
                iso_ramp_up.append((s, e))
            if event in ISO_FALL:
                iso_ramp_down.append((s, e))
            if event in DUT_RISE:
                dut_ramp_up.append((s, e))
            if event in DUT_FALL:
                dut_ramp_down.append((s, e))
    
    # Step 4: Build digital step waveforms
    iso_digital = build_digital_step_waveform(iso_steady_blocks, boundaries)
    dut_digital = build_digital_step_waveform(dut_steady_blocks, boundaries)
    
    # Step 5: Check if ramps exist
    iso_has_ramps = (len(iso_ramp_up) + len(iso_ramp_down)) > 0
    dut_has_ramps = (len(dut_ramp_up) + len(dut_ramp_down)) > 0
    
    # Step 6: Build display waveforms with ramps
    iso_display = apply_directed_ramps_on_display(iso_digital, iso_ramp_up, iso_ramp_down)
    dut_display = apply_directed_ramps_on_display(dut_digital, dut_ramp_up, dut_ramp_down)
    
    return iso_digital, dut_digital, iso_display, dut_display, iso_has_ramps, dut_has_ramps, cycle_length_ms


def build_waveforms_from_blocks(
    blocks: List[Block],
    unit: str,
) -> Tuple[
    List[Tuple[float, int]],     # Isolator digital waveform (all blocks combined)
    List[Tuple[float, int]],     # DUT digital waveform (all blocks combined)
    List[Tuple[float, float]],   # Isolator display waveform (all blocks combined)
    List[Tuple[float, float]],   # DUT display waveform (all blocks combined)
    bool,                         # True if isolator has ramp events
    bool,                         # True if DUT has ramp events
    float,                        # Total length of all blocks in milliseconds
    List[float],                  # List of block end times for visualization
]:
    """
    Generate complete waveforms from a sequence of blocks.
    
    This function processes multiple blocks in sequence, where each block
    has its own schedule and cycle count. Blocks execute one after another,
    with time offsets applied so each block starts where the previous one ended.
    
    This enables complex test sequences:
        - Initialization block (1 cycle)
        - Main test block (100 cycles)
        - Shutdown block (1 cycle)
    
    The function:
    1. Validates all blocks
    2. Processes each block using build_waveforms_from_schedule
    3. Applies time offsets to concatenate blocks
    4. Combines all block waveforms into single continuous waveforms
    5. Tracks block boundaries for visualization
    
    Args:
        blocks (List[Block]): Ordered list of blocks to execute sequentially
        unit (str): Time unit for event times ("ms", "sec", or "min")
    
    Returns:
        Tuple containing:
            - Isolator digital waveform points (all blocks)
            - DUT digital waveform points (all blocks)
            - Isolator display waveform points (all blocks, with ramps)
            - DUT display waveform points (all blocks, with ramps)
            - Boolean indicating if isolator has any ramp events
            - Boolean indicating if DUT has any ramp events
            - Total length in milliseconds (sum of all block lengths)
            - List of block end times (for marking boundaries in visualization)
    
    Raises:
        ValueError: If blocks list is empty, or if any block is invalid
    
    Example:
        >>> blocks = [
        ...     Block("Init", [ScheduledEvent("Isolator On", 0.0, 100.0)], cycles=1),
        ...     Block("Main", [ScheduledEvent("Isolator On", 0.0, 50.0), ...], cycles=10),
        ...     Block("Shutdown", [ScheduledEvent("Isolator On", 0.0, 100.0)], cycles=1)
        ... ]
        >>> iso_dig, dut_dig, iso_disp, dut_disp, iso_ramps, dut_ramps, total_ms, block_ends = \
        ...     build_waveforms_from_blocks(blocks, "ms")
        >>> # block_ends might be [100.0, 600.0, 700.0] if blocks are 100ms, 500ms, 100ms
    
    Note:
        - Each block is independent and starts at time 0 internally
        - Time offsets are applied to create continuous timeline
        - Block boundaries are tracked for visualization purposes
        - All blocks share the same time unit
    """
    if not blocks:
        raise ValueError("Add at least one block to the profile.")
    
    # Initialize combined waveform data structures
    combined_iso_digital: List[Tuple[float, int]] = []
    combined_dut_digital: List[Tuple[float, int]] = []
    combined_iso_display: List[Tuple[float, float]] = []
    combined_dut_display: List[Tuple[float, float]] = []
    
    # Track if any block has ramps
    any_iso_ramps = False
    any_dut_ramps = False
    
    # Track block end times for visualization boundaries
    block_end_times: List[float] = []
    
    # Current time offset (where next block should start)
    current_time_offset = 0.0
    
    # Process each block in sequence
    for block_idx, block in enumerate(blocks):
        if not block.scheduled_events:
            raise ValueError(f"Block '{block.block_name}' has no scheduled events.")
        
        if block.cycles < 1:
            raise ValueError(f"Block '{block.block_name}' must have cycles >= 1.")
        
        # Generate waveforms for this block
        iso_dig, dut_dig, iso_disp, dut_disp, iso_ramps, dut_ramps, block_length_ms = \
            build_waveforms_from_schedule(block.scheduled_events, unit, block.cycles)
        
        # Track if we have any ramps across all blocks
        any_iso_ramps = any_iso_ramps or iso_ramps
        any_dut_ramps = any_dut_ramps or dut_ramps
        
        # Apply time offset to this block's waveforms
        if current_time_offset > 0:
            # Offset digital waveforms
            iso_dig = [(t + current_time_offset, s) for t, s in iso_dig]
            dut_dig = [(t + current_time_offset, s) for t, s in dut_dig]
            
            # Offset display waveforms
            iso_disp = [(t + current_time_offset, v) for t, v in iso_disp]
            dut_disp = [(t + current_time_offset, v) for t, v in dut_disp]
        
        # Append to combined waveforms
        combined_iso_digital.extend(iso_dig)
        combined_dut_digital.extend(dut_dig)
        combined_iso_display.extend(iso_disp)
        combined_dut_display.extend(dut_disp)
        
        # Update time offset for next block
        current_time_offset += block_length_ms
        
        # Record this block's end time
        block_end_times.append(current_time_offset)
    
    # Normalize combined waveforms to remove any redundant points at block boundaries
    combined_iso_digital = normalize_step_points(combined_iso_digital)
    combined_dut_digital = normalize_step_points(combined_dut_digital)
    combined_iso_display = merge_duplicate_times_keep_last(combined_iso_display)
    combined_dut_display = merge_duplicate_times_keep_last(combined_dut_display)
    
    # Total length is the final time offset
    total_length_ms = current_time_offset
    
    return (combined_iso_digital, combined_dut_digital,
            combined_iso_display, combined_dut_display,
            any_iso_ramps, any_dut_ramps,
            total_length_ms, block_end_times)


# ----------------------------
# Waveform Shifting Functions
# ----------------------------

def shift_series(points: List[Tuple[float, float]], shift_ms: float) -> Tuple[List[float], List[float]]:
    """
    Apply a time offset to display waveform points and separate into lists.
    
    This function shifts all time values by a constant offset and returns
    separate lists for times and values, which is useful for plotting.
    
    Args:
        points (List[Tuple[float, float]]): Waveform as (time, value) tuples
        shift_ms (float): Time offset to add to all points (in milliseconds)
    
    Returns:
        Tuple[List[float], List[float]]: Separate lists of (times, values)
    
    Example:
        >>> points = [(0.0, 0.0), (10.0, 1.0), (20.0, 0.0)]
        >>> times, values = shift_series(points, 50.0)
        >>> times
        [50.0, 60.0, 70.0]
        >>> values
        [0.0, 1.0, 0.0]
    """
    times = [t + shift_ms for t, _ in points]
    values = [v for _, v in points]
    return times, values


def shift_step_points(points: List[Tuple[float, int]], shift_ms: float) -> Tuple[List[float], List[int]]:
    """
    Apply a time offset to digital waveform points and separate into lists.
    
    Similar to shift_series but for digital (integer state) waveforms.
    
    Args:
        points (List[Tuple[float, int]]): Waveform as (time, state) tuples
        shift_ms (float): Time offset to add to all points (in milliseconds)
    
    Returns:
        Tuple[List[float], List[int]]: Separate lists of (times, states)
    
    Example:
        >>> points = [(0.0, 0), (10.0, 1), (20.0, 0)]
        >>> times, states = shift_step_points(points, 50.0)
        >>> times
        [50.0, 60.0, 70.0]
        >>> states
        [0, 1, 0]
    """
    times = [t + shift_ms for t, _ in points]
    states = [s for _, s in points]
    return times, states


# ----------------------------
# Multi-Channel Preview Generation
# ----------------------------

def build_preview_channels(
    positions: List[PositionConfig],
    row_delay_ms: float,
    iso_display: List[Tuple[float, float]],
    dut_display: List[Tuple[float, float]],
    iso_digital: List[Tuple[float, int]],
    dut_digital: List[Tuple[float, int]],
) -> Dict[str, Dict]:
    """
    Generate multi-channel preview data for all enabled positions.
    
    This function creates preview waveforms for each enabled position, applying
    row delays and DUT offsets as configured. Each position gets two channels:
    one for the isolator and one for the DUT.
    
    Args:
        positions (List[PositionConfig]): List of all position configurations
        row_delay_ms (float): Delay between starting each position (milliseconds)
        iso_display (List[Tuple[float, float]]): Base isolator display waveform
        dut_display (List[Tuple[float, float]]): Base DUT display waveform
        iso_digital (List[Tuple[float, int]]): Base isolator digital waveform
        dut_digital (List[Tuple[float, int]]): Base DUT digital waveform
    
    Returns:
        Dict[str, Dict]: Dictionary mapping channel names to channel data.
                         Each channel has keys: "display_t", "display_v",
                         "digital_t", "digital_v"
    
    Example:
        >>> positions = [
        ...     PositionConfig(1, True, 1, 21, 10.0),
        ...     PositionConfig(2, True, 2, 22, 5.0)
        ... ]
        >>> channels = build_preview_channels(positions, 50.0, iso_disp, dut_disp, 
        ...                                    iso_dig, dut_dig)
        >>> list(channels.keys())
        ['ISO P1 (GPIO1)', 'DUT P1 (GPIO21)', 'ISO P2 (GPIO2)', 'DUT P2 (GPIO22)']
    
    Note:
        - Only enabled positions are included in the output
        - Isolator waveforms are shifted by: position_index * row_delay_ms
        - DUT waveforms are shifted by: position_index * row_delay_ms + dut_offset_ms
        - Channel names include GPIO numbers for hardware reference
    """
    # Filter to only enabled positions
    enabled = [p for p in positions if p.enabled]
    
    if not enabled:
        return {}
    
    out: Dict[str, Dict] = {}
    
    # Generate channels for each enabled position
    for idx, p in enumerate(enabled):
        # Calculate base time shift for this position (row delay)
        base_shift = idx * row_delay_ms
        
        # Generate isolator channel
        t_iso_disp, v_iso_disp = shift_series(iso_display, base_shift)
        t_iso_dig, v_iso_dig = shift_step_points(iso_digital, base_shift)
        
        iso_channel_name = f"ISO P{p.position} (GPIO{p.isolator_gpio})"
        out[iso_channel_name] = {
            "display_t": t_iso_disp,
            "display_v": v_iso_disp,
            "digital_t": t_iso_dig,
            "digital_v": v_iso_dig,
        }
        
        # Generate DUT channel (with additional DUT-specific offset)
        dut_shift = base_shift + float(p.dut_offset_ms)
        t_dut_disp, v_dut_disp = shift_series(dut_display, dut_shift)
        t_dut_dig, v_dut_dig = shift_step_points(dut_digital, dut_shift)
        
        dut_channel_name = f"DUT P{p.position} (GPIO{p.dut_gpio})"
        out[dut_channel_name] = {
            "display_t": t_dut_disp,
            "display_v": v_dut_disp,
            "digital_t": t_dut_dig,
            "digital_v": v_dut_dig,
        }
    
    return out
