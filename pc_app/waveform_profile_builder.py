# profile_builder_with_pico.py
# PC GUI + Pico export/run with non-blocking (threaded) run, plus Pause/Resume/Stop.
#
# Requirements:
#   pip install pyserial ttkbootstrap matplotlib
#
# Notes:
# - Run is executed in a background thread so the GUI stays responsive.
# - Pause/Resume/Stop are sent to Pico while running.
# - Waveform Blocks section is scrollable.

import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional

import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.widgets.scrolled import ScrolledFrame

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import threading
import queue
import time

try:
    import serial
except Exception:
    serial = None


# ----------------------------
# Units
# ----------------------------
UNIT_TO_MS = {"ms": 1.0, "sec": 1000.0, "min": 60_000.0}

EVENTS = [
    "Isolator On",
    "Isolator Rise Time",
    "Isolator Fall Time",
    "DUT Hold Time",
    "DUT Rise Time",
    "DUT Fall Time",
    "Isolator Off Time",
    "DUT Off Time",
    "Cycle Delay",
]

ISO_ON_STEADY = {"Isolator On"}
ISO_OFF_STEADY = {"Isolator Off Time", "Cycle Delay"}

DUT_ON_STEADY = {"DUT Hold Time"}
DUT_OFF_STEADY = {"DUT Off Time", "Cycle Delay"}

ISO_RISE = {"Isolator Rise Time"}   # display only
ISO_FALL = {"Isolator Fall Time"}   # display only
DUT_RISE = {"DUT Rise Time"}        # display only
DUT_FALL = {"DUT Fall Time"}        # display only


# ----------------------------
# Data model
# ----------------------------
@dataclass
class PositionConfig:
    position: int
    enabled: bool
    isolator_gpio: int
    dut_gpio: int
    dut_offset_ms: float = 0.0


@dataclass
class ScheduledEvent:
    event: str
    start: float
    duration: float


@dataclass
class Profile:
    profile_name: str
    waveform_time_units: str
    scheduled_events: List[ScheduledEvent]
    isolator_waveform_points: List[Tuple[float, int]]
    dut_waveform_points: List[Tuple[float, int]]
    row_delay_ms: float
    cycles: int
    positions: List[PositionConfig]


# ----------------------------
# Helpers
# ----------------------------
def to_ms(v: float, unit: str) -> float:
    if unit not in UNIT_TO_MS:
        raise ValueError(f"Unsupported unit: {unit}")
    return float(v) * UNIT_TO_MS[unit]


