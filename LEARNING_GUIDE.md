# Profile Builder - Learning Guide for Non-Programmers

**Welcome!** This guide will help you understand exactly what the Profile Builder code does and why, even if you're not experienced with coding. Think of this as your personal tutor for understanding the system.

---

## Table of Contents
1. [The Big Picture: What This Application Does](#the-big-picture)
2. [The Data Flow: From GUI to Hardware](#the-data-flow)
3. [Key Concepts Explained Simply](#key-concepts-explained-simply)
4. [The File Structure: What Each File Does](#the-file-structure)
5. [Data Structures: How Information Is Organized](#data-structures)
6. [The Waveform Engine: The Brain of the Operation](#the-waveform-engine)
7. [The GUI: What You See and Touch](#the-gui)
8. [Saving and Loading: How Profiles Are Stored](#saving-and-loading)
9. [Common Patterns You'll See in the Code](#common-patterns)
10. [Walking Through a Complete Example](#walking-through-example)

---

## The Big Picture: What This Application Does

### The Simple Explanation

Imagine you're a conductor of an orchestra, but instead of musicians, you're controlling electronic components (like power supplies, relays, and test equipment). The Profile Builder is your "sheet music" - it lets you write down exactly when each "instrument" should turn on, how long it should stay on, and when it should turn off.

### The Technical Explanation

The Profile Builder is a **test automation system**. It:
1. Lets you **define a test sequence** (what happens and when)
2. **Generates precise timing waveforms** (mathematical representations of on/off signals)
3. **Saves these waveforms as instructions** (JSON files)
4. **Sends them to hardware** (Raspberry Pi Pico) that executes the test

### Why This Matters

In manufacturing or testing environments, you need to:
- Test products repeatedly with **exact timing** (millisecond precision)
- Control **multiple devices** (10 test positions, each with isolator and DUT)
- Document tests for **quality assurance** (saved profiles)
- Make **changes easily** without rewiring hardware

---

## The Data Flow: From GUI to Hardware

Here's the journey your test profile takes from your brain to the hardware:

```
YOU (User)
    ↓
[1] GUI Input: Click, type, configure
    ↓
[2] Tkinter Variables: Live data storage (tk.StringVar, tk.IntVar, etc.)
    ↓
[3] Python Objects: Structured data (ScheduledEvent, Block, Profile)
    ↓
[4] Waveform Engine: Mathematical processing
    ↓
[5] Digital Waveforms: List of (time, state) tuples
    ↓
[6] JSON File: Text format for storage
    ↓
[7] Serial Port: Communication wire
    ↓
[8] Raspberry Pi Pico: Microcontroller hardware
    ↓
[9] GPIO Pins: Physical outputs
    ↓
[10] YOUR TEST HARDWARE: Relays, power supplies, etc.
```

### What Happens at Each Step

**[1] GUI Input**: You add a schedule event like "Power Supply 1 On at 50ms"

**[2] Tkinter Variables**: The GUI stores this in memory as:
- `event_var = "Power Supply 1 On"`
- `start_var = 50.0`
- `duration_var = 0.0`

**[3] Python Objects**: When you click "Rebuild", it creates:
```python
ScheduledEvent(event="Power Supply 1 On", start=50.0, duration=0.0)
```

**[4] Waveform Engine**: The math happens:
- "Power Supply 1 On at 50ms" → Turn GPIO 15 HIGH at 50ms
- Creates a list of all state changes for the entire test

**[5] Digital Waveforms**: The result is a list:
```python
[(0.0, 0),      # Start at time 0ms, state LOW (off)
 (50.0, 1),     # At 50ms, change to HIGH (on)
 (280.0, 0)]    # At 280ms, change to LOW (off)
```

**[6] JSON File**: Saved as text that both humans and computers can read

**[7-10]**: Hardware execution (Pico reads the file and controls real pins)

---

## Key Concepts Explained Simply

### 1. Events vs. Waveforms

**Event** = "What you want to happen"
- Example: "Turn on isolator from 0ms to 300ms"
- Human-readable
- What you configure in the GUI

**Waveform** = "The precise instructions for hardware"
- Example: `[(0, 1), (300, 0)]` means "set HIGH at 0ms, set LOW at 300ms"
- Machine-readable
- What the Pico executes

**Why Both?** Events are easy for humans to think about. Waveforms are what hardware needs to execute.

### 2. Blocks: Sequential Test Phases

Think of blocks like **chapters in a book**. Each chapter (block) has:
- A **name** (e.g., "Warm-Up Phase", "Stress Test")
- Its own **schedule of events** (what happens in this phase)
- A **cycle count** (how many times to repeat this phase)

**Why Blocks?** You might want:
- Block 1: "Warm-Up" - Run 5 cycles at low power
- Block 2: "Stress Test" - Run 100 cycles at high power
- Block 3: "Cool-Down" - Run 3 cycles at low power

Without blocks, you'd have to manually repeat events - with blocks, you just say "do this 100 times."

### 3. Positions: Multiple Test Stations

Imagine a factory assembly line with 10 stations. Each station:
- Tests one product (DUT = Device Under Test)
- Has an isolator (power switch for safety)
- Can start at different times (row delay)
- Can have timing offsets (DUT offset)

**Why?** Testing one product at a time is slow. Testing 10 simultaneously is 10x faster!

### 4. Auxiliary Outputs: Custom Control

These are like "wild card" outputs you define yourself:
- Power Supply 1, Power Supply 2
- Relay A, Relay B
- Valve 1, Pneumatic Clamp, etc.

Each one gets a GPIO pin and generates its own waveform based on your schedule.

### 5. Rise/Fall Time: Smooth Transitions

Real hardware doesn't switch instantly from OFF to ON. There's a **ramp** (transition period).

- **Rise Time**: How long to go from 0% to 100%
- **Fall Time**: How long to go from 100% to 0%

**Why Model This?** So you can see realistic waveforms in the preview and know if signals might overlap.

---

## The File Structure: What Each File Does

### Core Application Files

#### `models.py` - The Data Containers

**What it does**: Defines the "shape" of your data

Think of this like designing forms/templates:
- **ScheduledEvent**: A form with 3 fields (event, start, duration)
- **Block**: A form for a test phase (name, schedule list, cycles)
- **Profile**: The master form that contains everything
- **PositionConfig**: Settings for one test station
- **AuxiliaryOutput**: Settings for one custom output

**Why separate this?** Keep data definitions in one place so everyone uses the same "form template."

**Key Code Pattern**:
```python
@dataclass
class ScheduledEvent:
    event: str       # What happens (e.g., "Isolator On")
    start: float     # When it starts (e.g., 0.0)
    duration: float  # How long it lasts (e.g., 300.0)
```

The `@dataclass` decorator automatically creates a constructor, so you can write:
```python
ev = ScheduledEvent("Isolator On", 0.0, 300.0)
```

#### `waveform_engine.py` - The Math Brain

**What it does**: Converts human-friendly events into hardware-ready waveforms

Think of this as a **translator**:
- Input: "Turn on isolator from 0ms to 300ms"
- Output: `[(0, 1), (300, 0)]` (time, state pairs)

**Why separate this?** The math is complex and should be isolated from the GUI code.

**Main Functions**:

1. **`build_waveforms_from_schedule()`**: Processes one block
   - Takes a list of events
   - Handles overlapping events
   - Creates digital and display waveforms

2. **`build_waveforms_from_blocks()`**: Processes all blocks
   - Calls `build_waveforms_from_schedule()` for each block
   - Adds time offsets so blocks run sequentially
   - Combines all blocks into one long waveform

3. **`build_auxiliary_waveforms()`**: Generates custom output waveforms
   - Scans for "{Name} On" and "{Name} Off" events
   - Creates waveforms for each auxiliary output

4. **`build_preview_channels()`**: Creates multi-position preview data
   - Applies row delays (stagger position start times)
   - Applies DUT offsets
   - Formats data for matplotlib plotting

#### `waveform_profile_builder.py` - The GUI

**What it does**: The graphical interface you interact with

This is the **largest file** because GUIs are complex. It contains:
- **Window layout** (frames, labels, buttons, entry fields)
- **Event handlers** (what happens when you click a button)
- **Data binding** (connecting GUI widgets to Tkinter variables)
- **Validation** (checking your inputs make sense)

**Why so big?** GUIs have lots of visual elements and interactions.

**Key Sections**:
- `__init__()`: Set up initial state
- `_build_layout()`: Create all GUI widgets
- `_rebuild_and_preview()`: Generate and display waveforms
- `_on_save_profile()` / `_on_load_profile()`: File operations
- Block management methods: Add, remove, switch between blocks
- Position methods: Configure test stations
- Auxiliary methods: Configure custom outputs

#### `config.py` - Settings and Constants

**What it does**: Stores default values and configuration

Think of this as the **settings file**:
```python
DEFAULT_ISOLATOR_RISE_MS = 0.0
DEFAULT_DUT_RISE_MS = 8.0
DEFAULT_AUXILIARY_GPIO_START = 15
```

**Why separate this?** Easy to change defaults without hunting through code.

#### `utils.py` - Helper Functions

**What it does**: Small utility functions used everywhere

Example:
```python
def to_ms(value: float, unit: str) -> float:
    """Convert time value to milliseconds"""
    return value * UNIT_TO_MS[unit]
```

**Why separate this?** Don't repeat the same code in multiple places.

#### `pico_serial.py` - Hardware Communication

**What it does**: Talks to the Raspberry Pi Pico over USB

**Key Operations**:
- Connect to COM port
- Send JSON file
- Send control commands (run, pause, resume, stop)
- Receive status messages

### Test Files

#### `tests/test_models.py`

Tests that the data structures work correctly:
- Can create objects
- Default values work
- JSON serialization works

#### `tests/test_waveform_engine.py`

Tests that the math is correct:
- Waveforms have right number of points
- Overlapping events handled correctly
- Blocks combine correctly
- Edge cases don't crash

---

## Data Structures: How Information Is Organized

### Why Data Structures Matter

Imagine organizing a filing cabinet. You could:
- **Bad**: Throw all papers in randomly
- **Good**: Use folders, labels, sections

Data structures are like **labeled folders** for your data. Good organization makes code:
- Easier to understand
- Less prone to bugs
- Easier to modify

### The Profile Builder Hierarchy

```
Profile (The entire test configuration)
├── profile_name: str
├── waveform_time_units: str
├── blocks: List[Block]
│   └── Block
│       ├── block_name: str
│       ├── cycles: int
│       └── scheduled_events: List[ScheduledEvent]
│           └── ScheduledEvent
│               ├── event: str
│               ├── start: float
│               └── duration: float
├── positions: List[PositionConfig]
│   └── PositionConfig
│       ├── position: int
│       ├── enabled: bool
│       ├── isolator_gpio: int
│       ├── dut_gpio: int
│       └── dut_offset_ms: float
├── auxiliary_outputs: List[AuxiliaryOutput]
│   └── AuxiliaryOutput
│       ├── name: str
│       ├── gpio: int
│       └── enabled: bool
├── isolator_waveform_points: List[Tuple[float, int]]
├── dut_waveform_points: List[Tuple[float, int]]
└── auxiliary_waveforms: Dict[str, List[Tuple[float, int]]]
```

### Understanding Each Level

#### Profile - The Master Container

```python
@dataclass
class Profile:
    profile_name: str
    waveform_time_units: str
    blocks: List[Block]
    # ... more fields
```

**Think of it as**: A complete test recipe
- Name: What you call this test
- Units: ms, sec, or min (like choosing metric vs imperial)
- Blocks: The test phases
- Positions: The test stations
- Waveforms: The computed results

#### Block - A Test Phase

```python
@dataclass
class Block:
    block_name: str
    cycles: int
    scheduled_events: List[ScheduledEvent]
```

**Think of it as**: One chapter in your test
- Name: "Warm-Up", "Stress Test", etc.
- Cycles: How many times to repeat
- Scheduled Events: What happens during this phase

#### ScheduledEvent - One Action

```python
@dataclass
class ScheduledEvent:
    event: str
    start: float
    duration: float
```

**Think of it as**: One line in your script
- Event: What action to take
- Start: When to start (in your chosen units)
- Duration: How long it lasts

**Example**:
```python
ScheduledEvent("Isolator On", 0.0, 300.0)
# "Turn on isolator, starting at 0ms, for 300ms"
```

#### PositionConfig - One Test Station

```python
@dataclass
class PositionConfig:
    position: int           # Which station (1-10)
    enabled: bool          # Is this station active?
    isolator_gpio: int     # Which pin controls the isolator
    dut_gpio: int          # Which pin controls the DUT
    dut_offset_ms: float   # Time offset for this station
```

**Think of it as**: Settings for one workstation on your assembly line

#### AuxiliaryOutput - Custom Control

```python
@dataclass
class AuxiliaryOutput:
    name: str      # "Power Supply 1"
    gpio: int      # Pin 15
    enabled: bool  # Is it active?
```

**Think of it as**: Adding a custom button to your control panel

### Waveform Data Structure

After the waveform engine processes your events, it creates:

```python
# List of (time_milliseconds, state) tuples
waveform = [
    (0.0, 0),      # At 0ms, state is LOW (off)
    (50.0, 1),     # At 50ms, change to HIGH (on)
    (300.0, 0),    # At 300ms, change to LOW (off)
    (600.0, 1),    # At 600ms, change to HIGH (on)
]
```

**Why tuples?** A tuple `(time, state)` is a pair that can't be modified accidentally. It's like saying "these two values go together as one unit."

**Why a list?** The waveform is a sequence of state changes in chronological order.

---

## The Waveform Engine: The Brain of the Operation

This is the most complex part, so let's break it down step by step.

### Problem: Overlapping Events

Imagine you schedule:
- "Isolator On" from 0-300ms
- "Isolator Ramp Down" from 280-320ms

These **overlap** from 280-300ms. What should happen?

**Solution: "Last Start Wins"**

The event that **starts later** takes priority. So "Isolator Ramp Down" (starts at 280ms) wins over "Isolator On" (starts at 0ms) in the overlap zone.

### Algorithm: Building a Waveform

Here's the step-by-step process in `build_waveforms_from_schedule()`:

#### Step 1: Convert to Milliseconds

```python
# User might enter "5 seconds" but we need everything in ms
start_ms = 5.0 * 1000 = 5000.0
```

#### Step 2: Find All Time Boundaries

```python
# If you have events at:
# Event 1: 0-100ms
# Event 2: 50-150ms
# Boundaries are: [0, 50, 100, 150]
```

**Why?** We need to know every point where something might change.

#### Step 3: Build "Steady-State Blocks"

For each time interval between boundaries:
1. Check which events are active
2. Apply "last start wins" to resolve conflicts
3. Determine the state (HIGH, LOW, or ramping)

```python
# From 0-50ms: Only Event 1 is active → HIGH
# From 50-100ms: Both active, Event 2 starts later → Event 2's state
# From 100-150ms: Only Event 2 is active → Event 2's state
```

#### Step 4: Generate State Changes

Only record when the state **changes**:

```python
# If state is HIGH from 0-50, then RAMP from 50-100, then LOW from 100-150:
waveform = [
    (0, HIGH),
    (50, RAMP_START),
    (100, LOW)
]
```

#### Step 5: Add Rise/Fall Ramps

If an event has `rise_time_ms`, add intermediate points:

```python
# Rising from 0 to 1 over 10ms:
ramp = [
    (0, 0.0),
    (2, 0.2),
    (4, 0.4),
    (6, 0.6),
    (8, 0.8),
    (10, 1.0)
]
```

### Multi-Block Processing

`build_waveforms_from_blocks()` handles multiple blocks:

```python
# Block 1: 0-600ms (1 cycle)
# Block 2: 600-2400ms (3 cycles, 600ms each)
# Block 3: 2400-3000ms (1 cycle)

# Process each block:
for block_index, block in enumerate(blocks):
    # Generate waveform for this block
    block_waveform = build_waveforms_from_schedule(...)
    
    # Add time offset
    time_offset = sum(previous_block_lengths)
    offset_waveform = [(t + time_offset, state) for t, state in block_waveform]
    
    # Append to total waveform
    total_waveform.extend(offset_waveform)
```

### Auxiliary Waveforms

For custom outputs, the engine:

1. Scans schedule for "{Name} On" and "{Name} Off" events
2. Builds intervals where output should be HIGH
3. Generates step waveform (no ramps, just digital steps)

```python
def build_auxiliary_waveforms(schedule, auxiliary_outputs, unit, cycles):
    result = {}
    
    for aux_output in auxiliary_outputs:
        if not aux_output.enabled:
            continue
            
        name = aux_output.name
        on_event = f"{name} On"
        off_event = f"{name} Off"
        
        # Find all On/Off events
        on_times = [ev.start for ev in schedule if ev.event == on_event]
        off_times = [ev.start for ev in schedule if ev.event == off_event]
        
        # Build steady-state blocks where output is HIGH
        # ... (complex logic here) ...
        
        result[name] = waveform
    
    return result
```

---

## The GUI: What You See and Touch

### Tkinter: The GUI Framework

**Tkinter** is Python's built-in GUI library. Think of it as a toolkit:
- **Widgets**: Building blocks (buttons, text boxes, labels)
- **Frames**: Containers to organize widgets
- **Variables**: Live data connections (tk.StringVar, tk.IntVar)
- **Events**: Actions that trigger code (button clicks, key presses)

### Widget Hierarchy

```
Window (tb.Window)
├── Top Bar (Frame)
│   ├── Profile Name (Entry)
│   ├── Units (Combobox)
│   ├── Current Block Label (Label)
│   ├── Load Button (Button)
│   └── Save Button (Button)
├── Mid Panel (PanedWindow)
│   ├── Left Panel (ScrolledFrame)
│   │   ├── Pico Controls (Labelframe)
│   │   ├── Block Management (Labelframe)
│   │   ├── Schedule Builder (Labelframe)
│   │   ├── Auxiliary Outputs (Labelframe)
│   │   └── Positions (Labelframe)
│   └── Right Panel (Frame)
│       ├── Summary Label (Label)
│       └── Preview Canvas (Matplotlib)
```

### Tkinter Variables: The Magic Link

**Problem**: How does a text box know when you type?

**Solution**: Tkinter Variables

```python
# Create a variable
self.profile_name = tk.StringVar(value="New Profile")

# Link it to a text box
entry = tb.Entry(top, textvariable=self.profile_name)

# Now, when you type in the box, the variable updates automatically!
# And you can read it anytime:
name = self.profile_name.get()  # Returns "New Profile" (or whatever you typed)
```

**Types**:
- `StringVar`: Text (profile name, event type)
- `IntVar`: Whole numbers (GPIO pins, cycles)
- `DoubleVar`: Decimal numbers (times, delays)
- `BooleanVar`: True/False (enabled checkboxes)

### Event Binding: Making Things Happen

When you want code to run when something happens:

```python
# Run function when button clicked
button = tb.Button(frame, text="Save", command=self._on_save_profile)

# Run function when text box loses focus
entry.bind("<FocusOut>", lambda event: self._rebuild_and_preview())

# Run function when Enter key pressed
entry.bind("<Return>", lambda event: self._rebuild_and_preview())
```

**The lambda trick**: `lambda event: function()` creates a tiny anonymous function that ignores the event parameter and just calls your function.

### Dynamic Widget Creation

**Challenge**: You don't know how many schedule rows the user will create.

**Solution**: Create widgets programmatically and store them in a list.

```python
# Start with empty list
self.schedule_rows = []

def _add_schedule_row(self, event="Isolator On", start=0.0, duration=0.0):
    # Create variables
    ev_var = tk.StringVar(value=event)
    st_var = tk.DoubleVar(value=start)
    du_var = tk.DoubleVar(value=duration)
    
    # Create frame
    row = tb.Frame(self.sched_container)
    row.pack(fill=X, pady=2)
    
    # Create widgets
    tb.Combobox(row, textvariable=ev_var, ...).pack(side=LEFT)
    tb.Entry(row, textvariable=st_var, ...).pack(side=LEFT)
    tb.Entry(row, textvariable=du_var, ...).pack(side=LEFT)
    tb.Button(row, text="Remove", command=remove_func).pack(side=LEFT)
    
    # Store for later access
    self.schedule_rows.append((ev_var, st_var, du_var, row))
```

Now you can add unlimited schedule rows!

### The Preview Pipeline

When you change anything in the GUI:

```python
def _rebuild_and_preview(self):
    # 1. Extract data from GUI
    unit = self.waveform_unit.get()
    blocks = self._get_blocks()
    auxiliary_outputs = self._get_auxiliary_outputs()
    positions = self._get_positions()
    
    # 2. Generate waveforms
    iso_digital, dut_digital, iso_display, dut_display, ..., aux_waveforms = \
        build_waveforms_from_blocks(blocks, unit, auxiliary_outputs)
    
    # 3. Generate multi-position preview
    channels = build_preview_channels(positions, row_delay, iso_display, dut_display, ...)
    
    # 4. Plot on matplotlib
    for channel_name, channel_data in channels.items():
        t = channel_data["display_t"]
        v = channel_data["display_v"]
        self.ax.plot(t, v)
    
    # 5. Refresh display
    self.canvas.draw()
```

---

## Saving and Loading: How Profiles Are Stored

### JSON: The Universal Format

**JSON** (JavaScript Object Notation) is a text format that's:
- **Human-readable**: You can open it in Notepad
- **Machine-parseable**: Python can read/write it easily
- **Universal**: Almost every language supports it

### Example Profile JSON

```json
{
  "profile_name": "My Test",
  "waveform_time_units": "ms",
  "blocks": [
    {
      "block_name": "Main Test",
      "cycles": 1,
      "scheduled_events": [
        {
          "event": "Isolator On",
          "start": 0.0,
          "duration": 300.0
        },
        {
          "event": "Power Supply 1 On",
          "start": 50.0,
          "duration": 0.0
        }
      ]
    }
  ],
  "positions": [
    {
      "position": 1,
      "enabled": true,
      "isolator_gpio": 1,
      "dut_gpio": 21,
      "dut_offset_ms": 0.0
    }
  ],
  "auxiliary_outputs": [
    {
      "name": "Power Supply 1",
      "gpio": 15,
      "enabled": true
    }
  ],
  "isolator_waveform_points": [
    [0.0, 1],
    [300.0, 0]
  ],
  "dut_waveform_points": [
    [80.0, 1],
    [280.0, 0]
  ],
  "auxiliary_waveforms": {
    "Power Supply 1": [
      [0.0, 0],
      [50.0, 1],
      [280.0, 0]
    ]
  }
}
```

### Saving: Python Objects → JSON

```python
def _on_save_profile(self):
    # 1. Build Profile object from GUI
    profile = self._build_profile_object()
    
    # 2. Convert to dictionary
    data = asdict(profile)  # dataclasses magic!
    
    # 3. Convert nested objects
    data["blocks"] = [asdict(b) for b in profile.blocks]
    data["positions"] = [asdict(p) for p in profile.positions]
    
    # 4. Serialize to JSON text
    json_text = json.dumps(data, indent=2)
    
    # 5. Write to file
    with open(filepath, "w") as f:
        f.write(json_text)
```

### Loading: JSON → Python Objects

```python
def _on_load_profile(self):
    # 1. Read file
    with open(filepath, "r") as f:
        data = json.load(f)  # Parse JSON
    
    # 2. Extract basic settings
    self.profile_name.set(data["profile_name"])
    self.waveform_unit.set(data["waveform_time_units"])
    
    # 3. Load blocks
    for block_data in data["blocks"]:
        block_name = block_data["block_name"]
        cycles = block_data["cycles"]
        schedule = block_data["scheduled_events"]
        
        # Create block in GUI
        self._add_block(block_name, cycles)
        
        # Load schedule into block
        for event_data in schedule:
            self._add_schedule_row(
                event_data["event"],
                event_data["start"],
                event_data["duration"]
            )
    
    # 4. Load auxiliary outputs
    for aux_data in data.get("auxiliary_outputs", []):
        self._add_auxiliary_output(
            aux_data["name"],
            aux_data["gpio"],
            aux_data["enabled"]
        )
    
    # 5. Rebuild preview
    self._rebuild_and_preview()
```

### Backward Compatibility

**Problem**: Old files don't have `auxiliary_outputs` field.

**Solution**: Use `.get()` with default:

```python
# If "auxiliary_outputs" doesn't exist, use empty list
aux_list = data.get("auxiliary_outputs", [])
```

This lets old files load without errors!

---

## Common Patterns You'll See in the Code

### Pattern 1: The "Get from GUI" Pattern

**Purpose**: Extract data from Tkinter variables

```python
def _get_blocks(self) -> List[Block]:
    blocks = []
    for name_var, cycles_var, schedule_rows, _frame in self.blocks:
        # Read from Tkinter variables
        name = name_var.get()
        cycles = cycles_var.get()
        
        # Build schedule
        schedule = []
        for ev_var, st_var, du_var in schedule_rows:
            schedule.append(ScheduledEvent(
                ev_var.get(),
                st_var.get(),
                du_var.get()
            ))
        
        # Create Block object
        blocks.append(Block(name, cycles, schedule))
    
    return blocks
```

**Pattern**: Loop through stored widgets/variables, read values, build objects.

### Pattern 2: The "Closure for Remove" Pattern

**Purpose**: Create a remove button that knows which row to delete

```python
def _add_schedule_row(self, ...):
    row = tb.Frame(...)
    
    # This is a closure - it "captures" the `row` variable
    def remove():
        # Find this specific row
        for i, (_, _, _, frame) in enumerate(self.schedule_rows):
            if frame is row:  # Found it!
                self.schedule_rows.pop(i)
                break
        row.destroy()  # Remove from GUI
        self._rebuild_and_preview()
    
    tb.Button(row, text="Remove", command=remove).pack(...)
```

**Why this works**: Each row gets its own `remove()` function that remembers which row it belongs to.

### Pattern 3: The "Try-Except" Pattern

**Purpose**: Handle errors gracefully

```python
def _on_save_profile(self):
    try:
        profile = self._build_profile_object()
        # ... save code ...
    except Exception as e:
        messagebox.showerror("Save Error", str(e))
        return  # Stop here, don't continue
```

**Pattern**: Try to do something, catch errors, show user-friendly message.

### Pattern 4: The "List Comprehension" Pattern

**Purpose**: Transform one list into another

```python
# Long way:
result = []
for item in items:
    result.append(transform(item))

# Short way (list comprehension):
result = [transform(item) for item in items]

# Example:
waveform_points = [(float(t), int(s)) for t, s in waveform]
# Converts each tuple to (float, int) format
```

### Pattern 5: The "Destructuring" Pattern

**Purpose**: Unpack tuples into named variables

```python
# Tuple with 4 elements
row_data = (ev_var, st_var, du_var, frame)

# Destructure into 4 variables
ev_var, st_var, du_var, frame = row_data

# Can ignore elements with _
ev_var, st_var, du_var, _ = row_data  # Ignore frame
```

### Pattern 6: The "Optional Parameter with Default" Pattern

**Purpose**: Make parameters optional

```python
def _add_block(self, name: str = None, cycles: int = 1):
    if name is None:
        name = f"Block {len(self.blocks) + 1}"
    # ...

# Can call with or without arguments:
_add_block()  # Uses default name "Block 1"
_add_block("Custom Name")  # Uses provided name
_add_block("Test", 5)  # Name and cycles
```

---

## Walking Through a Complete Example

Let's trace what happens when you:
1. Create a simple profile
2. Save it
3. Send it to hardware

### Step 1: You Configure in GUI

You:
- Set profile name to "Test 1"
- Add block "Main" with 1 cycle
- Add event "Isolator On" at 0ms for 300ms
- Add event "Power Supply 1 On" at 50ms (duration 0)
- Add event "Power Supply 1 Off" at 280ms (duration 0)
- Enable position 1 (GPIO 1 for isolator, GPIO 21 for DUT)
- Configure auxiliary output "Power Supply 1" on GPIO 15

### Step 2: You Click "Rebuild"

The `_rebuild_and_preview()` function runs:

```python
def _rebuild_and_preview(self):
    # Extract from GUI
    unit = "ms"
    blocks = [
        Block(
            block_name="Main",
            cycles=1,
            scheduled_events=[
                ScheduledEvent("Isolator On", 0.0, 300.0),
                ScheduledEvent("Power Supply 1 On", 50.0, 0.0),
                ScheduledEvent("Power Supply 1 Off", 280.0, 0.0)
            ]
        )
    ]
    auxiliary_outputs = [
        AuxiliaryOutput("Power Supply 1", 15, True)
    ]
    
    # Call waveform engine
    iso_dig, dut_dig, iso_disp, dut_disp, ..., aux_waves = \
        build_waveforms_from_blocks(blocks, unit, auxiliary_outputs)
    
    # iso_dig is now: [(0.0, 1), (300.0, 0)]
    # dut_dig is now: [(0.0, 0)] (stays off in this example)
    # aux_waves is now: {"Power Supply 1": [(0.0, 0), (50.0, 1), (280.0, 0)]}
    
    # Generate preview (not shown here)
    # Plot it
    # Display it
```

### Step 3: You Click "Save"

The `_on_save_profile()` function runs:

```python
def _on_save_profile(self):
    # Build Profile object
    profile = Profile(
        profile_name="Test 1",
        waveform_time_units="ms",
        blocks=[Block(...)],
        isolator_waveform_points=[(0.0, 1), (300.0, 0)],
        dut_waveform_points=[(0.0, 0)],
        row_delay_ms=0.0,
        positions=[PositionConfig(1, True, 1, 21, 0.0)],
        auxiliary_outputs=[AuxiliaryOutput("Power Supply 1", 15, True)],
        auxiliary_waveforms={"Power Supply 1": [(0.0, 0), (50.0, 1), (280.0, 0)]}
    )
    
    # Convert to JSON
    data = asdict(profile)
    # ... nested conversions ...
    json_text = json.dumps(data, indent=2)
    
    # Write file
    with open("test1.json", "w") as f:
        f.write(json_text)
```

### Step 4: File is Created

`test1.json` now contains:
```json
{
  "profile_name": "Test 1",
  "blocks": [...],
  "isolator_waveform_points": [[0.0, 1], [300.0, 0]],
  "auxiliary_waveforms": {
    "Power Supply 1": [[0.0, 0], [50.0, 1], [280.0, 0]]
  },
  ...
}
```

### Step 5: You Click "Export to Pico"

```python
def _pico_export_current(self):
    # Build profile
    profile = self._build_profile_object()
    
    # Convert to JSON
    json_text = self._profile_to_json_text(profile)
    
    # Send over serial
    self.pico.send_file(
        self.pico_filename.get(),  # "profile.json"
        json_text
    )
```

The `PicoLink.send_file()` method:
1. Opens the serial port (USB connection)
2. Sends a "WRITE" command
3. Sends the filename
4. Sends the JSON text
5. Waits for acknowledgment

### Step 6: Pico Receives and Stores

The Pico firmware (in `pico_firmware/main.py`):
1. Receives the "WRITE" command
2. Receives the filename
3. Receives the JSON text
4. Writes it to flash storage

### Step 7: You Click "Run on Pico"

```python
def _pico_run(self):
    # Send "RUN" command over serial
    self.pico.send_command("RUN", self.pico_filename.get())
```

### Step 8: Pico Executes

The Pico firmware:
1. Receives "RUN" command
2. Reads "profile.json" from flash
3. Parses JSON into memory
4. Reads waveform points
5. **Executes in real-time**:
   - At 0ms: Set GPIO 1 HIGH (isolator on), GPIO 15 LOW (power supply off)
   - At 50ms: Set GPIO 15 HIGH (power supply on)
   - At 280ms: Set GPIO 15 LOW (power supply off)
   - At 300ms: Set GPIO 1 LOW (isolator off)
6. Repeats for all positions (with row delay)
7. Repeats for all cycles
8. Repeats for all blocks

### Step 9: Hardware Responds

Real GPIO pins on the Pico change state:
- Pin 1 controls a relay → Isolator turns on/off
- Pin 15 controls another relay → Power supply turns on/off
- Pin 21 controls test equipment → DUT signal changes

Your test runs **automatically** with **millisecond precision**!

---

## Why This Design?

### Separation of Concerns

**Concept**: Each file has one main job.

- `models.py`: Define data structures
- `waveform_engine.py`: Math and algorithms
- `waveform_profile_builder.py`: User interface
- `pico_serial.py`: Hardware communication

**Why?**: Easier to:
- Find bugs (know which file to check)
- Make changes (won't accidentally break other parts)
- Test (test each part independently)
- Understand (focus on one thing at a time)

### Data-Driven Design

**Concept**: Separate data from code.

Events are **data**:
```python
ScheduledEvent("Isolator On", 0.0, 300.0)
```

The waveform engine is **code** that processes any events you give it.

**Why?**: Flexibility! You can:
- Add new event types without changing the engine
- Save/load profiles (just save the data)
- Test with different data
- Share profiles between users

### Declarative vs Imperative

**Imperative** (telling computer HOW):
```python
for i in range(10):
    print(i)
```

**Declarative** (telling computer WHAT):
```python
@dataclass
class Profile:
    name: str
    blocks: List[Block]
```

The GUI and data models are **declarative** - you describe WHAT you want.
The waveform engine is **imperative** - it describes HOW to compute it.

**Why mix both?**: 
- Declarative: Easy to read, hard to mess up
- Imperative: Flexible, powerful for algorithms

### Event-Driven Architecture

**Concept**: Things happen in response to events.

- User clicks button → `_on_save_profile()` runs
- User types in text box → Variable updates
- Text box loses focus → `_rebuild_and_preview()` runs

**Why?**: GUIs are naturally event-driven. User actions are unpredictable, so code must respond to whatever happens.

---

## Advanced Concepts (For When You're Ready)

### Type Hints

```python
def build_waveforms_from_schedule(
    schedule: List[ScheduledEvent],
    unit: str,
    cycles: int = 1
) -> Tuple[List[Tuple[float, int]], ...]:
```

**What it means**:
- `schedule: List[ScheduledEvent]` - schedule is a list of ScheduledEvent objects
- `unit: str` - unit is a string
- `cycles: int = 1` - cycles is an integer, default 1
- `-> Tuple[...]` - function returns a tuple

**Why?**: Documentation + type checking (catch errors before running)

### Dataclasses

```python
@dataclass
class Block:
    block_name: str
    cycles: int
    scheduled_events: List[ScheduledEvent]
```

**Magic**: The `@dataclass` decorator automatically creates:
- `__init__()` - constructor
- `__repr__()` - string representation
- `__eq__()` - equality comparison

**Why?**: Less boilerplate code, fewer bugs.

### List Comprehensions with Conditionals

```python
# Get only enabled positions
enabled = [p for p in positions if p.enabled]

# Get names of auxiliary outputs
names = [aux.name for aux in auxiliary_outputs if aux.enabled]

# Transform and filter in one line
waveform = [(t + offset, s) for t, s in original if t < max_time]
```

### Lambda Functions

```python
# Regular function
def add_five(x):
    return x + 5

# Lambda (anonymous function)
add_five = lambda x: x + 5

# Use in sorting
sorted(items, key=lambda item: item.start)  # Sort by start time
```

### Generators (yield)

```python
def count_up_to(n):
    i = 0
    while i < n:
        yield i
        i += 1

# Only generates values as needed (memory efficient)
for num in count_up_to(1000000):
    print(num)
```

Not used much in this codebase, but common in Python.

---

## Common Debugging Techniques

### Print Debugging

**Simple but effective**:
```python
def _rebuild_and_preview(self):
    print(f"DEBUG: unit = {self.waveform_unit.get()}")
    print(f"DEBUG: num blocks = {len(self.blocks)}")
    
    blocks = self._get_blocks()
    print(f"DEBUG: blocks = {blocks}")
    
    # ... rest of code
```

### Checking Types

```python
print(f"Type of waveform: {type(waveform)}")
print(f"Length: {len(waveform)}")
print(f"First element: {waveform[0]}")
```

### Try-Except for Details

```python
try:
    result = risky_operation()
except Exception as e:
    print(f"Error: {e}")
    print(f"Type: {type(e)}")
    import traceback
    traceback.print_exc()  # Full error details
```

### Assertions

```python
def build_waveform(schedule):
    assert len(schedule) > 0, "Schedule cannot be empty!"
    assert all(e.start >= 0 for e in schedule), "All start times must be >= 0"
    # ... rest of code
```

---

## Next Steps: Where to Go from Here

### To Understand More

1. **Read Python Tutorial**: https://docs.python.org/3/tutorial/
2. **Learn Tkinter**: https://realpython.com/python-gui-tkinter/
3. **Practice with Dataclasses**: Try creating your own
4. **Study the waveform engine**: It's the most complex part

### To Modify the Code

Start with small changes:
1. **Add a new event type**: Add it to `EVENTS` in `models.py`
2. **Change default GPIO pins**: Edit `config.py`
3. **Add a GUI element**: Follow the patterns in `_build_layout()`
4. **Add validation**: Check user inputs in `_rebuild_and_preview()`

### To Extend the System

Ideas:
1. **Add event validation**: Check for conflicts (e.g., DUT on before isolator)
2. **Add waveform export**: Save waveforms as CSV for analysis
3. **Add templates**: Pre-built profiles for common tests
4. **Add a wizard**: Step-by-step guide for new users
5. **Add visualization**: Show auxiliary outputs in preview

---

## Glossary of Terms

**Auxiliary Output**: A custom-defined GPIO output (power supply, relay, etc.)

**Block**: A test phase with its own schedule and cycle count

**Cycle**: One complete execution of a block's schedule

**Dataclass**: A Python class decorator that auto-generates methods

**DUT**: Device Under Test - the product being tested

**Event**: A scheduled action (e.g., "Isolator On")

**GPIO**: General Purpose Input/Output - a pin on the microcontroller

**GUI**: Graphical User Interface - what you see and interact with

**Isolator**: A safety device that isolates power to a test station

**JSON**: JavaScript Object Notation - a text format for data

**Lambda**: An anonymous function (small inline function)

**Pico**: Raspberry Pi Pico - a microcontroller board

**Position**: A test station in a multi-position test setup

**Profile**: A complete test configuration

**Ramp**: A smooth transition from one state to another

**Row Delay**: Time offset between starting different test positions

**Schedule**: A list of events with their timing

**Serial Port**: A communication connection (usually USB)

**State**: The current value of a signal (HIGH/LOW, ON/OFF, 0/1)

**Tkinter**: Python's built-in GUI library

**Tuple**: An immutable sequence (can't be changed after creation)

**Waveform**: A time-series of state changes

**Widget**: A GUI element (button, text box, label, etc.)

---

## Questions to Test Your Understanding

1. **What's the difference between an Event and a Waveform?**
   - Answer: Events are human-friendly descriptions; waveforms are machine-ready instructions.

2. **Why use Blocks instead of just one long schedule?**
   - Answer: To repeat different phases different numbers of times without duplicating events.

3. **What does "last start wins" mean?**
   - Answer: When events overlap, the one that starts later takes priority.

4. **Why separate models.py from waveform_engine.py?**
   - Answer: Separation of concerns - data structures vs. algorithms.

5. **What's the purpose of Tkinter Variables?**
   - Answer: Live connection between GUI widgets and Python code.

6. **How does the GUI know when to rebuild the preview?**
   - Answer: Event binding - functions are called when widgets change.

7. **Why use JSON instead of a custom format?**
   - Answer: Universal, human-readable, easy to parse.

8. **What's a closure and why use it for Remove buttons?**
   - Answer: A function that "remembers" its context; lets each button know which row to remove.

9. **Why return a tuple from build_waveforms_from_blocks()?**
   - Answer: To return multiple values (isolator waveform, DUT waveform, auxiliary waveforms, etc.).

10. **What's the advantage of the dataclass decorator?**
    - Answer: Automatically generates boilerplate code (constructor, repr, etc.).

---

## Final Thoughts

This codebase is well-structured and follows good practices:
- **Modular**: Each file has a clear purpose
- **Readable**: Good variable names, comments, docstrings
- **Testable**: Logic separated from GUI
- **Maintainable**: Easy to modify and extend

The best way to learn is to:
1. **Read the code** - Start with `models.py`, then `waveform_engine.py`
2. **Trace execution** - Add print statements to follow the flow
3. **Make small changes** - Try adding a simple feature
4. **Break things** - Intentionally cause errors to see what happens
5. **Ask questions** - Research concepts you don't understand

Remember: **Everyone was a beginner once**. Programming is a skill learned through practice, not innate talent. Keep exploring, keep experimenting, and keep learning!

---

**Good luck on your learning journey!** 🚀
