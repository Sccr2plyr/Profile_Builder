"""
Waveform Profile Builder - Main GUI Application
================================================
A comprehensive graphical user interface for building, visualizing, and deploying
multi-position waveform test profiles to Raspberry Pi Pico hardware.

This application provides:
    - Visual waveform builder with overlapping event support
    - Real-time multi-channel waveform preview with matplotlib
    - Multi-position configuration with independent GPIO control
    - Profile save/load functionality (JSON format)
    - Serial communication with Pico hardware
    - Non-blocking execution with pause/resume/stop controls

Requirements:
    pip install pyserial ttkbootstrap matplotlib

Architecture:
    - models.py: Data structures (Profile, PositionConfig, ScheduledEvent)
    - waveform_engine.py: Waveform generation algorithms
    - pico_serial.py: Serial communication with Pico
    - utils.py: Helper functions
    - waveform_profile_builder.py (this file): GUI implementation

Usage:
    python waveform_profile_builder.py

Features:
    - Overlapping events with "last start wins" logic
    - Visual rise/fall time display (ramps)
    - Row delay for sequential position activation
    - DUT offset for phase shifting per position
    - Cycle Delay is automatically skipped on the final cycle
    - Background thread execution keeps GUI responsive

Author: Profile Builder Team
Version: 2.0 (Modularized)
Date: January 2026
"""

# ----------------------------
# Standard Library Imports
# ----------------------------
import json
import threading
import queue
import time
from dataclasses import asdict
from typing import List, Dict, Tuple, Optional

# ----------------------------
# Third-Party GUI Imports
# ----------------------------
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame

# ----------------------------
# Matplotlib Imports (for waveform visualization)
# ----------------------------
import matplotlib
matplotlib.use("TkAgg")  # Use TkAgg backend for embedding in Tkinter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# ----------------------------
# Local Module Imports
# ----------------------------
from models import (
    Profile, PositionConfig, ScheduledEvent, Block,
    EVENTS, UNIT_TO_MS
)
from waveform_engine import build_waveforms_from_schedule, build_waveforms_from_blocks, build_preview_channels
from pico_serial import PicoLink





# ================================
# Main GUI Application Class
# ================================

