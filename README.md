# Profile Builder

A comprehensive waveform profile builder for Raspberry Pi Pico testing with multi-block sequential execution, real-time visualization, and serial communication.

## ✨ Features

- **Test Blocks**: Create multiple independent waveform blocks that execute sequentially
- **Real-time Preview**: Matplotlib visualization with block boundaries
- **Multi-Position**: Configure up to 10 test positions with independent GPIO control
- **Serial Communication**: Upload and run profiles on Raspberry Pi Pico hardware
- **Save/Load**: JSON-based profile persistence with backward compatibility
- **Modular Architecture**: Clean separation of concerns (GUI, models, waveform engine, hardware)

## 📁 Project Structure

```
Profile_Builder/
├── pc_app/                          # Main Python package
│   ├── models.py                    # Data structures
│   ├── waveform_engine.py           # Waveform generation
│   ├── pico_serial.py               # Serial communication
│   ├── utils.py                     # Helper functions
│   ├── config.py                    # Configuration constants
│   └── waveform_profile_builder.py  # Main GUI application
├── pico_firmware/                   # Raspberry Pi Pico firmware
│   └── main.py                      # MicroPython code
├── tests/                           # Unit tests
│   ├── test_models.py
│   └── test_waveform_engine.py
├── examples/                        # Sample profiles
│   └── example_profile.json
├── app.py                           # Application entry point
├── setup.py                         # Package installation
├── pyproject.toml                   # Modern Python packaging
├── requirements.txt                 # Runtime dependencies
├── requirements-dev.txt             # Development dependencies
└── README.md                        # This file
```

## 🚀 Quick Start

### PC Setup

```bash
# Clone the repository
git clone https://github.com/Sccr2plyr/Profile_Builder.git
cd Profile_Builder/Profile_Builder

# Create virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

### Pico Setup

1. Copy `pico_firmware/main.py` to your Raspberry Pi Pico as `main.py`
   - Use Thonny, rshell, or ampy to copy the file
   - **Important**: Close Thonny after copying to release the serial port

2. The Pico will automatically run the firmware on boot

## 📖 Usage

### Creating a Profile

1. **Add Blocks**: Click "+ Add Block" to create test sequences
   - Each block has independent waveform schedule and cycle count
   - Blocks execute sequentially (Block 1 → Block 2 → Block 3...)
   
2. **Configure Waveforms**: For each block:
   - Add schedule events (Isolator On/Off, DUT Hold/Off, Cycle Delay)
   - Set start times and durations
   - Adjust cycle count
   
3. **Configure Positions**: 
   - Enable/disable positions
   - Assign GPIO pins
   - Set time offsets

4. **Preview**: Real-time visualization shows all blocks with boundaries

5. **Save**: Export profile as JSON for later use

### Running on Pico

1. **Connect**: Enter COM port and click "Connect"
2. **Export**: Click "Export to Pico" to upload profile
3. **Run**: Click "Run on Pico" to start execution
4. **Control**: Use Pause/Resume/Stop during execution

## 🧪 Testing

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run with coverage
pytest --cov=pc_app --cov-report=html

# View coverage report
open htmlcov/index.html  # On Windows: start htmlcov/index.html
```

## 📦 Installation as Package

```bash
# Install in development mode
pip install -e .

# Or install from source
pip install .

# Run from anywhere
profile-builder
```

## 🔧 Configuration

Default settings can be modified in `pc_app/config.py`:
- GPIO pin assignments
- Serial communication parameters
- Time units and conversions
- Visualization settings
- Rise/fall times for events

## 📝 Serial Protocol

The Pico firmware supports the following commands:
- `PING` - Test connection (responds with "PONG")
- `PUT <filename> <size>` - Upload profile JSON
- `RUN <filename>` - Execute profile
- `STOP` - Stop execution
- `PAUSE` - Pause execution
- `RESUME` - Resume from pause
- `QUIT` - Exit (for REPL testing)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔄 Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

**Current Version: 2.0.0**
- Multi-block sequential execution
- Modular architecture
- Comprehensive test suite
- Improved packaging and documentation

## ⚠️ Notes

- Default serial port is `/dev/ttyACM0` (Linux) or `COM3` (Windows)
- Change port in GUI if your Pico uses a different port
- Ensure Thonny is closed before connecting from the GUI
- Waveforms are pre-computed on PC before upload
- Pico firmware does not need changes for new block feature
