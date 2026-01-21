"""
Configuration constants for Profile Builder.
"""

# ===========================
# Hardware Configuration
# ===========================

# Default GPIO pin assignments
DEFAULT_NUM_POSITIONS = 10
DEFAULT_ISOLATOR_GPIO_START = 1  # Isolator pins: 1-10
DEFAULT_DUT_GPIO_START = 21      # DUT pins: 21-30

# Auxiliary output defaults
DEFAULT_AUXILIARY_GPIO_START = 15  # Auxiliary pins start at 15
DEFAULT_AUXILIARY_OUTPUTS = [
    ("Power Supply 1", 15),
    ("Power Supply 2", 16),
]

# Serial communication defaults
DEFAULT_COM_PORT_LINUX = "/dev/ttyACM0"
DEFAULT_COM_PORT_WINDOWS = "COM3"
DEFAULT_BAUD_RATE = 115200
DEFAULT_SERIAL_TIMEOUT = 1.0

# ===========================
# Waveform Settings
# ===========================

# Time units available in the GUI
TIME_UNITS = ["ms", "sec", "min"]
DEFAULT_TIME_UNIT = "ms"

# Unit conversions to milliseconds
UNIT_TO_MS = {
    "ms": 1.0,
    "sec": 1000.0,
    "min": 60000.0,
}

# Event types available in schedule builder
EVENT_TYPES = [
    "Isolator On",
    "Isolator Off",
    "DUT ON Time",
    "DUT Off Time",
    "Cycle Delay",
]

# Event rise/fall times (milliseconds)
ISOLATOR_ON_RISE_MS = 5.0
ISOLATOR_OFF_FALL_MS = 3.0
DUT_ON_RISE_MS = 2.0
DUT_OFF_FALL_MS = 2.0

# ===========================
# GUI Settings
# ===========================

# Application window
APP_TITLE = "Position Profile Builder"
APP_WIDTH = 1450
APP_HEIGHT = 900
APP_THEME = "flatly"  # ttkbootstrap theme

# Default profile settings
DEFAULT_PROFILE_NAME = "New Profile"
DEFAULT_ROW_DELAY_MS = 0.0
DEFAULT_BLOCK_NAME = "Block"
DEFAULT_CYCLES = 1

# Number of positions enabled by default
DEFAULT_ENABLED_POSITIONS = 3

# ===========================
# File Settings
# ===========================

# Default filenames
DEFAULT_PICO_FILENAME = "profile.json"

# File extensions
PROFILE_FILE_EXTENSION = ".json"

# ===========================
# Visualization Settings
# ===========================

# Matplotlib figure size
FIGURE_WIDTH = 7
FIGURE_HEIGHT = 6
FIGURE_DPI = 100

# Channel vertical spacing in preview
CHANNEL_VERTICAL_SPACING = 2.0

# Block boundary line style
BLOCK_BOUNDARY_COLOR = "red"
BLOCK_BOUNDARY_STYLE = "--"
BLOCK_BOUNDARY_ALPHA = 0.5
BLOCK_BOUNDARY_WIDTH = 1