def merge_duplicate_times_keep_last(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for t, v in points:
        if out and abs(out[-1][0] - t) < 1e-9:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    return out


def normalize_step_points(points: List[Tuple[float, int]]) -> List[Tuple[float, int]]:
    if not points:
        return []

    pts = sorted(points, key=lambda x: x[0])

    merged: List[Tuple[float, int]] = []
    for t, s in pts:
        if merged and abs(merged[-1][0] - t) < 1e-9:
            merged[-1] = (t, s)
        else:
            merged.append((t, s))

    compact: List[Tuple[float, int]] = []
    for i, (t, s) in enumerate(merged):
        if not compact:
            compact.append((t, s))
            continue
        is_last = (i == len(merged) - 1)
        if s != compact[-1][1] or is_last:
            compact.append((t, s))

    if len(compact) == 1:
        compact.append((compact[0][0], compact[0][1]))
    return compact


def state_last_start_wins(t_ms: float, blocks: List[Tuple[float, float, int]], default: int = 0) -> int:
    best = None  # (start, state)
    for s, e, st in blocks:
        if s <= t_ms < e:
            if best is None or s > best[0]:
                best = (s, st)
    return best[1] if best else default


def build_digital_step_waveform(steady_blocks: List[Tuple[float, float, int]], boundaries: List[float]) -> List[Tuple[float, int]]:
    if not boundaries:
        return [(0.0, 0), (0.0, 0)]

    b = sorted(set(boundaries))

    pts: List[Tuple[float, int]] = []
    for t in b:
        pts.append((t, state_last_start_wins(t, steady_blocks, default=0)))

    pts.append((b[-1], state_last_start_wins(b[-1], steady_blocks, default=0)))
    return normalize_step_points(pts)


def apply_directed_ramps_on_display(
    base_step_points: List[Tuple[float, int]],
    ramp_up_windows: List[Tuple[float, float]],
    ramp_down_windows: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    if not base_step_points:
        return []

    display = [(t, float(s)) for t, s in base_step_points]
    display = sorted(display, key=lambda x: x[0])
    display = merge_duplicate_times_keep_last(display)

    def overlay_ramp(rs: float, re: float, v0: float, v1: float):
        nonlocal display
        if re <= rs:
            return

        new_disp: List[Tuple[float, float]] = []
        for t, v in display:
            if t < rs or t > re:
                new_disp.append((t, v))

        new_disp.append((rs, v0))
        new_disp.append((re, v1))

        new_disp = sorted(new_disp, key=lambda x: x[0])
        new_disp = merge_duplicate_times_keep_last(new_disp)
        display = new_disp

    for rs, re in sorted(ramp_up_windows, key=lambda x: x[0]):
        overlay_ramp(rs, re, 0.0, 1.0)

    for rs, re in sorted(ramp_down_windows, key=lambda x: x[0]):
        overlay_ramp(rs, re, 1.0, 0.0)

    return display


def build_waveforms_from_schedule(
    schedule: List[ScheduledEvent],
    unit: str,
    cycles: int,
) -> Tuple[
    List[Tuple[float, int]],     # iso digital (expanded cycles)
    List[Tuple[float, int]],     # dut digital (expanded cycles)
    List[Tuple[float, float]],   # iso display (expanded cycles)
    List[Tuple[float, float]],   # dut display (expanded cycles)
    bool,                        # iso_has_ramps
    bool,                        # dut_has_ramps
    float,                       # cycle_length_ms (base single-cycle length)
]:
    if not schedule:
        raise ValueError("Add at least one schedule block.")
    if cycles < 1:
        raise ValueError("Cycles must be >= 1")

    base_events_ms: List[Tuple[str, float, float]] = []
    base_boundaries: List[float] = [0.0]

    for ev in schedule:
        if ev.event not in EVENTS:
            raise ValueError(f"Unknown event '{ev.event}'")
        if ev.start < 0:
            raise ValueError("Start must be >= 0")
        if ev.duration < 0:
            raise ValueError("Duration must be >= 0")

        s = to_ms(ev.start, unit)
        e = s + to_ms(ev.duration, unit)
        base_events_ms.append((ev.event, s, e))
        base_boundaries.extend([s, e])

    cycle_length_ms = max(base_boundaries) if base_boundaries else 0.0

    boundaries: List[float] = [0.0]
    iso_steady_blocks: List[Tuple[float, float, int]] = []
    dut_steady_blocks: List[Tuple[float, float, int]] = []

    iso_ramp_up: List[Tuple[float, float]] = []
    iso_ramp_down: List[Tuple[float, float]] = []
    dut_ramp_up: List[Tuple[float, float]] = []
    dut_ramp_down: List[Tuple[float, float]] = []

    for c in range(cycles):
        shift = c * cycle_length_ms

        for event, s0, e0 in base_events_ms:
            if event == "Cycle Delay" and c == cycles - 1:
                continue

            s = s0 + shift
            e = e0 + shift
            boundaries.extend([s, e])

            if event in ISO_ON_STEADY:
                iso_steady_blocks.append((s, e, 1))
            if event in ISO_OFF_STEADY:
                iso_steady_blocks.append((s, e, 0))

            if event in DUT_ON_STEADY:
                dut_steady_blocks.append((s, e, 1))
            if event in DUT_OFF_STEADY:
                dut_steady_blocks.append((s, e, 0))

            if event in ISO_RISE:
                iso_ramp_up.append((s, e))
            if event in ISO_FALL:
                iso_ramp_down.append((s, e))
            if event in DUT_RISE:
                dut_ramp_up.append((s, e))
            if event in DUT_FALL:
                dut_ramp_down.append((s, e))

    iso_digital = build_digital_step_waveform(iso_steady_blocks, boundaries)
    dut_digital = build_digital_step_waveform(dut_steady_blocks, boundaries)

    iso_has_ramps = (len(iso_ramp_up) + len(iso_ramp_down)) > 0
    dut_has_ramps = (len(dut_ramp_up) + len(dut_ramp_down)) > 0

    iso_display = apply_directed_ramps_on_display(iso_digital, iso_ramp_up, iso_ramp_down)
    dut_display = apply_directed_ramps_on_display(dut_digital, dut_ramp_up, dut_ramp_down)

    return iso_digital, dut_digital, iso_display, dut_display, iso_has_ramps, dut_has_ramps, cycle_length_ms


def shift_series(points: List[Tuple[float, float]], shift_ms: float) -> Tuple[List[float], List[float]]:
    return [t + shift_ms for t, _ in points], [v for _, v in points]


def shift_step_points(points: List[Tuple[float, int]], shift_ms: float) -> Tuple[List[float], List[int]]:
    return [t + shift_ms for t, _ in points], [s for _, s in points]


def build_preview_channels(
    positions: List[PositionConfig],
    row_delay_ms: float,
    iso_display: List[Tuple[float, float]],
    dut_display: List[Tuple[float, float]],
    iso_digital: List[Tuple[float, int]],
    dut_digital: List[Tuple[float, int]],
) -> Dict[str, Dict]:
    enabled = [p for p in positions if p.enabled]
    if not enabled:
        return {}

    out: Dict[str, Dict] = {}

    for idx, p in enumerate(enabled):
        base_shift = idx * row_delay_ms

        t_iso_disp, v_iso_disp = shift_series(iso_display, base_shift)
        t_iso_dig, v_iso_dig = shift_step_points(iso_digital, base_shift)

        out[f"ISO P{p.position} (GPIO{p.isolator_gpio})"] = {
            "display_t": t_iso_disp,
            "display_v": v_iso_disp,
            "digital_t": t_iso_dig,
            "digital_v": v_iso_dig,
        }

        t_dut_disp, v_dut_disp = shift_series(dut_display, base_shift + float(p.dut_offset_ms))
        t_dut_dig, v_dut_dig = shift_step_points(dut_digital, base_shift + float(p.dut_offset_ms))

        out[f"DUT P{p.position} (GPIO{p.dut_gpio})"] = {
            "display_t": t_dut_disp,
            "display_v": v_dut_disp,
            "digital_t": t_dut_dig,
            "digital_v": v_dut_dig,
        }

    return out


# ----------------------------
# Pico serial helper (PC side)
# ----------------------------
class PicoLink:
    """
    PC -> Pico:
      PING\n
      PUT <filename> <nbytes>\n<raw json bytes>
      RUN <filename>\n
      STOP\n
      PAUSE\n
      RESUME\n

    Pico -> PC:
      PONG\n
      OK PUT\n or ERR <msg>\n
      OK RUN\n then DONE ...\n (or ERR ...)
      OK STOP\n
      OK PAUSE\n
      OK RESUME\n
    """
    def __init__(self):
        self.ser: Optional["serial.Serial"] = None
        self.port = ""
        self.baud = 115200
        self.last_filename = "profile.json"
        self._lock = threading.Lock()

    def connect(self, port: str, baud: int = 115200, timeout: float = 1.0):
        if serial is None:
            raise RuntimeError("pyserial not installed. Run: pip install pyserial")
        if self.ser and self.ser.is_open:
            self.ser.close()

        self.port = port
        self.baud = baud
        self.ser = serial.Serial(port, baudrate=baud, timeout=timeout, write_timeout=timeout)

        # Give Pico time to reboot after opening the port
        time.sleep(1.5)

        # If the board is sitting in REPL, try a soft reset to run main.py
        self._soft_reset()
        time.sleep(1.0)

        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def _require(self):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Not connected to Pico. Click Connect first.")

    def _readline(self) -> str:
        self._require()
        line = self.ser.readline()
        if not line:
            return ""
        try:
            return line.decode("utf-8", errors="replace").strip()
        except Exception:
            return str(line)

    def _soft_reset(self):
        if not self.ser or not self.ser.is_open:
            return
        try:
            # Ctrl-C twice to break out of any running code, then Ctrl-D for soft reset
            self.ser.write(b"\x03\x03")
            self.ser.flush()
            time.sleep(0.1)
            self.ser.write(b"\x04")
            self.ser.flush()
        except Exception:
            pass

    def ping(self) -> str:
        self._require()
        with self._lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception:
                pass
            self.ser.write(b"PING\n")
            self.ser.flush()
            deadline = time.monotonic() + 5.0
            last = ""
            while time.monotonic() < deadline:
                line = self._readline()
                if not line:
                    continue
                last = line
                if line == "PONG":
                    return line
            # Try a soft reset once if no response
            if not last:
                self._soft_reset()
                time.sleep(1.0)
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
                self.ser.write(b"PING\n")
                self.ser.flush()
                retry_deadline = time.monotonic() + 3.0
                while time.monotonic() < retry_deadline:
                    line = self._readline()
                    if not line:
                        continue
                    if line == "PONG":
                        return line
                return "ERR no response after reset"
            return last or "ERR no response"

    def put_json(self, filename: str, json_text: str) -> str:
        self._require()
        data = json_text.encode("utf-8")
        header = f"PUT {filename} {len(data)}\n".encode("utf-8")
        with self._lock:
            self.ser.write(header)
            self.ser.write(data)
            self.ser.flush()
            self.last_filename = filename
            return self._readline()

    def run(self, filename: Optional[str] = None) -> str:
        self._require()
        fn = filename or self.last_filename
        with self._lock:
            self.ser.write(f"RUN {fn}\n".encode("utf-8"))
            self.ser.flush()
            return self._readline()

    def wait_done(self, timeout_s: float = 120.0) -> str:
        self._require()
        import time as _t
        t0 = _t.time()
        while True:
            if (_t.time() - t0) > timeout_s:
                return "ERR timeout waiting for DONE"
            with self._lock:
                line = self._readline()
            if not line:
                continue
            if line.startswith("DONE"):
                return line
            if line.startswith("ERR"):
                return line

    def stop(self) -> str:
        self._require()
        with self._lock:
            self.ser.write(b"STOP\n")
            self.ser.flush()
            return self._readline()

    def pause(self) -> str:
        self._require()
        with self._lock:
            self.ser.write(b"PAUSE\n")
            self.ser.flush()
            return self._readline()

    def resume(self) -> str:
        self._require()
        with self._lock:
            self.ser.write(b"RESUME\n")
            self.ser.flush()
            return self._readline()


# ----------------------------
# GUI
# ----------------------------
class ProfileBuilderApp(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly")
        self.title("Position Profile Builder")
        self.geometry("1450x900")

        self.num_positions = 10
        self.default_isolator_gpios = list(range(1, self.num_positions + 1))
        self.default_dut_gpios = list(range(21, 21 + self.num_positions))

        self.profile_name = tk.StringVar(value="New Profile")
        self.waveform_unit = tk.StringVar(value="ms")
        self.row_delay_ms = tk.DoubleVar(value=0.0)
        self.cycles_var = tk.IntVar(value=1)

        self.schedule_rows: List[Tuple[tk.StringVar, tk.DoubleVar, tk.DoubleVar, tb.Frame]] = []

        self.iso_digital: List[Tuple[float, int]] = []
        self.dut_digital: List[Tuple[float, int]] = []
        self.iso_display: List[Tuple[float, float]] = []
        self.dut_display: List[Tuple[float, float]] = []
        self.iso_has_ramps = False
        self.dut_has_ramps = False
        self.cycle_length_ms = 0.0

        self.pos_enabled_vars: List[tk.BooleanVar] = []
        self.pos_iso_gpio_vars: List[tk.IntVar] = []
        self.pos_dut_gpio_vars: List[tk.IntVar] = []
        self.pos_offset_vars: List[tk.DoubleVar] = []

        # Pico
        self.pico = PicoLink()
        self.pico_port = tk.StringVar(value="/dev/ttyACM0")
        self.pico_baud = tk.IntVar(value=115200)
        self.pico_status = tk.StringVar(value="Pico: Disconnected")
        self.pico_filename = tk.StringVar(value="profile.json")

        self._pico_q = queue.Queue()
        self._pico_run_thread: Optional[threading.Thread] = None
        self._pico_is_running = False
        self._pico_is_paused = False

        self._build_layout()
        self._init_positions()

        # Starter example
        self._add_schedule_row("Isolator On", 0, 300)
        self._add_schedule_row("DUT Hold Time", 80, 200)
        self._add_schedule_row("DUT Off Time", 280, 120)
        self._add_schedule_row("Cycle Delay", 400, 200)

        self._rebuild_and_preview()

    def _build_layout(self):
        top = tb.Frame(self, padding=10)
        top.pack(side=TOP, fill=X)

        tb.Label(top, text="Profile Name:").pack(side=LEFT)
        tb.Entry(top, textvariable=self.profile_name, width=25).pack(side=LEFT, padx=(5, 15))

        tb.Label(top, text="Units:").pack(side=LEFT)
        unit_combo = tb.Combobox(top, textvariable=self.waveform_unit, values=["ms", "sec", "min"], width=6, state="readonly")
        unit_combo.pack(side=LEFT, padx=(5, 15))
        unit_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_and_preview())

        tb.Label(top, text="Cycles:").pack(side=LEFT)
        cycles_entry = tb.Entry(top, textvariable=self.cycles_var, width=6)
        cycles_entry.pack(side=LEFT, padx=(5, 15))
        cycles_entry.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        cycles_entry.bind("<Return>", lambda _e: self._rebuild_and_preview())

        tb.Button(top, text="Load Profile JSON", bootstyle=PRIMARY, command=self._on_load_profile).pack(side=LEFT)
        tb.Button(top, text="Save Profile JSON", bootstyle=SUCCESS, command=self._on_save_profile).pack(side=LEFT, padx=(10, 0))

        mid = tb.Panedwindow(self, orient=HORIZONTAL)
        mid.pack(fill=BOTH, expand=YES)

        left = tb.Frame(mid, padding=10)
        right = tb.Frame(mid, padding=10)
        mid.add(left, weight=1)
        mid.add(right, weight=2)

        # Pico Panel
        pico_box = tb.Labelframe(left, text="Pico (Export + Run)", padding=10)
        pico_box.pack(fill=X, pady=(0, 10))

        row1 = tb.Frame(pico_box)
        row1.pack(fill=X, pady=2)
        tb.Label(row1, text="COM Port:", width=12, anchor=W).pack(side=LEFT)
        tb.Entry(row1, textvariable=self.pico_port, width=10).pack(side=LEFT, padx=(0, 8))
        tb.Label(row1, text="Baud:", width=6, anchor=W).pack(side=LEFT)
        tb.Entry(row1, textvariable=self.pico_baud, width=8).pack(side=LEFT)

        row2 = tb.Frame(pico_box)
        row2.pack(fill=X, pady=2)
        tb.Label(row2, text="File on Pico:", width=12, anchor=W).pack(side=LEFT)
        tb.Entry(row2, textvariable=self.pico_filename, width=18).pack(side=LEFT)

        row3 = tb.Frame(pico_box)
        row3.pack(fill=X, pady=(6, 2))
        self.btn_connect = tb.Button(row3, text="Connect", command=self._pico_connect)
        self.btn_connect.pack(side=LEFT)
        self.btn_ping = tb.Button(row3, text="Ping", command=self._pico_ping)
        self.btn_ping.pack(side=LEFT, padx=(6, 0))
        self.btn_export = tb.Button(row3, text="Export to Pico", bootstyle=SUCCESS, command=self._pico_export_current)
        self.btn_export.pack(side=LEFT, padx=(12, 0))
        self.btn_run = tb.Button(row3, text="Run on Pico", bootstyle=PRIMARY, command=self._pico_run)
        self.btn_run.pack(side=LEFT, padx=(6, 0))
        self.btn_pause = tb.Button(row3, text="Pause", bootstyle=WARNING, command=self._pico_pause)
        self.btn_pause.pack(side=LEFT, padx=(6, 0))
        self.btn_resume = tb.Button(row3, text="Resume", bootstyle=INFO, command=self._pico_resume)
        self.btn_resume.pack(side=LEFT, padx=(6, 0))
        self.btn_stop = tb.Button(row3, text="Stop", bootstyle=DANGER, command=self._pico_stop)
        self.btn_stop.pack(side=LEFT, padx=(6, 0))

        tb.Label(pico_box, textvariable=self.pico_status).pack(anchor=W, pady=(6, 0))

        # Schedule builder
        sched_box = tb.Labelframe(left, text="Waveform Blocks (overlap allowed)", padding=10)
        sched_box.pack(fill=X, pady=(0, 10))

        header = tb.Frame(sched_box)
        header.pack(fill=X)
        tb.Label(header, text="Event", width=22).pack(side=LEFT)
        tb.Label(header, text="Start", width=10).pack(side=LEFT)
        tb.Label(header, text="Duration", width=10).pack(side=LEFT)

        # ✅ scrollable schedule area
        self.sched_scroll = ScrolledFrame(sched_box, autohide=True, height=260)
        self.sched_scroll.pack(fill=BOTH, expand=YES, pady=(6, 0))

        self.sched_container = tb.Frame(self.sched_scroll)
        self.sched_container.pack(fill=BOTH, expand=YES)

        btns = tb.Frame(sched_box)
        btns.pack(fill=X, pady=(10, 0))
        tb.Button(btns, text="+ Add block", command=self._add_schedule_row).pack(side=LEFT)
        tb.Button(btns, text="Rebuild", command=self._rebuild_and_preview).pack(side=LEFT, padx=(10, 0))

        # Apply across positions
        apply_box = tb.Labelframe(left, text="Apply Across Positions", padding=10)
        apply_box.pack(fill=X, pady=(0, 10))
        self._labeled_entry(apply_box, "Row delay between positions (ms):", self.row_delay_ms)

        # Positions
        pos_frame = tb.Labelframe(left, text="Positions", padding=10)
        pos_frame.pack(fill=BOTH, expand=YES)

        self.pos_scroll = ScrolledFrame(pos_frame, autohide=True)
        self.pos_scroll.pack(fill=BOTH, expand=YES)

        pheader = tb.Frame(self.pos_scroll)
        pheader.pack(fill=X, pady=(0, 4))
        for txt, w in [("Use", 5), ("Pos", 5), ("Isolator GPIO", 12), ("DUT GPIO", 10), ("DUT Offset (ms)", 13)]:
            tb.Label(pheader, text=txt, width=w).pack(side=LEFT)

        self.pos_rows_container = tb.Frame(self.pos_scroll)
        self.pos_rows_container.pack(fill=BOTH, expand=YES)

        # Preview
        preview_box = tb.Labelframe(right, text="Preview", padding=10)
        preview_box.pack(fill=BOTH, expand=YES)

        self.summary_lbl = tb.Label(preview_box, text="", justify=LEFT)
        self.summary_lbl.pack(anchor=W, pady=(0, 8))

        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=preview_box)
        self.canvas.get_tk_widget().pack(fill=BOTH, expand=YES)

        self._update_pico_button_states()

    def _update_pico_button_states(self):
        connected = bool(self.pico.ser and self.pico.ser.is_open)
        running = self._pico_is_running
        paused = self._pico_is_paused

        self.btn_connect.config(state=("normal" if not running else "disabled"))
        self.btn_ping.config(state=("normal" if connected and not running else "disabled"))
        self.btn_export.config(state=("normal" if connected and not running else "disabled"))
        self.btn_run.config(state=("normal" if connected and not running else "disabled"))
        self.btn_pause.config(state=("normal" if connected and running and not paused else "disabled"))
        self.btn_resume.config(state=("normal" if connected and running and paused else "disabled"))
        self.btn_stop.config(state=("normal" if connected and running else "disabled"))

    def _labeled_entry(self, parent, label, var):
        r = tb.Frame(parent)
        r.pack(fill=X, pady=2)
        tb.Label(r, text=label, width=28, anchor=W).pack(side=LEFT)
        e = tb.Entry(r, textvariable=var, width=10)
        e.pack(side=LEFT)
        e.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        e.bind("<Return>", lambda _e: self._rebuild_and_preview())

    def _add_schedule_row(self, default_event: str = None, start: float = 0.0, duration: float = 0.0):
        ev_var = tk.StringVar(value=default_event or EVENTS[0])
        st_var = tk.DoubleVar(value=float(start))
        du_var = tk.DoubleVar(value=float(duration))

        row = tb.Frame(self.sched_container)
        row.pack(fill=X, pady=2)

        cb = tb.Combobox(row, textvariable=ev_var, values=EVENTS, state="readonly", width=22)
        cb.pack(side=LEFT)

        st = tb.Entry(row, textvariable=st_var, width=10)
        st.pack(side=LEFT, padx=(6, 0))

        du = tb.Entry(row, textvariable=du_var, width=10)
        du.pack(side=LEFT, padx=(6, 0))

        def remove():
            for i, (_a, _b, _c, frame) in enumerate(self.schedule_rows):
                if frame is row:
                    self.schedule_rows.pop(i)
                    break
            row.destroy()
            self._rebuild_and_preview()

        tb.Button(row, text="Remove", bootstyle=SECONDARY, command=remove).pack(side=LEFT, padx=(10, 0))

        cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_and_preview())
        st.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        du.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
        st.bind("<Return>", lambda _e: self._rebuild_and_preview())
        du.bind("<Return>", lambda _e: self._rebuild_and_preview())

        self.schedule_rows.append((ev_var, st_var, du_var, row))

    def _clear_schedule_rows(self):
        for _ev_var, _st_var, _du_var, frame in self.schedule_rows:
            frame.destroy()
        self.schedule_rows.clear()

    def _init_positions(self):
        for w in self.pos_rows_container.winfo_children():
            w.destroy()

        self.pos_enabled_vars.clear()
        self.pos_iso_gpio_vars.clear()
        self.pos_dut_gpio_vars.clear()
        self.pos_offset_vars.clear()

        for i in range(self.num_positions):
            pos = i + 1
            enabled = tk.BooleanVar(value=(pos <= 3))
            iso_gpio = tk.IntVar(value=self.default_isolator_gpios[i] if i < len(self.default_isolator_gpios) else (i + 1))
            dut_gpio = tk.IntVar(value=self.default_dut_gpios[i] if i < len(self.default_dut_gpios) else (21 + i))
            offset = tk.DoubleVar(value=0.0)

            self.pos_enabled_vars.append(enabled)
            self.pos_iso_gpio_vars.append(iso_gpio)
            self.pos_dut_gpio_vars.append(dut_gpio)
            self.pos_offset_vars.append(offset)

            row = tb.Frame(self.pos_rows_container)
            row.pack(fill=X, pady=1)

            tb.Checkbutton(row, variable=enabled, command=self._rebuild_and_preview, width=5).pack(side=LEFT)
            tb.Label(row, text=str(pos), width=5).pack(side=LEFT)

            for var, wcol in [(iso_gpio, 12), (dut_gpio, 10), (offset, 13)]:
                e = tb.Entry(row, textvariable=var, width=wcol)
                e.pack(side=LEFT)
                e.bind("<FocusOut>", lambda _e: self._rebuild_and_preview())
                e.bind("<Return>", lambda _e: self._rebuild_and_preview())

    def _get_positions(self) -> List[PositionConfig]:
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
        events: List[ScheduledEvent] = []
        for ev_var, st_var, du_var, _frame in self.schedule_rows:
            events.append(ScheduledEvent(ev_var.get(), float(st_var.get()), float(du_var.get())))
        return events

    def _rebuild_and_preview(self):
        self.ax.clear()
        self.ax.grid(True)

        unit = self.waveform_unit.get()
        schedule = self._get_schedule()

        try:
            cycles = int(self.cycles_var.get())
        except Exception:
            cycles = 1

        try:
            (self.iso_digital, self.dut_digital,
             self.iso_display, self.dut_display,
             self.iso_has_ramps, self.dut_has_ramps,
             self.cycle_length_ms) = build_waveforms_from_schedule(schedule, unit, cycles)
        except Exception as e:
            self.summary_lbl.config(text=f"Waveform error: {e}")
            self.ax.text(0.5, 0.5, str(e), ha="center", va="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        positions = self._pico_positions = self._get_positions()

        channels = build_preview_channels(
            positions=positions,
            row_delay_ms=float(self.row_delay_ms.get()),
            iso_display=self.iso_display,
            dut_display=self.dut_display,
            iso_digital=self.iso_digital,
            dut_digital=self.dut_digital,
        )

        enabled_count = sum(1 for p in positions if p.enabled)

        self.summary_lbl.config(
            text=(
                f"Units: {unit} | Cycles: {cycles} | Base cycle length: {self.cycle_length_ms:.1f} ms\n"
                f"Enabled positions: {enabled_count} | Row delay: {self.row_delay_ms.get()} ms\n"
                f"Cycle Delay blocks are OFF windows and are skipped on the final cycle."
            )
        )

        if not channels:
            self.ax.text(0.5, 0.5, "No positions enabled.", ha="center", va="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        labels = list(channels.keys())
        for yi, label in enumerate(labels):
            payload = channels[label]
            is_iso = label.startswith("ISO")
            has_ramps = self.iso_has_ramps if is_iso else self.dut_has_ramps

            if has_ramps:
                t = payload["display_t"]
                v = payload["display_v"]
                self.ax.plot(t, [val + yi * 2 for val in v])
            else:
                t = payload["digital_t"]
                v = payload["digital_v"]
                self.ax.step(t, [val + yi * 2 for val in v], where="post")

        self.ax.set_yticks([yi * 2 + 0.5 for yi in range(len(labels))])
        self.ax.set_yticklabels(labels, fontsize=8)
        self.ax.set_xlabel("Time (ms)")
        self.ax.set_title("Preview")
        self.fig.tight_layout()
        self.canvas.draw()

    def _build_profile_object(self) -> Profile:
        positions = self._get_positions()
        if not any(p.enabled for p in positions):
            raise ValueError("Enable at least one position.")

        schedule = self._get_schedule()
        if not schedule:
            raise ValueError("Add at least one schedule block.")

        unit = self.waveform_unit.get()

        try:
            cycles = int(self.cycles_var.get())
        except Exception:
            raise ValueError("Cycles must be an integer >= 1.")

        if cycles < 1:
            raise ValueError("Cycles must be >= 1.")

        iso_dig, dut_dig, *_ = build_waveforms_from_schedule(schedule, unit, cycles)

        return Profile(
            profile_name=self.profile_name.get().strip() or "Profile",
            waveform_time_units=unit,
            scheduled_events=schedule,
            isolator_waveform_points=[(float(t), int(s)) for t, s in iso_dig],
            dut_waveform_points=[(float(t), int(s)) for t, s in dut_dig],
            row_delay_ms=float(self.row_delay_ms.get()),
            cycles=cycles,
            positions=positions,
        )

    def _profile_to_json_text(self, prof: Profile) -> str:
        data = asdict(prof)
        data["positions"] = [asdict(p) for p in prof.positions]
        data["scheduled_events"] = [asdict(ev) for ev in prof.scheduled_events]
        return json.dumps(data, indent=2)

    def _on_save_profile(self):
        try:
            prof = self._build_profile_object()
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            return

        save_path = filedialog.asksaveasfilename(
            title="Save Profile JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if not save_path:
            return

        try:
            json_text = self._profile_to_json_text(prof)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(json_text)
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            return

        messagebox.showinfo("Saved", f"Profile saved:\n{save_path}")

    def _on_load_profile(self):
        path = filedialog.askopenfilename(
            title="Load Profile JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not read JSON:\n{e}")
            return

        try:
            self.profile_name.set(data.get("profile_name", "Profile"))
            self.waveform_unit.set(data.get("waveform_time_units", "ms"))
            self.row_delay_ms.set(float(data.get("row_delay_ms", 0.0)))
            self.cycles_var.set(int(data.get("cycles", 1)))

            sched = data.get("scheduled_events", [])
            if not isinstance(sched, list):
                raise ValueError("scheduled_events must be a list")

            self._clear_schedule_rows()
            for ev in sched:
                event = ev.get("event", EVENTS[0])
                start = float(ev.get("start", 0.0))
                duration = float(ev.get("duration", 0.0))
                if event not in EVENTS:
                    raise ValueError(f"Unknown event in file: {event}")
                self._add_schedule_row(event, start, duration)

            pos_list = data.get("positions", [])
            if not isinstance(pos_list, list):
                raise ValueError("positions must be a list")

            if len(pos_list) > 0:
                self.num_positions = len(pos_list)
                self.default_isolator_gpios = list(range(1, self.num_positions + 1))
                self.default_dut_gpios = list(range(21, 21 + self.num_positions))
                self._init_positions()

                for i, p in enumerate(pos_list):
                    if i >= self.num_positions:
                        break
                    self.pos_enabled_vars[i].set(bool(p.get("enabled", False)))
                    self.pos_iso_gpio_vars[i].set(int(p.get("isolator_gpio", i + 1)))
                    self.pos_dut_gpio_vars[i].set(int(p.get("dut_gpio", 21 + i)))
                    self.pos_offset_vars[i].set(float(p.get("dut_offset_ms", 0.0)))

        except Exception as e:
            messagebox.showerror("Load Error", f"Profile format error:\n{e}")
            return

        self._rebuild_and_preview()

    # ----------------------------
    # Pico UI actions
    # ----------------------------
    def _pico_set_status(self, text: str):
        self.pico_status.set(f"Pico: {text}")

    def _pico_connect(self):
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
        try:
            prof = self._build_profile_object()
            json_text = self._profile_to_json_text(prof)

            filename = self.pico_filename.get().strip() or "profile.json"
            resp = self.pico.put_json(filename, json_text)

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
        if self._pico_run_thread and self._pico_run_thread.is_alive():
            messagebox.showinfo("Pico", "Pico is already running a profile.")
            return

        try:
            filename = self.pico_filename.get().strip() or "profile.json"
            resp = self.pico.run(filename)
            if not resp.startswith("OK"):
                self._pico_set_status(f"Run failed: {resp}")
                messagebox.showerror("Pico Run Error", resp or "No response from Pico.")
                return

            self._pico_is_running = True
            self._pico_is_paused = False
            self._update_pico_button_states()
            self._pico_set_status(f"Running {filename}...")

            def worker():
                done = self.pico.wait_done(timeout_s=300.0)
                self._pico_q.put(("done", filename, done))

            self._pico_run_thread = threading.Thread(target=worker, daemon=True)
            self._pico_run_thread.start()
            self.after(50, self._poll_pico_queue)

        except Exception as e:
            messagebox.showerror("Pico Run Error", str(e))
            self._pico_is_running = False
            self._pico_is_paused = False
            self._update_pico_button_states()

    def _poll_pico_queue(self):
        try:
            while True:
                kind, filename, msg = self._pico_q.get_nowait()
                if kind == "done":
                    self._pico_is_running = False
                    self._pico_is_paused = False
                    self._update_pico_button_states()

                    if msg.startswith("DONE"):
                        self._pico_set_status(f"Done: {filename}")
                    else:
                        self._pico_set_status(f"Run error: {msg}")
                        messagebox.showerror("Pico Run Error", msg)
        except queue.Empty:
            pass

        if self._pico_run_thread and self._pico_run_thread.is_alive():
            self.after(50, self._poll_pico_queue)

    def _pico_pause(self):
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


if __name__ == "__main__":
    app = ProfileBuilderApp()
    app.mainloop()
