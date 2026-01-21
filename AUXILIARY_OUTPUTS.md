# Auxiliary GPIO Output System

## Overview

The Auxiliary GPIO Output System allows you to define custom named outputs (like power supplies, relays, valves, etc.) that can be controlled as part of your waveform profile. Each auxiliary output automatically generates two schedulable events that can be used in your test sequence.

## Features

- **Dynamic Configuration**: Add and remove auxiliary outputs as needed
- **Named Outputs**: Each output has a descriptive name (e.g., "Power Supply 1", "Relay A")
- **Automatic Event Generation**: Each output creates "{Name} On" and "{Name} Off" events
- **Independent GPIO Control**: Each output controls a single GPIO pin
- **Enable/Disable**: Quickly enable or disable outputs without removing them
- **Profile Integration**: Saved with profiles for complete test documentation

## Use Cases

- **Make-Before-Break Testing**: Turn Power Supply 1 off, then Power Supply 2 on
- **Relay Control**: Control external relays for switching test equipment
- **Valve Control**: Sequence pneumatic or hydraulic valves
- **Multi-Power Supply**: Coordinate multiple power supplies with precise timing
- **Custom Hardware**: Control any GPIO-connected device

## Configuration

### Default Outputs

The system initializes with two default outputs:
- **Power Supply 1**: GPIO 15
- **Power Supply 2**: GPIO 16

### Adding Auxiliary Outputs

1. Open the **Auxiliary Outputs** section in the GUI
2. Click **"+ Add Output"**
3. Configure:
   - **Enabled**: Checkbox to enable/disable this output
   - **Name**: Descriptive name (used in event names)
   - **GPIO**: GPIO pin number to control

### Removing Auxiliary Outputs

- Click **"- Remove"** to remove the last auxiliary output

## Using Auxiliary Events

Once configured, auxiliary outputs automatically add events to the schedule builder:

Example with "Power Supply 1":
- **"Power Supply 1 On"** - Sets GPIO 15 HIGH
- **"Power Supply 1 Off"** - Sets GPIO 15 LOW

### Scheduling Example

```
Event                    Start    Duration
----------------------------------------------
Isolator On              0        300
Power Supply 1 On        50       0
Power Supply 1 Off       280      0
Power Supply 2 On        285      0
DUT On Time              80       200
DUT Off Time             280      120
Power Supply 2 Off       400      0
Cycle Delay              400      200
```

This sequence demonstrates make-before-break: Power Supply 1 turns off at 280ms, and Power Supply 2 turns on at 285ms (5ms break time).

## Technical Details

### Waveform Generation

- **Step Function**: Auxiliary outputs generate digital step waveforms (HIGH/LOW)
- **Timing**: Events with duration=0 create instantaneous state changes
- **Cycles**: Auxiliary waveforms repeat across all cycles in a block
- **Block Support**: Each block can have independent auxiliary waveform timing

### GPIO Behavior

- **Initial State**: All auxiliary outputs start LOW
- **On Event**: Sets output HIGH until an Off event occurs
- **Off Event**: Sets output LOW
- **Overlapping Events**: "Last start wins" - later events override earlier ones at the same time

### Data Model

#### AuxiliaryOutput Dataclass

```python
@dataclass
class AuxiliaryOutput:
    name: str           # Display name (e.g., "Power Supply 1")
    gpio: int           # GPIO pin number
    enabled: bool       # Whether this output is active
```

#### Profile Integration

The `Profile` dataclass includes:
- `auxiliary_outputs: List[AuxiliaryOutput]` - Configuration
- `auxiliary_waveforms: Dict[str, List[Tuple[float, int]]]` - Generated waveforms

Format of `auxiliary_waveforms`:
```python
{
    "Power Supply 1": [(0.0, 0), (50.0, 1), (280.0, 0), ...],
    "Power Supply 2": [(0.0, 0), (285.0, 1), (400.0, 0), ...]
}
```

Each tuple is `(time_ms: float, state: int)` where state is 0 (LOW) or 1 (HIGH).

## File Format

### JSON Structure

