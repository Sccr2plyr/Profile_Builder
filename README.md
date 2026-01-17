# Pico Profile Builder

PC GUI for building waveform profiles and exporting/running them on a Raspberry Pi Pico over serial.

## Project Layout

- `app.py` — GUI entry point
- `pc_app/waveform_profile_builder.py` — main GUI + Pico protocol
- `pico_firmware/main.py` — MicroPython firmware (copy to Pico as `main.py`)
- `requirements.txt` — Python dependencies

## Setup (PC)

```bash
pip install -r requirements.txt
```

## Setup (Pico)

Copy `pico_firmware/main.py` to the Pico as `main.py` (e.g., via Thonny or rshell).

> Close Thonny after copying — it holds the serial port.

## Run

```bash
python app.py
```

Default serial port is `/dev/ttyACM0`. Change it in the GUI if needed.

## Notes

- The app sends `PING`, `PUT`, `RUN`, `STOP`, `PAUSE`, `RESUME`.
- The firmware also accepts `QUIT` to exit its loop if you’re running it from REPL.