class ProfileBuilderApp(tb.Window):
    """
    Main application window for the Waveform Profile Builder.
    
    This class implements a comprehensive GUI for:
    - Building waveform schedules with visual timeline editor
    - Configuring multiple test positions with GPIO mapping
    - Previewing waveforms in real-time with matplotlib
    - Saving/loading profiles to/from JSON files
    - Serial communication with Pico hardware
    - Running profiles with pause/resume/stop controls
    
    The GUI is organized into three main sections:
    1. Left panel: Schedule builder, position config, and Pico controls
    2. Right panel: Live waveform preview
    3. Top bar: Profile settings and file operations
    
    Architecture:
        - All GUI elements are built in _build_layout()
        - Waveform generation uses waveform_engine module
        - Serial communication uses PicoLink from pico_serial module
        - Background thread for non-blocking Pico execution
        - Event-driven updates for responsive UI
    
    Attributes:
        num_positions (int): Number of test positions (default: 10)
        default_isolator_gpios (List[int]): Default GPIO pins for isolators
        default_dut_gpios (List[int]): Default GPIO pins for DUTs
        
        Profile configuration variables (tk.StringVar, tk.DoubleVar, etc.):
            - profile_name: Name of the current profile
            - waveform_unit: Time unit for waveform events
            - row_delay_ms: Delay between positions
            - cycles_var: Number of waveform cycles
        
        Waveform data (computed by waveform_engine):
            - iso_digital/dut_digital: Step waveforms for hardware
            - iso_display/dut_display: Display waveforms with ramps
            - iso_has_ramps/dut_has_ramps: Flags for ramp visualization
            - cycle_length_ms: Length of one cycle
        
        Position configuration lists:
            - pos_enabled_vars: Enable/disable flags for positions
            - pos_iso_gpio_vars: Isolator GPIO assignments
            - pos_dut_gpio_vars: DUT GPIO assignments
            - pos_offset_vars: DUT time offsets
        
        Pico communication:
            - pico: PicoLink instance for serial communication
            - pico_port/pico_baud/pico_filename: Connection settings
            - pico_status: Status message for user display
            - _pico_q: Queue for background thread communication
            - _pico_run_thread: Background execution thread
            - _pico_is_running/_pico_is_paused: Execution state flags
    """
    
    def __init__(self):
        """
        Initialize the Profile Builder application.
        
        This method:
        1. Creates the main window with ttkbootstrap theme
        2. Initializes all data structures and variables
        3. Builds the complete GUI layout
        4. Sets up default position configurations
        5. Loads a starter example for demonstration
        6. Generates initial preview
        """
        # Load saved theme preference or use default
        import os
        theme_file = os.path.join(os.path.dirname(__file__), ".theme_preference")
        saved_theme = "flatly"
        if os.path.exists(theme_file):
            try:
                with open(theme_file, "r") as f:
                    saved_theme = f.read().strip() or "flatly"
            except:
                pass
        
        # Initialize the themed window
        super().__init__(themename=saved_theme)
        self.title("Position Profile Builder")
        self.geometry("1450x900")
        
        # Save theme on close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # ----------------------------
        # Position Configuration
        # ----------------------------
        self.num_positions = 10
        # Default GPIO mappings (1-10 for isolators, 21-30 for DUTs)
        self.default_isolator_gpios = list(range(1, self.num_positions + 1))
        self.default_dut_gpios = list(range(21, 21 + self.num_positions))
        
        # ----------------------------
        # Profile Settings (Tkinter Variables)
        # ----------------------------
        # These variables are bound to GUI widgets and trigger updates on change
        self.profile_name = tk.StringVar(value="New Profile")
        self.waveform_unit = tk.StringVar(value="ms")  # Time unit: ms, sec, or min
        self.row_delay_ms = tk.DoubleVar(value=0.0)    # Delay between positions
        self.preview_mode = tk.StringVar(value="All Blocks")  # Preview mode: "All Blocks" or "Current Block"
        
        # ----------------------------
        # Block Management
        # ----------------------------
        # List of blocks: each entry is (block_name_var, cycles_var, schedule_rows_list, block_frame)
        self.blocks: List[Tuple[tk.StringVar, tk.IntVar, List, tb.Frame]] = []
        self.current_block_index = 0  # Index of the currently displayed/edited block
        
        # ----------------------------
        # Schedule Data (for current block)
        # ----------------------------
        # List of scheduled event rows: (event_var, start_var, duration_var, frame_widget)
        self.schedule_rows: List[Tuple[tk.StringVar, tk.DoubleVar, tk.DoubleVar, tb.Frame]] = []
        
        # ----------------------------
        # Waveform Data (computed by waveform_engine)
        # ----------------------------
        # Digital waveforms (for hardware): list of (time_ms, state) tuples
        self.iso_digital: List[Tuple[float, int]] = []
        self.dut_digital: List[Tuple[float, int]] = []
        
        # Display waveforms (for visualization): list of (time_ms, value) tuples
        self.iso_display: List[Tuple[float, float]] = []
        self.dut_display: List[Tuple[float, float]] = []
        
        # Flags indicating if ramps exist (for choosing plot style)
        self.iso_has_ramps = False
        self.dut_has_ramps = False
        
        # Total waveform length and block boundaries
        self.total_length_ms = 0.0
        self.block_end_times: List[float] = []  # Time points where blocks end
        
        # ----------------------------
        # Position Configuration Variables
        # ----------------------------
        # These lists hold Tkinter variables for each position's settings
        self.pos_enabled_vars: List[tk.BooleanVar] = []      # Enabled checkboxes
        self.pos_iso_gpio_vars: List[tk.IntVar] = []         # Isolator GPIO pins
        self.pos_dut_gpio_vars: List[tk.IntVar] = []         # DUT GPIO pins
        self.pos_offset_vars: List[tk.DoubleVar] = []        # DUT time offsets
        
        # ----------------------------
        # Auxiliary Outputs Configuration
        # ----------------------------
        # List of auxiliary outputs: (name_var, gpio_var, enabled_var, frame)
        self.auxiliary_outputs: List[Tuple[tk.StringVar, tk.IntVar, tk.BooleanVar, tb.Frame]] = []
        
        # ----------------------------
        # Pico Serial Communication
        # ----------------------------
        self.pico = PicoLink()                                  # Serial communication handler
        self.pico_port = tk.StringVar(value="/dev/ttyACM0")   # COM port (Linux default)
        self.pico_baud = tk.IntVar(value=115200)               # Baud rate
        self.pico_status = tk.StringVar(value="Pico: Disconnected")  # Status message
        self.pico_filename = tk.StringVar(value="profile.json")      # Filename on Pico
        
        # Background thread management for non-blocking execution
        self._pico_q = queue.Queue()                          # Queue for thread communication
        self._pico_run_thread: Optional[threading.Thread] = None  # Execution thread
        self._pico_is_running = False                         # Execution state
        self._pico_is_paused = False                          # Pause state
        
        # ----------------------------
        # Build GUI and Initialize
        # ----------------------------
        self._build_layout()         # Create all GUI widgets
        self._init_positions()       # Initialize position configuration widgets
        self._init_auxiliary_outputs()  # Initialize auxiliary outputs with defaults
        
        # Create a default block with starter example
        self._add_block("Main Test", cycles=1)
        self._switch_to_block(0)
        
        # Add starter events to the first block
        self._add_schedule_row("Isolator On", 0, 300)
        self._add_schedule_row("DUT Hold Time", 80, 200)
        self._add_schedule_row("DUT Off Time", 280, 120)
        self._add_schedule_row("Cycle Delay", 400, 200)
        
        # Generate initial preview
        self._rebuild_and_preview()

    def _build_layout(self):
        """
        Construct the complete GUI layout.
        
        This method creates all widgets and organizes them into a three-section layout:
        
        1. Top Bar:
           - Profile name entry
           - Time unit selector (ms, sec, min)
           - Cycles count
           - Load/Save buttons
        
        2. Left Panel (scrollable):
           - Pico connection controls (COM port, baud rate)
           - Pico command buttons (Connect, Ping, Export, Run, Pause, Resume, Stop)
           - Waveform schedule builder (scrollable event list)
           - Position configuration (row delay, GPIO assignments)
        
        3. Right Panel:
           - Summary text (units, cycles, enabled positions)
           - matplotlib canvas for waveform preview
        
        Layout Structure:
            Window
            ├── top (Frame): Profile settings and file operations
            ├── mid (PanedWindow): Horizontal split
            │   ├── left (Frame): Controls and configuration
            │   │   ├── pico_box: Serial communication controls
            │   │   ├── sched_box: Waveform schedule builder
            │   │   ├── apply_box: Cross-position settings
            │   │   └── pos_frame: Position configuration grid
            │   └── right (Frame): Waveform preview
            │       ├── summary_lbl: Text summary
            │       └── canvas: matplotlib figure
        
        All widgets are stored as instance attributes for later access and updates.
        Event bindings are configured to trigger waveform rebuilds on value changes.
        """
        # ===========================
        # Top Bar - Profile Settings
        # ===========================
        top = tb.Frame(self, padding=10)
        top.pack(side=TOP, fill=X)

        # Profile name entry field
        tb.Label(top, text="Profile Name:").pack(side=LEFT)
        tb.Entry(top, textvariable=self.profile_name, width=25).pack(side=LEFT, padx=(5, 15))

        # Time unit selector - triggers preview rebuild on change
        tb.Label(top, text="Units:").pack(side=LEFT)
        unit_combo = tb.Combobox(top, textvariable=self.waveform_unit, values=["ms", "sec", "min"], width=6, state="readonly")
        unit_combo.pack(side=LEFT, padx=(5, 15))
        unit_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_and_preview())

        # Preview mode selector
        tb.Label(top, text="Preview:").pack(side=LEFT)
        preview_combo = tb.Combobox(top, textvariable=self.preview_mode, values=["All Blocks", "Current Block"], width=12, state="readonly")
        preview_combo.pack(side=LEFT, padx=(5, 15))
        preview_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_and_preview())

        # Current block indicator
        self.current_block_label = tb.Label(top, text="Block: None", font=("Arial", 10, "bold"))
        self.current_block_label.pack(side=LEFT, padx=(15, 15))

        # File operation buttons
        tb.Button(top, text="Load Profile JSON", bootstyle=PRIMARY, command=self._on_load_profile).pack(side=LEFT)
        tb.Button(top, text="Save Profile JSON", bootstyle=SUCCESS, command=self._on_save_profile).pack(side=LEFT, padx=(10, 0))

        # ===========================
        # Main Content Area - Horizontal Split
        # ===========================
        mid = tb.Panedwindow(self, orient=HORIZONTAL)
        mid.pack(fill=BOTH, expand=YES)

        # Left panel container (wrapper for PanedWindow compatibility)
        left_container = tb.Frame(mid)
        
        # Scrollable frame inside the container
        left_scroll = ScrolledFrame(left_container, autohide=True)
        left_scroll.pack(fill=BOTH, expand=YES)
        left = left_scroll  # For compatibility with existing code
        
        # Right panel for preview visualization
        right = tb.Frame(mid, padding=10)
        
        # Add panels to the paned window (resizable divider)
        mid.add(left_container, weight=1)   # Left takes 1/3 of space
        mid.add(right, weight=2)  # Right takes 2/3 of space

        # ===========================
        # Pico Control Panel
        # ===========================
        pico_box = tb.Labelframe(left, text="Pico (Export + Run)", padding=10)
        pico_box.pack(fill=X, pady=(0, 10))

        # Row 1: COM port and baud rate entry
        row1 = tb.Frame(pico_box)
        row1.pack(fill=X, pady=2)
        tb.Label(row1, text="COM Port:", width=12, anchor=W).pack(side=LEFT)
        tb.Entry(row1, textvariable=self.pico_port, width=10).pack(side=LEFT, padx=(0, 8))
        tb.Label(row1, text="Baud:", width=6, anchor=W).pack(side=LEFT)
        tb.Entry(row1, textvariable=self.pico_baud, width=8).pack(side=LEFT)

        # Row 2: Filename on Pico
        row2 = tb.Frame(pico_box)
        row2.pack(fill=X, pady=2)
        tb.Label(row2, text="File on Pico:", width=12, anchor=W).pack(side=LEFT)
        tb.Entry(row2, textvariable=self.pico_filename, width=18).pack(side=LEFT)

        # Row 3: Command buttons (stored for state management)
        row3 = tb.Frame(pico_box)
        row3.pack(fill=X, pady=(6, 2))
        
        # Connection and status buttons
        self.btn_connect = tb.Button(row3, text="Connect", command=self._pico_connect)
        self.btn_connect.pack(side=LEFT)
        self.btn_ping = tb.Button(row3, text="Ping", command=self._pico_ping)
        self.btn_ping.pack(side=LEFT, padx=(6, 0))
        
        # Profile upload and execution buttons
        self.btn_export = tb.Button(row3, text="Export to Pico", bootstyle=SUCCESS, command=self._pico_export_current)
        self.btn_export.pack(side=LEFT, padx=(12, 0))
        self.btn_run = tb.Button(row3, text="Run on Pico", bootstyle=PRIMARY, command=self._pico_run)
        self.btn_run.pack(side=LEFT, padx=(6, 0))
        
        # Execution control buttons
        self.btn_pause = tb.Button(row3, text="Pause", bootstyle=WARNING, command=self._pico_pause)
        self.btn_pause.pack(side=LEFT, padx=(6, 0))
        self.btn_resume = tb.Button(row3, text="Resume", bootstyle=INFO, command=self._pico_resume)
        self.btn_resume.pack(side=LEFT, padx=(6, 0))
        self.btn_stop = tb.Button(row3, text="Stop", bootstyle=DANGER, command=self._pico_stop)
        self.btn_stop.pack(side=LEFT, padx=(6, 0))

        # Status label
        tb.Label(pico_box, textvariable=self.pico_status).pack(anchor=W, pady=(6, 0))

        # ===========================
        # Block Management Panel
        # ===========================
        block_mgmt_box = tb.Labelframe(left, text="Test Blocks (Sequential Execution)", padding=10)
        block_mgmt_box.pack(fill=X, pady=(0, 10))

        # Instructions
        inst_label = tb.Label(block_mgmt_box, text="Blocks execute in order. Each has independent cycles.", 
                              font=("Arial", 8), foreground="gray")
        inst_label.pack(anchor=W, pady=(0, 5))

        # Block list container with scrollbar
        self.block_list_scroll = ScrolledFrame(block_mgmt_box, autohide=True, height=120)
        self.block_list_scroll.pack(fill=BOTH, expand=YES, pady=(0, 5))
        
        self.block_list_container = tb.Frame(self.block_list_scroll)
        self.block_list_container.pack(fill=BOTH, expand=YES)

        # Block management buttons
        block_btn_frame = tb.Frame(block_mgmt_box)
        block_btn_frame.pack(fill=X)
        tb.Button(block_btn_frame, text="+ Add Block", bootstyle=SUCCESS, command=self._on_add_block).pack(side=LEFT, padx=(0, 5))
        tb.Button(block_btn_frame, text="Remove Block", bootstyle=DANGER, command=self._on_remove_current_block).pack(side=LEFT, padx=(0, 5))
        tb.Button(block_btn_frame, text="Move Up", bootstyle=SECONDARY, command=self._on_move_block_up).pack(side=LEFT, padx=(0, 5))
        tb.Button(block_btn_frame, text="Move Down", bootstyle=SECONDARY, command=self._on_move_block_down).pack(side=LEFT)

        # ===========================
        # Waveform Schedule Builder (for current block)
        # ===========================
        sched_box = tb.Labelframe(left, text="Current Block Waveform", padding=10)
        sched_box.pack(fill=X, pady=(0, 10))

        # Column headers for schedule entries
        header = tb.Frame(sched_box)
        header.pack(fill=X)
        tb.Label(header, text="Event", width=22).pack(side=LEFT)
        tb.Label(header, text="Start", width=10).pack(side=LEFT)
        tb.Label(header, text="Duration", width=10).pack(side=LEFT)

        # Scrollable container for schedule rows (allows many events)
        self.sched_scroll = ScrolledFrame(sched_box, autohide=True, height=260)
        self.sched_scroll.pack(fill=BOTH, expand=YES, pady=(6, 0))

        # Container frame inside scroll area
        self.sched_container = tb.Frame(self.sched_scroll)
        self.sched_container.pack(fill=BOTH, expand=YES)

        # Add/Rebuild buttons
        btns = tb.Frame(sched_box)
        btns.pack(fill=X, pady=(10, 0))
        tb.Button(btns, text="+ Add block", command=self._add_schedule_row).pack(side=LEFT)
        tb.Button(btns, text="Rebuild", command=self._rebuild_and_preview).pack(side=LEFT, padx=(10, 0))

        # ===========================
        # Cross-Position Settings
        # ===========================
        apply_box = tb.Labelframe(left, text="Apply Across Positions", padding=10)
        apply_box.pack(fill=X, pady=(0, 10))
        self._labeled_entry(apply_box, "Row delay between positions (ms):", self.row_delay_ms)

        # ===========================
        # Auxiliary Outputs Configuration
        # ===========================
        aux_box = tb.Labelframe(left, text="Auxiliary Outputs (Power Supplies, Relays, etc.)", padding=10)
        aux_box.pack(fill=X, pady=(0, 10))
        
        # Instructions
        inst_label = tb.Label(aux_box, text="Define named outputs. Each generates '{Name} On' and '{Name} Off' events.",
                              font=("Arial", 8), foreground="gray")
        inst_label.pack(anchor=W, pady=(0, 5))
        
        # Column headers
        aux_header = tb.Frame(aux_box)
        aux_header.pack(fill=X, pady=(0, 4))
        tb.Label(aux_header, text="Enabled", width=8).pack(side=LEFT)
        tb.Label(aux_header, text="Name", width=20).pack(side=LEFT)
        tb.Label(aux_header, text="GPIO", width=8).pack(side=LEFT)
        
        # Scrollable container for auxiliary output rows
        self.aux_scroll = ScrolledFrame(aux_box, autohide=True, height=100)
        self.aux_scroll.pack(fill=BOTH, expand=YES, pady=(0, 5))
        
        self.aux_container = tb.Frame(self.aux_scroll)
        self.aux_container.pack(fill=BOTH, expand=YES)
        
        # Add/Remove buttons
        aux_btn_frame = tb.Frame(aux_box)
        aux_btn_frame.pack(fill=X)
        tb.Button(aux_btn_frame, text="+ Add Output", bootstyle=SUCCESS, command=self._add_auxiliary_output).pack(side=LEFT, padx=(0, 5))
        tb.Button(aux_btn_frame, text="- Remove", bootstyle=DANGER, command=self._remove_last_auxiliary_output).pack(side=LEFT)

        # ===========================
        # Position Configuration Grid
        # ===========================
        pos_frame = tb.Labelframe(left, text="Positions", padding=10)
        pos_frame.pack(fill=BOTH, expand=YES)

        # Scrollable container for position rows
        self.pos_scroll = ScrolledFrame(pos_frame, autohide=True)
        self.pos_scroll.pack(fill=BOTH, expand=YES)

        # Column headers for position configuration
        pheader = tb.Frame(self.pos_scroll)
        pheader.pack(fill=X, pady=(0, 4))
        for txt, w in [("Use", 5), ("Pos", 5), ("Isolator GPIO", 12), ("DUT GPIO", 10), ("DUT Offset (ms)", 13)]:
            tb.Label(pheader, text=txt, width=w).pack(side=LEFT)

        # Container for position rows (populated by _init_positions)
        self.pos_rows_container = tb.Frame(self.pos_scroll)
        self.pos_rows_container.pack(fill=BOTH, expand=YES)

        # ===========================
        # Waveform Preview Panel
        # ===========================
        preview_box = tb.Labelframe(right, text="Preview", padding=10)
        preview_box.pack(fill=BOTH, expand=YES)

        # Summary text label
        self.summary_lbl = tb.Label(preview_box, text="", justify=LEFT)
        self.summary_lbl.pack(anchor=W, pady=(0, 8))

        # matplotlib figure for waveform visualization
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.grid(True)

        # Embed matplotlib canvas in Tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=preview_box)
        self.canvas.get_tk_widget().pack(fill=BOTH, expand=YES)

        # Initialize button states based on connection status
        self._update_pico_button_states()

    def _update_pico_button_states(self):
        """
        Update the enabled/disabled state of Pico control buttons.
        
        Button states depend on:
        - Connection status (connected vs. disconnected)
        - Execution status (running vs. idle)
        - Pause status (paused vs. active)
        
        State Logic:
            - Connect: Enabled when not running
            - Ping: Enabled when connected and not running
            - Export: Enabled when connected and not running
            - Run: Enabled when connected and not running
            - Pause: Enabled when connected, running, and not paused
            - Resume: Enabled when connected, running, and paused
            - Stop: Enabled when connected and running
        
        This method is called after every Pico operation to keep the UI
        synchronized with the actual system state.
        """
        connected = bool(self.pico.ser and self.pico.ser.is_open)
        running = self._pico_is_running
        paused = self._pico_is_paused

        # Update button states based on current system state
        self.btn_connect.config(state=("normal" if not running else "disabled"))
        self.btn_ping.config(state=("normal" if connected and not running else "disabled"))
        self.btn_export.config(state=("normal" if connected and not running else "disabled"))
        self.btn_run.config(state=("normal" if connected and not running else "disabled"))
        self.btn_pause.config(state=("normal" if connected and running and not paused else "disabled"))
        self.btn_resume.config(state=("normal" if connected and running and paused else "disabled"))
        self.btn_stop.config(state=("normal" if connected and running else "disabled"))

    def _labeled_entry(self, parent, label, var):
        """
        Create a labeled entry widget with auto-rebuild on value change.
        
        This helper creates a consistent layout for labeled numeric entries
        throughout the application. All entries created with this method
        automatically trigger waveform rebuild when changed.
        
        Args:
            parent: Parent widget to contain the labeled entry
            label (str): Label text to display
            var: Tkinter variable bound to the entry widget
        
        Events:
            - FocusOut: Rebuilds waveform when user leaves the field
            - Return: Rebuilds waveform when user presses Enter
        """
        r = tb.Frame(parent)
        r.pack(fill=X, pady=2)
        tb.Label(r, text=label, width=35, anchor=W).pack(side=LEFT)
        e = tb.Entry(r, textvariable=var, width=10)
        e.pack(side=LEFT)
        
        # Bind events for automatic preview updates
        e.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        e.bind("<Return>", lambda _e: self._rebuild_and_preview())

    def _add_schedule_row(self, default_event: str = None, start: float = 0.0, duration: float = 0.0):
        """
        Add a new waveform event row to the schedule builder.
        
        Creates a row with:
        - Event type dropdown (combobox)
        - Start time entry
        - Duration entry
        - Remove button
        
        All widgets are bound to automatically trigger waveform rebuild on change.
        
        Args:
            default_event (str, optional): Initial event type. Defaults to first event in EVENTS list
            start (float, optional): Initial start time. Defaults to 0.0
            duration (float, optional): Initial duration. Defaults to 0.0
        
        The row is stored in self.schedule_rows for later access and deletion.
        """
        # Get available events (base + auxiliary)
        available_events = self._get_available_events()
        
        # Create Tkinter variables for this row
        ev_var = tk.StringVar(value=default_event or available_events[0] if available_events else EVENTS[0])
        st_var = tk.DoubleVar(value=float(start))
        du_var = tk.DoubleVar(value=float(duration))

        # Create the row frame
        row = tb.Frame(self.sched_container)
        row.pack(fill=X, pady=2)

        # Event type dropdown
        cb = tb.Combobox(row, textvariable=ev_var, values=available_events, state="readonly", width=22)
        cb.pack(side=LEFT)

        # Start time entry
        st = tb.Entry(row, textvariable=st_var, width=10)
        st.pack(side=LEFT, padx=(6, 0))

        # Duration entry
        du = tb.Entry(row, textvariable=du_var, width=10)
        du.pack(side=LEFT, padx=(6, 0))

        def remove():
            """Remove this row from the schedule and rebuild waveforms."""
            # Find and remove this row from the list
            for i, (_a, _b, _c, frame) in enumerate(self.schedule_rows):
                if frame is row:
                    self.schedule_rows.pop(i)
                    break
            row.destroy()
            self._rebuild_and_preview()

        # Remove button
        tb.Button(row, text="Remove", bootstyle=SECONDARY, command=remove).pack(side=LEFT, padx=(10, 0))

        # Bind change events to trigger waveform rebuild
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_and_preview())
        st.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        du.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        st.bind("<Return>", lambda _e: self._rebuild_and_preview())
        du.bind("<Return>", lambda _e: self._rebuild_and_preview())

        # Store row data for later access
        self.schedule_rows.append((ev_var, st_var, du_var, row))

    def _clear_schedule_rows(self):
        """
        Remove all schedule rows from the GUI.
        
        Used when loading a profile from file to clear existing schedule
        before populating with loaded data.
        """
        for _ev_var, _st_var, _du_var, frame in self.schedule_rows:
            frame.destroy()
        self.schedule_rows.clear()

    def _init_positions(self):
        """
        Initialize position configuration widgets.
        
        Creates a row for each position (default: 10) with:
        - Enable checkbox
        - Position number label
        - Isolator GPIO entry
        - DUT GPIO entry
        - DUT offset entry
        
        Default Configuration:
            - First 3 positions enabled
            - Isolator GPIOs: 1-10
            - DUT GPIOs: 21-30
            - All offsets: 0.0 ms
        
        All entries are bound to trigger waveform rebuild on change.
        """
        # Clear any existing position widgets
        for w in self.pos_rows_container.winfo_children():
            w.destroy()

        # Clear variable lists
        self.pos_enabled_vars.clear()
        self.pos_iso_gpio_vars.clear()
        self.pos_dut_gpio_vars.clear()
        self.pos_offset_vars.clear()

        # Create a row for each position
        for i in range(self.num_positions):
            pos = i + 1
            
            # Create Tkinter variables with default values
            enabled = tk.BooleanVar(value=(pos <= 3))  # Enable first 3 positions by default
            iso_gpio = tk.IntVar(value=self.default_isolator_gpios[i] if i < len(self.default_isolator_gpios) else (i + 1))
            dut_gpio = tk.IntVar(value=self.default_dut_gpios[i] if i < len(self.default_dut_gpios) else (21 + i))
            offset = tk.DoubleVar(value=0.0)

            # Store variables for later access
            self.pos_enabled_vars.append(enabled)
            self.pos_iso_gpio_vars.append(iso_gpio)
            self.pos_dut_gpio_vars.append(dut_gpio)
            self.pos_offset_vars.append(offset)

            # Create row frame
            row = tb.Frame(self.pos_rows_container)
            row.pack(fill=X, pady=1)

            # Enable checkbox
            tb.Checkbutton(row, variable=enabled, command=self._rebuild_and_preview, width=5).pack(side=LEFT)
            
            # Position number label
            tb.Label(row, text=str(pos), width=5).pack(side=LEFT)

            # Entry fields for GPIO pins and offset
            for var, wcol in [(iso_gpio, 12), (dut_gpio, 10), (offset, 13)]:
                e = tb.Entry(row, textvariable=var, width=wcol)
                e.pack(side=LEFT)
                
                # Bind events for automatic preview updates
                e.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
                e.bind("<Return>", lambda _e: self._rebuild_and_preview())

    def _get_positions(self) -> List[PositionConfig]:
        """
        Extract position configurations from GUI widgets.
        
        Returns:
            List[PositionConfig]: List of all position configurations
                                  (both enabled and disabled)
        
        This method reads all Tkinter variables and converts them to
        PositionConfig objects for use in profile generation.
        """
        out: List[PositionConfig] = []
        for i in range(self.num_positions):
            out.append(
                PositionConfig(
                    position=i + 1,
                    enabled=bool(self.pos_enabled_vars[i].get()),
                    isolator_gpio=int(self.pos_iso_gpio_vars[i].get()),
                    dut_gpio=int(self.pos_dut_gpio_vars[i].get()),
                    dut_offset_ms=float(self.pos_offset_vars[i].get()),
                )
            )
        return out

    def _get_schedule(self) -> List[ScheduledEvent]:
        """
        Extract scheduled events from GUI widgets.
        
        Returns:
            List[ScheduledEvent]: List of all scheduled waveform events
        
        This method reads all schedule row variables and converts them
        to ScheduledEvent objects for waveform generation.
        """
        events: List[ScheduledEvent] = []
        for ev_var, st_var, du_var, _frame in self.schedule_rows:
            events.append(ScheduledEvent(ev_var.get(), float(st_var.get()), float(du_var.get())))
        return events

    # ===========================
    # Auxiliary Output Management Methods
    # ===========================

    def _init_auxiliary_outputs(self):
        """
        Initialize auxiliary outputs with defaults from config.
        
        Creates auxiliary output rows for each default output defined
        in config.DEFAULT_AUXILIARY_OUTPUTS.
        """
        from config import DEFAULT_AUXILIARY_OUTPUTS
        
        # Clear any existing auxiliary widgets
        for _name_var, _gpio_var, _enabled_var, frame in self.auxiliary_outputs:
            frame.destroy()
        self.auxiliary_outputs.clear()
        
        # Add default auxiliary outputs
        for name, gpio in DEFAULT_AUXILIARY_OUTPUTS:
            self._add_auxiliary_output(name=name, gpio=gpio, enabled=True)

    def _add_auxiliary_output(self, name: str = None, gpio: int = None, enabled: bool = True):
        """
        Add a new auxiliary output row to the configuration.
        
        Args:
            name (str, optional): Name of the output. Defaults to "Aux N"
            gpio (int, optional): GPIO pin number. Defaults to next available
            enabled (bool, optional): Whether output is enabled. Defaults to True
        
        Creates a row with:
        - Enable checkbox
        - Name entry
        - GPIO entry
        
        Each output generates two events: "{Name} On" and "{Name} Off"
        """
        from config import DEFAULT_AUXILIARY_GPIO_START
        
        # Auto-generate name if not provided
        if name is None:
            name = f"Aux {len(self.auxiliary_outputs) + 1}"
        
        # Auto-assign GPIO if not provided
        if gpio is None:
            gpio = DEFAULT_AUXILIARY_GPIO_START + len(self.auxiliary_outputs)
        
        # Create variables
        name_var = tk.StringVar(value=name)
        gpio_var = tk.IntVar(value=gpio)
        enabled_var = tk.BooleanVar(value=enabled)
        
        # Create row frame
        row = tb.Frame(self.aux_container)
        row.pack(fill=X, pady=1)
        
        # Enable checkbox
        tb.Checkbutton(row, variable=enabled_var, command=self._on_auxiliary_changed, width=8).pack(side=LEFT)
        
        # Name entry
        name_entry = tb.Entry(row, textvariable=name_var, width=20)
        name_entry.pack(side=LEFT, padx=(0, 5))
        name_entry.bind("<FocusOut>", lambda _e: self._on_auxiliary_changed())
        name_entry.bind("<Return>", lambda _e: self._on_auxiliary_changed())
        
        # GPIO entry
        gpio_entry = tb.Entry(row, textvariable=gpio_var, width=8)
        gpio_entry.pack(side=LEFT)
        gpio_entry.bind("<FocusOut>", lambda _e: self._on_auxiliary_changed())
        gpio_entry.bind("<Return>", lambda _e: self._on_auxiliary_changed())
        
        # Store row data
        self.auxiliary_outputs.append((name_var, gpio_var, enabled_var, row))
        
        # Update available events
        self._on_auxiliary_changed()

    def _remove_last_auxiliary_output(self):
        """
        Remove the last auxiliary output from the configuration.
        """
        if not self.auxiliary_outputs:
            return
        
        # Get and remove last row
        _name_var, _gpio_var, _enabled_var, frame = self.auxiliary_outputs.pop()
        frame.destroy()
        
        # Update available events
        self._on_auxiliary_changed()

    def _get_auxiliary_outputs(self) -> List:
        """
        Extract auxiliary outputs from GUI widgets.
        
        Returns:
            List[AuxiliaryOutput]: List of all auxiliary output configurations
        """
        from models import AuxiliaryOutput
        
        outputs = []
        for name_var, gpio_var, enabled_var, _frame in self.auxiliary_outputs:
            outputs.append(
                AuxiliaryOutput(
                    name=name_var.get().strip(),
                    gpio=int(gpio_var.get()),
                    enabled=bool(enabled_var.get())
                )
            )
        return outputs

    def _on_auxiliary_changed(self):
        """
        Handle auxiliary output changes.
        
        This method:
        1. Updates available events in all schedule comboboxes
        2. Rebuilds waveform preview
        """
        # Update event lists in all schedule rows
        self._update_event_lists()
        
        # Rebuild preview
        self._rebuild_and_preview()

    def _update_event_lists(self):
        """
        Update the event dropdown lists in all schedule rows to include auxiliary events.
        
        Dynamically generates event list based on enabled auxiliary outputs.
        Each enabled output adds two events: "{Name} On" and "{Name} Off"
        """
        # Get base events
        events = list(EVENTS)
        
        # Add auxiliary events
        for name_var, _gpio_var, enabled_var, _frame in self.auxiliary_outputs:
            if enabled_var.get():
                name = name_var.get().strip()
                if name:
                    events.append(f"{name} On")
                    events.append(f"{name} Off")
        
        # Update all schedule row comboboxes
        for ev_var, _st_var, _du_var, frame in self.schedule_rows:
            # Find the combobox widget in this row
            for widget in frame.winfo_children():
                if isinstance(widget, tb.Combobox):
                    widget.configure(values=events)
                    break

    def _get_available_events(self) -> List[str]:
        """
        Get list of available events including base events and auxiliary events.
        
        Returns:
            List[str]: All available event types
        """
        # Start with base events
        events = list(EVENTS)
        
        # Add auxiliary events for enabled outputs
        for name_var, _gpio_var, enabled_var, _frame in self.auxiliary_outputs:
            if enabled_var.get():
                name = name_var.get().strip()
                if name:
                    events.append(f"{name} On")
                    events.append(f"{name} Off")
        
        return events

    # ===========================
    # Block Management Methods
    # ===========================

    def _add_block(self, name: str = None, cycles: int = 1):
        """
        Add a new block to the test sequence.
        
        Args:
            name (str, optional): Block name. Defaults to "Block N"
            cycles (int, optional): Number of cycles for this block. Defaults to 1
        
        Creates:
            - Block name and cycles variables
            - Empty schedule rows list for this block
            - Block selector button in the block list
        """
        # Auto-generate name if not provided
        if name is None:
            name = f"Block {len(self.blocks) + 1}"
        
        # Create variables for this block
        block_name_var = tk.StringVar(value=name)
        block_cycles_var = tk.IntVar(value=cycles)
        block_schedule_rows = []  # Will hold schedule rows for this block
        
        # Create block selector frame
        block_frame = tb.Frame(self.block_list_container)
        block_frame.pack(fill=X, pady=2)
        
        block_idx = len(self.blocks)
        
        # Block selection button (shows block name and cycles)
        def make_select_cmd(idx):
            return lambda: self._switch_to_block(idx)
        
        btn = tb.Button(
            block_frame, 
            text=f"{name} ({cycles} cycles)",
            bootstyle=INFO,
            command=make_select_cmd(block_idx),
            width=20
        )
        btn.pack(side=LEFT, padx=(0, 5))
        
        # Block name entry
        tb.Label(block_frame, text="Name:", width=6).pack(side=LEFT)
        name_entry = tb.Entry(block_frame, textvariable=block_name_var, width=15)
        name_entry.pack(side=LEFT, padx=(0, 5))
        name_entry.bind("<FocusOut>", lambda _e: self._update_block_button())
        name_entry.bind("<Return>", lambda _e: self._update_block_button())
        
        # Block cycles entry
        tb.Label(block_frame, text="Cycles:", width=7).pack(side=LEFT)
        cycles_entry = tb.Entry(block_frame, textvariable=block_cycles_var, width=6)
        cycles_entry.pack(side=LEFT)
        cycles_entry.bind("<FocusOut>", lambda _e: self._update_block_button())
        cycles_entry.bind("<Return>", lambda _e: self._update_block_button())
        
        # Store block data
        self.blocks.append((block_name_var, block_cycles_var, block_schedule_rows, block_frame))
        
        # Update UI
        self._update_block_button()

    def _switch_to_block(self, block_idx: int):
        """
        Switch the schedule editor to display a different block.
        
        Args:
            block_idx (int): Index of the block to display
        
        This method:
        1. Saves the current block's schedule rows
        2. Clears the schedule editor
        3. Loads the target block's schedule rows
        4. Updates the current block indicator
        """
        if block_idx < 0 or block_idx >= len(self.blocks):
            return
        
        # Save current block's schedule rows (exclude frame, keep only vars)
        if 0 <= self.current_block_index < len(self.blocks):
            _, _, current_rows, _ = self.blocks[self.current_block_index]
            current_rows.clear()
            for ev_var, st_var, du_var, _ in self.schedule_rows:
                current_rows.append((ev_var, st_var, du_var))
        
        # Clear the schedule editor
        for _ev_var, _st_var, _du_var, frame in self.schedule_rows:
            frame.destroy()
        self.schedule_rows.clear()
        
        # Load target block's schedule rows
        block_name_var, block_cycles_var, block_rows, block_frame = self.blocks[block_idx]
        self.current_block_index = block_idx
        
        # Recreate schedule rows for this block
        for ev_var, st_var, du_var in block_rows:
            # Recreate the row widget
            row = tb.Frame(self.sched_container)
            row.pack(fill=X, pady=2)
            
            cb = tb.Combobox(row, textvariable=ev_var, values=EVENTS, state="readonly", width=22)
            cb.pack(side=LEFT)
            
            st = tb.Entry(row, textvariable=st_var, width=10)
            st.pack(side=LEFT, padx=(6, 0))
            
            du = tb.Entry(row, textvariable=du_var, width=10)
            du.pack(side=LEFT, padx=(6, 0))
            
            def remove(r=row):
                for i, (_a, _b, _c, frame) in enumerate(self.schedule_rows):
                    if frame is r:
                        self.schedule_rows.pop(i)
                        break
                r.destroy()
                self._rebuild_and_preview()
            
            tb.Button(row, text="Remove", bootstyle=SECONDARY, command=remove).pack(side=LEFT, padx=(10, 0))
            
            cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_and_preview())
            st.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
            du.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
            st.bind("<Return>", lambda _e: self._rebuild_and_preview())
            du.bind("<Return>", lambda _e: self._rebuild_and_preview())
            
            self.schedule_rows.append((ev_var, st_var, du_var, row))
        
        # Update current block indicator
        self.current_block_label.config(text=f"Block: {block_name_var.get()} ({block_cycles_var.get()} cycles)")
        
        # Rebuild preview
        self._rebuild_and_preview()

    def _update_block_button(self):
        """
        Update current block label and trigger preview rebuild when name or cycles changes.
        """
        # Update current block label if needed
        if 0 <= self.current_block_index < len(self.blocks):
            name_var, cycles_var, _, _ = self.blocks[self.current_block_index]
            self.current_block_label.config(text=f"Block: {name_var.get()} ({cycles_var.get()} cycles)")
        
        # Trigger preview rebuild
        self._rebuild_and_preview()

    def _on_add_block(self):
        """Handle Add Block button click."""
        self._add_block()

    def _on_remove_current_block(self):
        """Handle Remove Block button click."""
        if len(self.blocks) <= 1:
            messagebox.showwarning("Cannot Remove", "Profile must have at least one block.")
            return
        
        if not messagebox.askyesno("Remove Block", f"Remove block '{self.blocks[self.current_block_index][0].get()}'?"):
            return
        
        # Remove the block
        _, _, _, block_frame = self.blocks[self.current_block_index]
        block_frame.destroy()
        self.blocks.pop(self.current_block_index)
        
        # Switch to previous block or first block
        new_idx = max(0, self.current_block_index - 1)
        self.current_block_index = -1  # Force reload
        self._switch_to_block(new_idx)

    def _on_move_block_up(self):
        """Handle Move Up button click."""
        if self.current_block_index <= 0:
            return
        
        # Swap with previous block
        idx = self.current_block_index
        self.blocks[idx], self.blocks[idx-1] = self.blocks[idx-1], self.blocks[idx]
        
        # Rebuild block list UI
        self._rebuild_block_list()
        
        # Switch to moved block
        self.current_block_index = -1
        self._switch_to_block(idx - 1)

    def _on_move_block_down(self):
        """Handle Move Down button click."""
        if self.current_block_index >= len(self.blocks) - 1:
            return
        
        # Swap with next block
        idx = self.current_block_index
        self.blocks[idx], self.blocks[idx+1] = self.blocks[idx+1], self.blocks[idx]
        
        # Rebuild block list UI
        self._rebuild_block_list()
        
        # Switch to moved block
        self.current_block_index = -1
        self._switch_to_block(idx + 1)

    def _rebuild_block_list(self):
        """Rebuild the block list UI after reordering."""
        # Clear container
        for widget in self.block_list_container.winfo_children():
            widget.destroy()
        
        # Recreate all block frames
        for idx, (name_var, cycles_var, rows, old_frame) in enumerate(self.blocks):
            block_frame = tb.Frame(self.block_list_container)
            block_frame.pack(fill=X, pady=2)
            
            def make_select_cmd(i):
                return lambda: self._switch_to_block(i)
            
            btn = tb.Button(
                block_frame, 
                text=f"{name_var.get()} ({cycles_var.get()} cycles)",
                bootstyle=INFO,
                command=make_select_cmd(idx),
                width=20
            )
            btn.pack(side=LEFT, padx=(0, 5))
            
            tb.Label(block_frame, text="Name:", width=6).pack(side=LEFT)
            name_entry = tb.Entry(block_frame, textvariable=name_var, width=15)
            name_entry.pack(side=LEFT, padx=(0, 5))
            name_entry.bind("<FocusOut>", lambda _e: self._update_block_button())
            name_entry.bind("<Return>", lambda _e: self._update_block_button())
            
            tb.Label(block_frame, text="Cycles:", width=7).pack(side=LEFT)
            cycles_entry = tb.Entry(block_frame, textvariable=cycles_var, width=6)
            cycles_entry.pack(side=LEFT)
            cycles_entry.bind("<FocusOut>", lambda _e: self._update_block_button())
            cycles_entry.bind("<Return>", lambda _e: self._update_block_button())
            
            # Update tuple with new frame
            self.blocks[idx] = (name_var, cycles_var, rows, block_frame)

    def _get_blocks(self) -> List[Block]:
        """
        Extract all blocks from GUI.
        
        Returns:
            List[Block]: List of all blocks in execution order
        """
        # Save current block's schedule rows
        if 0 <= self.current_block_index < len(self.blocks):
            _, _, current_rows, _ = self.blocks[self.current_block_index]
            current_rows.clear()
            for ev_var, st_var, du_var, _ in self.schedule_rows:
                current_rows.append((ev_var, st_var, du_var))
        
        # Build Block objects
        blocks = []
        for name_var, cycles_var, rows, _ in self.blocks:
            events = [ScheduledEvent(ev.get(), float(st.get()), float(du.get())) 
                     for ev, st, du in rows]
            blocks.append(Block(
                block_name=name_var.get(),
                scheduled_events=events,
                cycles=int(cycles_var.get())
            ))
        
        return blocks

    # ===========================
    # Waveform Preview Methods
    # ===========================


    def _rebuild_and_preview(self):
        """
        Rebuild waveforms and update the preview display.
        
        This is the central method that orchestrates waveform generation and
        visualization. It's called automatically whenever any setting changes.
        
        Process Flow:
        1. Clear the matplotlib axes
        2. Read current settings (units, blocks, positions)
        3. Call waveform_engine to generate waveforms from all blocks
        4. Generate multi-channel preview data
        5. Update summary text
        6. Plot waveforms on matplotlib canvas with block boundaries
        
        Plot Style:
            - If ramps exist: Use line plot (shows smooth transitions)
            - If no ramps: Use step plot (shows digital edges)
            - Each channel is offset vertically by 2 units
            - Y-axis labels show channel names with GPIO numbers
            - Vertical lines mark block boundaries
        
        Error Handling:
            - Displays error message in summary label
            - Shows error text on plot canvas
            - Does not crash on invalid input
        
        Note:
            This method is called frequently, so it must be fast.
            All heavy computation is done in the waveform_engine module.
        """
        # Clear the previous plot
        self.ax.clear()
        self.ax.grid(True)

        # Get current settings from GUI
        unit = self.waveform_unit.get()
        all_blocks = self._get_blocks()
        auxiliary_outputs = self._get_auxiliary_outputs()
        
        # Filter blocks based on preview mode
        preview_mode = self.preview_mode.get()
        if preview_mode == "Current Block" and 0 <= self.current_block_index < len(all_blocks):
            blocks = [all_blocks[self.current_block_index]]
        else:
            blocks = all_blocks

        # Generate waveforms using waveform_engine
        try:
            (self.iso_digital, self.dut_digital,
             self.iso_display, self.dut_display,
             self.iso_has_ramps, self.dut_has_ramps,
             self.total_length_ms, self.block_end_times, self.auxiliary_waveforms) = build_waveforms_from_blocks(
                blocks, unit, auxiliary_outputs=auxiliary_outputs
            )
        except Exception as e:
            # Display error and abort preview
            self.summary_lbl.config(text=f"Waveform error: {e}")
            self.ax.text(0.5, 0.5, str(e), ha="center", va="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        # Get position configurations
        positions = self._pico_positions = self._get_positions()

        # Generate multi-channel preview data
        channels = build_preview_channels(
            positions=positions,
            row_delay_ms=float(self.row_delay_ms.get()),
            iso_display=self.iso_display,
            dut_display=self.dut_display,
            iso_digital=self.iso_digital,
            dut_digital=self.dut_digital,
        )

        # Count enabled positions and total cycles
        enabled_count = sum(1 for p in positions if p.enabled)
        total_cycles = sum(b.cycles for b in blocks)
        preview_mode = self.preview_mode.get()
        preview_note = f"Previewing: {preview_mode}"

        # Update summary text
        self.summary_lbl.config(
            text=(
                f"Units: {unit} | Blocks: {len(blocks)} | Total Cycles: {total_cycles} | Total Length: {self.total_length_ms:.1f} ms\n"
                f"Enabled positions: {enabled_count} | Row delay: {self.row_delay_ms.get()} ms\n"
                f"{preview_note} | Blocks execute sequentially. Cycle Delay in last cycle of each block is skipped."
            )
        )

        # Check if there are channels to plot
        if not channels:
            self.ax.text(0.5, 0.5, "No positions enabled.", ha="center", va="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        # Plot each channel with vertical offset
        labels = list(channels.keys())
        for yi, label in enumerate(labels):
            payload = channels[label]
            
            # Determine if this is an isolator or DUT channel
            is_iso = label.startswith("ISO")
            has_ramps = self.iso_has_ramps if is_iso else self.dut_has_ramps

            # Choose plot style based on whether ramps exist
            if has_ramps:
                # Use line plot for smooth ramp visualization
                t = payload["display_t"]
                v = payload["display_v"]
                self.ax.plot(t, [val + yi * 2 for val in v])
            else:
                # Use step plot for digital edges
                t = payload["digital_t"]
                v = payload["digital_v"]
                self.ax.step(t, [val + yi * 2 for val in v], where="post")

        # Draw vertical lines at block boundaries
        for block_end_time in self.block_end_times[:-1]:  # Skip the last one (end of profile)
            self.ax.axvline(x=block_end_time, color='red', linestyle='--', alpha=0.5, linewidth=1)

        # Configure axes
        self.ax.set_yticks([yi * 2 + 0.5 for yi in range(len(labels))])
        self.ax.set_yticklabels(labels, fontsize=8)
        self.ax.set_xlabel("Time (ms)")
        self.ax.set_title("Preview (red lines = block boundaries)")
        
        # Apply tight layout and redraw
        self.fig.tight_layout()
        self.canvas.draw()

    def _build_profile_object(self) -> Profile:
        """
        Build a complete Profile object from current GUI settings.
        
        This method:
        1. Validates that at least one position is enabled
        2. Validates that at least one block exists
        3. Gets all blocks from GUI
        4. Generates waveforms using waveform_engine
        5. Constructs a Profile dataclass with all settings
        
        Returns:
            Profile: Complete profile ready for JSON export or Pico upload
        
        Raises:
            ValueError: If validation fails or waveform generation fails
        
        The returned Profile contains:
            - User settings (name, units, row delay)
            - List of blocks (each with schedule and cycles)
            - Precomputed waveforms (digital step functions for all blocks)
            - Position configurations
        
        This object can be serialized to JSON for:
            - Saving to file
            - Uploading to Pico
            - Sharing with others
        """
        # Get current position configurations
        positions = self._get_positions()
        
        # Validate: at least one position must be enabled
        if not any(p.enabled for p in positions):
            raise ValueError("Enable at least one position.")

        # Get all blocks
        blocks = self._get_blocks()
        
        # Validate: at least one block must exist
        if not blocks:
            raise ValueError("Add at least one block.")

        # Get time unit and auxiliary outputs
        unit = self.waveform_unit.get()
        auxiliary_outputs = self._get_auxiliary_outputs()

        # Generate waveforms for all blocks (raises ValueError if any block is invalid)
        iso_dig, dut_dig, _, _, _, _, _, _, aux_waveforms = build_waveforms_from_blocks(
            blocks, unit, auxiliary_outputs=auxiliary_outputs
        )

        # Construct and return Profile object
        return Profile(
            profile_name=self.profile_name.get().strip() or "Profile",
            waveform_time_units=unit,
            blocks=blocks,
            isolator_waveform_points=[(float(t), int(s)) for t, s in iso_dig],
            dut_waveform_points=[(float(t), int(s)) for t, s in dut_dig],
            row_delay_ms=float(self.row_delay_ms.get()),
            positions=positions,
            auxiliary_outputs=auxiliary_outputs,
            auxiliary_waveforms=aux_waveforms,
        )

    def _profile_to_json_text(self, prof: Profile) -> str:
        """
        Convert a Profile object to JSON text.
        
        Args:
            prof (Profile): Profile object to serialize
        
        Returns:
            str: Pretty-printed JSON string
        
        The JSON format is human-readable and includes:
            - All profile settings
            - Schedule events (as list of objects)
            - Waveform points (as list of [time, state] pairs)
            - Position configurations (as list of objects)
        
        This format is compatible with both:
            - File save/load operations
            - Pico firmware (which expects this exact structure)
        """
        # Convert Profile to dictionary using dataclasses.asdict
        data = asdict(prof)
        
        # Explicitly convert nested dataclasses to dicts
        data["positions"] = [asdict(p) for p in prof.positions]
        data["blocks"] = [asdict(b) for b in prof.blocks]
        data["auxiliary_outputs"] = [asdict(aux) for aux in prof.auxiliary_outputs] if prof.auxiliary_outputs else []
        
        # Return pretty-printed JSON
        return json.dumps(data, indent=2)

    def _on_save_profile(self):
        """
        Handle Save Profile button click.
        
        This method:
        1. Builds a Profile object from current settings (includes all blocks)
        2. Opens a file save dialog
        3. Serializes the profile to JSON
        4. Writes to the selected file
        5. Shows success or error message
        
        File Format:
            - JSON with .json extension
            - Human-readable indented format
            - Contains all blocks with their schedules and cycles
            - Can be loaded back into the application
            - Can be uploaded to Pico hardware
        
        Error Handling:
            - Validates profile before opening dialog
            - Catches file write errors
            - Shows error messages to user
        """
        # Build profile from current GUI state (may raise ValueError)
        try:
            prof = self._build_profile_object()
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            return

        # Open file save dialog
        save_path = filedialog.asksaveasfilename(
            title="Save Profile JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        
        # User cancelled dialog
        if not save_path:
            return

        # Write profile to file
        try:
            json_text = self._profile_to_json_text(prof)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(json_text)
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            return

        # Show success message
        messagebox.showinfo("Saved", f"Profile saved:\n{save_path}")

    def _on_load_profile(self):
        """
        Handle Load Profile button click.
        
        This method:
        1. Opens a file open dialog
        2. Reads and parses JSON file
        3. Validates JSON structure
        4. Populates GUI with loaded settings
        5. Rebuilds waveform preview
        
        The loaded profile populates:
            - Profile name and settings (units, row delay)
            - All blocks with their schedules and cycles
            - Position configurations (updates all position widgets)
        
        Backward Compatibility:
            - Also supports old format with single schedule + cycles
            - Converts old format to a single block automatically
        
        Error Handling:
            - Validates JSON format
            - Checks for required fields
            - Shows error messages for invalid files
            - Does not modify GUI on error
        
        Note:
            - Adjusts num_positions if file has different count
            - Reinitializes position widgets if needed
            - Automatically rebuilds preview after loading
        """
        # Open file selection dialog
        path = filedialog.askopenfilename(
            title="Load Profile JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        # User cancelled dialog
        if not path:
            return

        # Read and parse JSON file
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not read JSON:\n{e}")
            return

        # Populate GUI with loaded data
        try:
            # Load basic settings
            self.profile_name.set(data.get("profile_name", "Profile"))
            self.waveform_unit.set(data.get("waveform_time_units", "ms"))
            self.row_delay_ms.set(float(data.get("row_delay_ms", 0.0)))

            # Check if this is new format (with blocks) or old format (single schedule + cycles)
            if "blocks" in data:
                # New format: load all blocks
                blocks_data = data.get("blocks", [])
                if not isinstance(blocks_data, list):
                    raise ValueError("blocks must be a list")
                
                if not blocks_data:
                    raise ValueError("blocks list cannot be empty")
                
                # Clear existing blocks (keep at least one empty block)
                while len(self.blocks) > 1:
                    _, _, _, block_frame = self.blocks[-1]
                    block_frame.destroy()
                    self.blocks.pop()
                
                # Load each block
                for i, block_data in enumerate(blocks_data):
                    block_name = block_data.get("block_name", f"Block {i+1}")
                    block_cycles = int(block_data.get("cycles", 1))
                    block_schedule = block_data.get("scheduled_events", [])
                    
                    if not isinstance(block_schedule, list):
                        raise ValueError(f"scheduled_events in block '{block_name}' must be a list")
                    
                    # Use existing first block or add new block
                    if i == 0:
                        # Update first block
                        name_var, cycles_var, _, _ = self.blocks[0]
                        name_var.set(block_name)
                        cycles_var.set(block_cycles)
                        self.current_block_index = -1  # Force reload
                        self._switch_to_block(0)
                    else:
                        # Add new block
                        self._add_block(block_name, block_cycles)
                    
                    # Switch to this block and load its schedule
                    self._switch_to_block(i)
                    self._clear_schedule_rows()
                    
                    for ev in block_schedule:
                        event = ev.get("event", EVENTS[0])
                        start = float(ev.get("start", 0.0))
                        duration = float(ev.get("duration", 0.0))
                        
                        # Note: Event type not validated here to allow auxiliary events
                        
                        self._add_schedule_row(event, start, duration)
                
                # Switch back to first block
                self._switch_to_block(0)
                
            else:
                # Old format: single schedule + cycles (backward compatibility)
                sched = data.get("scheduled_events", [])
                if not isinstance(sched, list):
                    raise ValueError("scheduled_events must be a list")
                
                cycles = int(data.get("cycles", 1))
                
                # Clear existing blocks and create single block
                while len(self.blocks) > 1:
                    _, _, _, block_frame = self.blocks[-1]
                    block_frame.destroy()
                    self.blocks.pop()
                
                # Update first block
                name_var, cycles_var, _, _ = self.blocks[0]
                name_var.set("Main Block")
                cycles_var.set(cycles)
                self.current_block_index = -1
                self._switch_to_block(0)
                
                # Load schedule into first block
                self._clear_schedule_rows()
                for ev in sched:
                    event = ev.get("event", EVENTS[0])
                    start = float(ev.get("start", 0.0))
                    duration = float(ev.get("duration", 0.0))
                    
                    # Note: Event type not validated here to allow auxiliary events
                    
                    self._add_schedule_row(event, start, duration)

            # Load position configurations
            pos_list = data.get("positions", [])
            if not isinstance(pos_list, list):
                raise ValueError("positions must be a list")

            # Reinitialize positions if count changed
            if len(pos_list) > 0:
                self.num_positions = len(pos_list)
                self.default_isolator_gpios = list(range(1, self.num_positions + 1))
                self.default_dut_gpios = list(range(21, 21 + self.num_positions))
                self._init_positions()

                # Populate position settings
                for i, p in enumerate(pos_list):
                    if i >= self.num_positions:
                        break
                    
                    self.pos_enabled_vars[i].set(bool(p.get("enabled", False)))
                    self.pos_iso_gpio_vars[i].set(int(p.get("isolator_gpio", i + 1)))
                    self.pos_dut_gpio_vars[i].set(int(p.get("dut_gpio", 21 + i)))
                    self.pos_offset_vars[i].set(float(p.get("dut_offset_ms", 0.0)))

            # Load auxiliary outputs (with backward compatibility)
            aux_list = data.get("auxiliary_outputs", [])
            if aux_list and isinstance(aux_list, list):
                # Clear existing auxiliary outputs
                while self.auxiliary_outputs:
                    self._remove_last_auxiliary_output()
                
                # Load each auxiliary output
                for aux in aux_list:
                    name = aux.get("name", "Aux")
                    gpio = int(aux.get("gpio", 15))
                    enabled = bool(aux.get("enabled", True))
                    self._add_auxiliary_output(name=name, gpio=gpio, enabled=enabled)

        except Exception as e:
            messagebox.showerror("Load Error", f"Profile format error:\n{e}")
            return

        # Rebuild preview with loaded data
        self._rebuild_and_preview()

    # ===========================
    # Pico Communication Methods
    # ===========================
    # These methods handle all interaction with the Raspberry Pi Pico hardware

    def _pico_set_status(self, text: str):
        """
        Update the Pico status label.
        
        Args:
            text (str): Status message to display (without "Pico:" prefix)
        
        The status label shows connection state, command responses, and errors.
        """
        self.pico_status.set(f"Pico: {text}")

    def _pico_connect(self):
        """
        Handle Connect button click.
        
        Establishes serial connection to the Pico:
        1. Reads COM port and baud rate from GUI
        2. Calls PicoLink.connect()
        3. Updates status and button states
        
        Error Handling:
            - Shows error dialog if connection fails
            - Updates status to "Disconnected" on error
            - Always updates button states
        """
        try:
            port = self.pico_port.get().strip()
            baud = int(self.pico_baud.get())
            self.pico.connect(port, baud=baud, timeout=1.0)
            self._pico_set_status(f"Connected on {port} @ {baud}")
        except Exception as e:
            self._pico_set_status("Disconnected")
            messagebox.showerror("Pico Connect Error", str(e))
        finally:
            self._update_pico_button_states()

    def _pico_ping(self):
        """
        Handle Ping button click.
        
        Tests if the Pico is responsive:
        1. Sends PING command
        2. Waits for PONG response
        3. Updates status based on response
        
        The ping test verifies that:
            - Serial connection is working
            - Pico firmware is running
            - Command protocol is functional
        """
        try:
            resp = self.pico.ping()
            if resp == "PONG":
                self._pico_set_status(f"Connected (PONG) on {self.pico.port}")
            else:
                self._pico_set_status(f"Ping failed: {resp}")
                messagebox.showerror("Pico Ping Error", resp or "No response from Pico.")
        except Exception as e:
            messagebox.showerror("Pico Ping Error", str(e))
        finally:
            self._update_pico_button_states()

    def _pico_export_current(self):
        """
        Handle Export to Pico button click.
        
        Uploads the current profile to Pico:
        1. Builds profile from current GUI state
        2. Converts to JSON text
        3. Sends PUT command with profile data
        4. Updates status based on response
        
        The profile is stored on the Pico's filesystem and can be
        executed later with the Run command.
        
        Error Handling:
            - Validates profile before upload
            - Shows error if profile is invalid
            - Shows error if upload fails
        """
        try:
            # Build and validate profile
            prof = self._build_profile_object()
            json_text = self._profile_to_json_text(prof)

            # Upload to Pico
            filename = self.pico_filename.get().strip() or "profile.json"
            resp = self.pico.put_json(filename, json_text)

            # Update status based on response
            if resp.startswith("OK"):
                self._pico_set_status(f"Exported to {filename} (OK)")
            else:
                self._pico_set_status(f"Export failed: {resp}")
                messagebox.showerror("Pico Export Error", resp or "No response from Pico.")
        except Exception as e:
            messagebox.showerror("Pico Export Error", str(e))
        finally:
            self._update_pico_button_states()

    def _pico_run(self):
        """
        Handle Run on Pico button click.
        
        Starts profile execution on the Pico in a background thread:
        1. Validates no execution is already running
        2. Sends RUN command to Pico
        3. Starts background thread to wait for completion
        4. Updates button states to show running
        
        Background Thread:
            - Calls pico.wait_done() to block until completion
            - Sends result through queue to GUI thread
            - Does not block GUI (keeps UI responsive)
        
        The background thread allows the user to:
            - Monitor progress
            - Pause/resume execution
            - Stop execution early
            - Use other GUI features while running
        
        Error Handling:
            - Checks if already running
            - Shows error if RUN command fails
            - Cleans up state on error
        """
        # Check if already running
        if self._pico_run_thread and self._pico_run_thread.is_alive():
            messagebox.showinfo("Pico", "Pico is already running a profile.")
            return

        try:
            # Send RUN command
            filename = self.pico_filename.get().strip() or "profile.json"
            resp = self.pico.run(filename)
            
            # Check for error response
            if not resp.startswith("OK"):
                self._pico_set_status(f"Run failed: {resp}")
                messagebox.showerror("Pico Run Error", resp or "No response from Pico.")
                return

            # Update state
            self._pico_is_running = True
            self._pico_is_paused = False
            self._update_pico_button_states()
            self._pico_set_status(f"Running {filename}...")

            # Start background thread to wait for completion
            def worker():
                """Background thread worker function."""
                done = self.pico.wait_done(timeout_s=300.0)
                self._pico_q.put(("done", filename, done))

            self._pico_run_thread = threading.Thread(target=worker, daemon=True)
            self._pico_run_thread.start()
            
            # Start polling the queue for completion
            self.after(50, self._poll_pico_queue)

        except Exception as e:
            messagebox.showerror("Pico Run Error", str(e))
            self._pico_is_running = False
            self._pico_is_paused = False
            self._update_pico_button_states()

    def _poll_pico_queue(self):
        """
        Poll the queue for background thread messages.
        
        This method is called periodically by the GUI event loop to check
        for completion messages from the background execution thread.
        
        When a message arrives:
            - Updates running/paused state
            - Updates button states
            - Shows status or error message
        
        If the background thread is still running, schedules another
        poll after 50ms.
        
        This polling mechanism keeps the GUI responsive while allowing
        background tasks to communicate results safely.
        """
        try:
            # Check for messages (non-blocking)
            while True:
                kind, filename, msg = self._pico_q.get_nowait()
                
                if kind == "done":
                    # Execution completed
                    self._pico_is_running = False
                    self._pico_is_paused = False
                    self._update_pico_button_states()

                    # Show result
                    if msg.startswith("DONE"):
                        self._pico_set_status(f"Done: {filename}")
                    else:
                        self._pico_set_status(f"Run error: {msg}")
                        messagebox.showerror("Pico Run Error", msg)
        except queue.Empty:
            pass  # No messages yet

        # Continue polling if thread is still alive
        if self._pico_run_thread and self._pico_run_thread.is_alive():
            self.after(50, self._poll_pico_queue)

    def _pico_pause(self):
        """
        Handle Pause button click.
        
        Pauses profile execution on the Pico:
        1. Sends PAUSE command
        2. Updates pause state if successful
        3. Updates button states
        
        While paused:
            - GPIO outputs maintain their current state
            - Timing is frozen
            - Resume button becomes enabled
        """
        try:
            resp = self.pico.pause()
            if resp.startswith("OK"):
                self._pico_is_paused = True
                self._pico_set_status("Paused (OK)")
            else:
                self._pico_set_status(f"Pause: {resp}")
        except Exception as e:
            messagebox.showerror("Pico Pause Error", str(e))
        finally:
            self._update_pico_button_states()

    def _pico_resume(self):
        """
        Handle Resume button click.
        
        Resumes paused profile execution on the Pico:
        1. Sends RESUME command
        2. Updates pause state if successful
        3. Updates button states
        
        Execution continues from the exact point where it was paused.
        """
        try:
            resp = self.pico.resume()
            if resp.startswith("OK"):
                self._pico_is_paused = False
                self._pico_set_status("Resumed (OK)")
            else:
                self._pico_set_status(f"Resume: {resp}")
        except Exception as e:
            messagebox.showerror("Pico Resume Error", str(e))
        finally:
            self._update_pico_button_states()

    def _pico_stop(self):
        """
        Handle Stop button click.
        
        Stops profile execution on the Pico immediately:
        1. Sends STOP command
        2. Updates running/paused state if successful
        3. Updates button states
        
        After stopping:
            - All GPIO outputs go to their default state
            - Execution cannot be resumed
            - Run button becomes enabled for new execution
        """
        try:
            resp = self.pico.stop()
            if resp.startswith("OK"):
                self._pico_set_status("Stopped (OK)")
                self._pico_is_running = False
                self._pico_is_paused = False
            else:
                self._pico_set_status(f"Stop: {resp}")
        except Exception as e:
            messagebox.showerror("Pico Stop Error", str(e))
        finally:
            self._update_pico_button_states()


    def _on_closing(self):
        """
        Handle window close event - saves theme preference.
        """
        import os
        try:
            theme_file = os.path.join(os.path.dirname(__file__), ".theme_preference")
            with open(theme_file, "w") as f:
                f.write(self.style.theme.name)
        except:
            pass
        self.destroy()


# ================================
# Application Entry Point
# ================================

if __name__ == "__main__":
    """
    Main entry point for the Profile Builder application.
    
    This creates and runs the main application window.
    The application uses ttkbootstrap's themed window and runs
    the Tkinter event loop until the user closes the window.
    
    Usage:
        python waveform_profile_builder.py
    
    Requirements:
        - Python 3.7+
        - ttkbootstrap
        - matplotlib
        - pyserial (optional, for Pico communication)
    """
    app = ProfileBuilderApp()
    app.mainloop()


def main():
    """
    Entry point for console script.
    
    This function is called when running 'profile-builder' from command line
    after installation via pip.
    """
    app = ProfileBuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
