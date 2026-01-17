# Pico main.py (MicroPython)
# Supports: PING, PUT, RUN, STOP, PAUSE, RESUME

import sys
import json
import time
import machine

try:
    import uselect
except ImportError:
    uselect = None

def _writeln(s):
    try:
        sys.stdout.write(s + "\n")
        sys.stdout.flush()
        try:
            with open("debug_log.txt", "a") as dbg:
                dbg.write("OUT: {}\n".format(s))
        except Exception:
            pass
    except Exception:
        pass

def _readline_blocking():
    try:
        return sys.stdin.readline()
    except Exception:
        return ""

def _read_exact_str(n):
    buf = ""
    while len(buf) < n:
        chunk = sys.stdin.read(n - len(buf))
        if not chunk:
            time.sleep_ms(1)
            continue
        buf += chunk
    return buf

def _poll_line_nonblocking():
    if uselect is None:
        return ""
    try:
        p = uselect.poll()
        p.register(sys.stdin, uselect.POLLIN)
        if not p.poll(0):
            return ""
        return sys.stdin.readline()
    except Exception:
        return ""

_stop = False
_paused = False

def _set_stop(v):
    global _stop
    _stop = v

def _get_stop():
    return _stop

def _set_paused(v):
    global _paused
    _paused = v

def _get_paused():
    return _paused

def _safe_all_low(pin_map):
    for _g, p in pin_map.items():
        try:
            p.value(0)
        except Exception:
            pass

def _validate_profile(d):
    for k in ("positions", "row_delay_ms", "isolator_waveform_points", "dut_waveform_points"):
        if k not in d:
            raise ValueError("Missing key: {}".format(k))
    if not isinstance(d["positions"], list):
        raise ValueError("positions must be a list")

def _clean_points(points):
    pts = []
    for it in points:
        if not isinstance(it, (list, tuple)) or len(it) != 2:
            continue
        t = int(round(float(it[0])))
        s = 1 if int(it[1]) else 0
        pts.append((t, s))
    pts.sort()  # no-arg sort
    cleaned = []
    last = None
    for t, s in pts:
        if last is None or s != last:
            cleaned.append((t, s))
            last = s
    if not cleaned:
        cleaned = [(0, 0)]
    if cleaned[0][0] > 0:
        cleaned.insert(0, (0, 0))
    return cleaned

def _build_events(profile):
    positions = profile["positions"]
    row_delay_ms = int(round(float(profile.get("row_delay_ms", 0.0))))

    iso_pts = _clean_points(profile["isolator_waveform_points"])
    dut_pts = _clean_points(profile["dut_waveform_points"])

    enabled = []
    for p in positions:
        if bool(p.get("enabled", False)):
            enabled.append(p)
    if not enabled:
        raise ValueError("No positions enabled")

    events = []  # (t_ms, gpio, state)
    for idx, p in enumerate(enabled):
        base_shift = idx * row_delay_ms
        dut_offset = int(round(float(p.get("dut_offset_ms", 0.0))))
        iso_gpio = int(p["isolator_gpio"])
        dut_gpio = int(p["dut_gpio"])

        for t, s in iso_pts:
            events.append((t + base_shift, iso_gpio, s))
        for t, s in dut_pts:
            events.append((t + base_shift + dut_offset, dut_gpio, s))

    events.sort()  # no-arg sort
    return events

def _run_profile_file(path):
    _set_stop(False)
    _set_paused(False)

    with open(path, "r") as f:
        prof = json.load(f)
    _validate_profile(prof)

    events = _build_events(prof)

    pins = {}
    for _t, gpio, _s in events:
        if gpio not in pins:
            pins[gpio] = machine.Pin(gpio, machine.Pin.OUT)
            pins[gpio].value(0)

    _safe_all_low(pins)

    t0 = time.ticks_ms()
    pause_start = 0

    i = 0
    n = len(events)

    while i < n:
        # process incoming commands while running
        line = _poll_line_nonblocking()
        if line:
            cmd = line.strip()
            if cmd == "STOP":
                _set_stop(True)
                _writeln("OK STOP")
            elif cmd == "PAUSE":
                if not _get_paused():
                    _set_paused(True)
                    pause_start = time.ticks_ms()
                _writeln("OK PAUSE")
            elif cmd == "RESUME":
                if _get_paused():
                    now = time.ticks_ms()
                    paused_ms = time.ticks_diff(now, pause_start)
                    # shift baseline so elapsed time "freezes" during pause
                    t0 = time.ticks_add(t0, paused_ms)
                    _set_paused(False)
                _writeln("OK RESUME")
            # ignore other commands during run

        if _get_stop():
            _safe_all_low(pins)
            return "STOPPED"

        if _get_paused():
            time.sleep_ms(5)
            continue

        t_ms, _gpio, _state = events[i]
        elapsed = time.ticks_diff(time.ticks_ms(), t0)

        if elapsed < t_ms:
            time.sleep_ms(1)
            continue

        same_t = t_ms
        while i < n and events[i][0] == same_t:
            _, g, s = events[i]
            try:
                pins[g].value(1 if s else 0)
            except Exception:
                pass
            i += 1

    _safe_all_low(pins)
    return "DONE"

def main():
    # Quiet startup (no READY)
    while True:
        line = _readline_blocking()
        try:
            with open("debug_log.txt", "a") as dbg:
                dbg.write("IN: {}\n".format(repr(line)))
        except Exception:
            pass
        if not line:
            time.sleep_ms(10)
            continue

        cmd = line.strip()
        if not cmd:
            continue

        if cmd == "PING":
            _writeln("PONG")
            continue

        if cmd == "STOP":
            _set_stop(True)
            _writeln("OK STOP")
            continue

        if cmd == "PAUSE":
            _set_paused(True)
            _writeln("OK PAUSE")
            continue

        if cmd == "RESUME":
            _set_paused(False)
            _writeln("OK RESUME")
            continue

        if cmd == "QUIT":
            _writeln("OK QUIT")
            break

        if cmd.startswith("PUT "):
            parts = cmd.split()
            if len(parts) != 3:
                _writeln("ERR PUT format")
                continue

            filename = parts[1]
            try:
                nbytes = int(parts[2])
            except Exception:
                _writeln("ERR PUT nbytes")
                continue

            try:
                raw_str = _read_exact_str(nbytes)
                obj = json.loads(raw_str)
                with open(filename, "w") as f:
                    json.dump(obj, f)
                _writeln("OK PUT")
            except Exception as e:
                _writeln("ERR {}".format(e))
            continue

        if cmd.startswith("RUN "):
            parts = cmd.split(" ", 1)
            if len(parts) != 2:
                _writeln("ERR RUN format")
                continue

            filename = parts[1].strip()
            try:
                _writeln("OK RUN")
                res = _run_profile_file(filename)
                _writeln("DONE {}".format(res))
            except Exception as e:
                _writeln("ERR {}".format(e))
            continue

        _writeln("ERR Unknown command")

    return

main()
