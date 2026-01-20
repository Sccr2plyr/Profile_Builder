"""
Utility Functions Module
=========================
This module contains helper functions used throughout the application.

Functions:
    - to_ms: Convert time values to milliseconds
    - merge_duplicate_times_keep_last: Merge consecutive points with same time
    - normalize_step_points: Normalize and compact step waveform points
"""

from typing import List, Tuple
from models import UNIT_TO_MS


# ----------------------------
# Time Conversion Functions
# ----------------------------

def to_ms(value: float, unit: str) -> float:
    """
    Convert a time value from the specified unit to milliseconds.
    
    This function is used throughout the application to normalize all time
    values to a common millisecond representation for consistent processing.
    
    Args:
        value (float): The time value to convert
        unit (str): The source unit ("ms", "sec", or "min")
    
    Returns:
        float: The time value in milliseconds
    
    Raises:
        ValueError: If the specified unit is not supported
    
    Examples:
        >>> to_ms(1.5, "sec")
        1500.0
        >>> to_ms(100, "ms")
        100.0
        >>> to_ms(2, "min")
        120000.0
    """
    if unit not in UNIT_TO_MS:
        raise ValueError(f"Unsupported unit: {unit}. Must be one of {list(UNIT_TO_MS.keys())}")
    return float(value) * UNIT_TO_MS[unit]


# ----------------------------
# Waveform Point Processing
# ----------------------------

def merge_duplicate_times_keep_last(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Merge consecutive waveform points that have the same time value.
    
    When multiple points share the same (or nearly same) timestamp, this function
    keeps only the last value at that timestamp. This is useful for cleaning up
    waveform data where transitions are represented as multiple points at the
    same time.
    
    Args:
        points (List[Tuple[float, float]]): List of (time, value) tuples
    
    Returns:
        List[Tuple[float, float]]: List with duplicate times merged, keeping last value
    
    Example:
        >>> points = [(0.0, 0.0), (10.0, 0.0), (10.0, 1.0), (20.0, 1.0)]
        >>> merge_duplicate_times_keep_last(points)
        [(0.0, 0.0), (10.0, 1.0), (20.0, 1.0)]
    
    Note:
        Uses a tolerance of 1e-9 milliseconds for time comparison to handle
        floating-point precision issues.
    """
    out: List[Tuple[float, float]] = []
    
    for t, v in points:
        # If we have points and the current time matches the last time (within tolerance)
        if out and abs(out[-1][0] - t) < 1e-9:
            # Replace the last point with the current one (keep last value)
            out[-1] = (t, v)
        else:
            # Different time, add as new point
            out.append((t, v))
    
    return out


def normalize_step_points(points: List[Tuple[float, int]]) -> List[Tuple[float, int]]:
    """
    Normalize and compact a step waveform by removing redundant points.
    
    This function performs several operations:
    1. Sorts points by time
    2. Merges duplicate timestamps (keeping last value)
    3. Removes intermediate points where the value doesn't change
    4. Ensures there are at least 2 points for plotting
    
    Args:
        points (List[Tuple[float, int]]): List of (time, state) tuples where
                                          state is 0 or 1
    
    Returns:
        List[Tuple[float, int]]: Normalized list with minimal points needed
                                 to represent the waveform
    
    Example:
        >>> points = [(0.0, 0), (10.0, 0), (20.0, 1), (30.0, 1), (40.0, 1)]
        >>> normalize_step_points(points)
        [(0.0, 0), (20.0, 1), (40.0, 1)]
    
    Note:
        - A waveform must have at least 2 points for proper display
        - Consecutive points with the same state are collapsed to just the
          first and last point at that state
        - Uses 1e-9 tolerance for time comparison
    """
    if not points:
        return []
    
    # Step 1: Sort by time
    pts = sorted(points, key=lambda x: x[0])
    
    # Step 2: Merge duplicate timestamps (keep last state)
    merged: List[Tuple[float, int]] = []
    for t, s in pts:
        if merged and abs(merged[-1][0] - t) < 1e-9:
            merged[-1] = (t, s)
        else:
            merged.append((t, s))
    
    # Step 3: Remove redundant intermediate points (keep only state changes and endpoints)
    compact: List[Tuple[float, int]] = []
    for i, (t, s) in enumerate(merged):
        if not compact:
            # Always keep the first point
            compact.append((t, s))
            continue
        
        is_last = (i == len(merged) - 1)
        
        # Keep this point if the state changes OR if it's the last point
        if s != compact[-1][1] or is_last:
            compact.append((t, s))
    
    # Step 4: Ensure at least 2 points for plotting
    if len(compact) == 1:
        compact.append((compact[0][0], compact[0][1]))
    
    return compact