```json
{
  "profile_name": "Make-Break Test",
  "waveform_time_units": "ms",
  "blocks": [...],
  "auxiliary_outputs": [
    {
      "name": "Power Supply 1",
      "gpio": 15,
      "enabled": true
    },
    {
      "name": "Power Supply 2",
      "gpio": 16,
      "enabled": true
    }
  ],
  "auxiliary_waveforms": {
    "Power Supply 1": [
      [0.0, 0],
      [50.0, 1],
      [280.0, 0]
    ],
    "Power Supply 2": [
      [0.0, 0],
      [285.0, 1],
      [400.0, 0]
    ]
  }
}
```

### Backward Compatibility

Profiles without `auxiliary_outputs` are fully compatible:
- Old profiles load without errors
- Auxiliary outputs default to empty list
- No auxiliary waveforms are generated

## Implementation Notes

### Waveform Engine

**`build_auxiliary_waveforms()`** function:
- Scans schedule for "{Name} On" and "{Name} Off" events
- Builds steady-state blocks where output is HIGH
- Generates step waveform with state transitions
- Repeats waveform for specified number of cycles
- Returns dictionary keyed by output name

**Integration**: Called within `build_waveforms_from_blocks()`:
1. Generate auxiliary waveforms for each block
2. Apply time offsets to align with block timing
3. Combine waveforms across all blocks
4. Normalize to total profile length

### GUI Components

**Auxiliary Outputs Panel**:
- Scrollable list of auxiliary output rows
- Add/Remove buttons
- Enable checkbox, Name entry, GPIO entry per row
- Auto-updates event dropdowns when changed

**Event Management**:
- `_get_available_events()`: Combines base events + auxiliary events
- `_update_event_lists()`: Refreshes all schedule row comboboxes
- `_on_auxiliary_changed()`: Callback for auxiliary output changes

**Save/Load**:
- `_get_auxiliary_outputs()`: Extracts AuxiliaryOutput objects from GUI
- `_build_profile_object()`: Includes auxiliary outputs in Profile
- `_profile_to_json_text()`: Serializes auxiliary outputs to JSON
- `_on_load_profile()`: Restores auxiliary outputs from JSON

## Future Enhancements

Potential improvements for future versions:

1. **Reorder Outputs**: Drag-and-drop reordering
2. **GPIO Validation**: Check for conflicts with isolator/DUT pins
3. **Preview Visualization**: Display auxiliary channels in preview plot
4. **Templates**: Predefined sets of common auxiliary outputs
5. **Event Aliases**: Alternative names for the same output state
6. **Initial State**: Configure starting state (HIGH vs LOW)
7. **Pico Firmware**: Update to read and execute auxiliary waveforms

## Configuration Constants

In `config.py`:

```python
# Default GPIO pin for first auxiliary output
DEFAULT_AUXILIARY_GPIO_START = 15

# Default auxiliary outputs (name, gpio) tuples
DEFAULT_AUXILIARY_OUTPUTS = [
    ("Power Supply 1", 15),
    ("Power Supply 2", 16),
]
```

Customize these constants to change default auxiliary output configuration.

## Best Practices

1. **Descriptive Names**: Use clear, specific names like "24V Power Supply" instead of "Aux1"
2. **GPIO Allocation**: Reserve GPIOs 15-20 for auxiliary outputs to avoid conflicts
3. **Zero Duration Events**: Use duration=0 for instantaneous state changes
4. **Make-Before-Break**: Schedule break events 5-10ms apart to allow settling time
5. **Documentation**: Add comments in profile name or save file with test description
6. **Validation**: Always preview waveforms before running on hardware

## Troubleshooting

### Event Not Appearing in Dropdown

- Ensure auxiliary output is **Enabled** (checkbox checked)
- Verify output **Name** is not empty
- Check that `_on_auxiliary_changed()` was called (automatic on changes)

### Wrong GPIO Pin Activated

- Verify **GPIO** entry has correct pin number
- Check for conflicts with isolator or DUT GPIOs
- Review loaded profile JSON for correct GPIO assignment

### Waveform Not Generated

- Confirm auxiliary output is **Enabled**
- Verify schedule contains both "On" and "Off" events
- Check that event names match output name exactly (case-sensitive)

### Old Profiles Not Loading

- Profiles without `auxiliary_outputs` load with empty list (correct behavior)
- Remove event validation if custom events needed
- Check JSON structure for `auxiliary_outputs` array

## Support

For issues or feature requests:
1. Check this documentation
2. Review [CHANGELOG.md](CHANGELOG.md) for recent changes
3. See [README.md](README.md) for general usage
4. Open an issue on GitHub with example profile JSON
