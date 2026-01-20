"""
Pico Serial Communication Module
=================================
This module handles all serial communication with the Raspberry Pi Pico.

The Pico runs firmware that accepts text-based commands over USB serial
to upload profiles, execute waveforms, and control execution (pause/resume/stop).

Protocol Overview:
    PC -> Pico Commands:
        PING\n                           - Check if Pico is responsive
        PUT <filename> <nbytes>\n<data>  - Upload JSON profile to Pico
        RUN <filename>\n                 - Execute a profile
        PAUSE\n                          - Pause execution
        RESUME\n                         - Resume execution
        STOP\n                           - Stop execution
    
    Pico -> PC Responses:
        PONG\n                  - Response to PING
        OK PUT\n                - Profile uploaded successfully
        OK RUN\n                - Profile execution started
        OK PAUSE\n              - Execution paused
        OK RESUME\n             - Execution resumed
        OK STOP\n               - Execution stopped
        DONE <info>\n           - Profile execution completed
        ERR <message>\n         - Error occurred

Classes:
    PicoLink: Manages serial connection and command protocol with Pico

Notes:
    - Uses pyserial library for serial communication
    - Implements thread-safe command execution
    - Automatically handles Pico soft reset on connect
    - Supports timeout-based response waiting
"""

import threading
import time
from typing import Optional

try:
    import serial
except ImportError:
    serial = None


class PicoLink:
    """
    Manages serial communication with a Raspberry Pi Pico running profile firmware.
    
    This class provides a high-level interface for:
    - Connecting to the Pico over USB serial
    - Uploading JSON profile files
    - Running profiles on the Pico
    - Controlling execution (pause/resume/stop)
    - Checking connection status (ping)
    
    The class is thread-safe and can be used from multiple threads, though
    only one command should be executed at a time.
    
    Attributes:
        ser (Optional[serial.Serial]): The active serial connection, or None if disconnected
        port (str): The COM port name (e.g., "COM3" on Windows, "/dev/ttyACM0" on Linux)
        baud (int): The baud rate for serial communication (default: 115200)
        last_filename (str): The last filename used in PUT command (for convenience)
    
    Example:
        >>> pico = PicoLink()
        >>> pico.connect("COM3", baud=115200)
        >>> pico.ping()
        'PONG'
        >>> pico.put_json("test.json", '{"cycles": 1}')
        'OK PUT'
        >>> pico.run("test.json")
        'OK RUN'
        >>> pico.wait_done(timeout_s=60.0)
        'DONE cycles=1'
        >>> pico.close()
    """
    
    def __init__(self):
        """
        Initialize a new PicoLink instance.
        
        The connection is not opened until connect() is called.
        """
        # Serial connection object (serial.Serial or None if disconnected)
        self.ser = None
        self.port = ""                              # COM port name
        self.baud = 115200                          # Baud rate
        self.last_filename = "profile.json"         # Default filename
        self._lock = threading.Lock()               # Thread-safe command execution
    
    def connect(self, port: str, baud: int = 115200, timeout: float = 1.0):
        """
        Open a serial connection to the Pico.
        
        This method:
        1. Closes any existing connection
        2. Opens a new serial port connection
        3. Waits for the Pico to reboot (USB serial triggers reset)
        4. Performs a soft reset to ensure main.py is running
        5. Clears serial buffers
        
        Args:
            port (str): COM port name (e.g., "COM3", "/dev/ttyACM0")
            baud (int): Baud rate for communication (default: 115200)
            timeout (float): Read/write timeout in seconds (default: 1.0)
        
        Raises:
            RuntimeError: If pyserial is not installed
            serial.SerialException: If the port cannot be opened
        
        Example:
            >>> pico.connect("/dev/ttyACM0", baud=115200)
        
        Note:
            - Opening the serial port causes the Pico to reboot
            - The 1.5s delay is necessary for the Pico to boot and run main.py
            - Soft reset (Ctrl-D) ensures the Pico is in the correct state
        """
        # Check if pyserial is available
        if serial is None:
            raise RuntimeError("pyserial not installed. Run: pip install pyserial")
        
        # Close any existing connection
        if self.ser and self.ser.is_open:
            self.ser.close()
        
        # Store connection parameters
        self.port = port
        self.baud = baud
        
        # Open the serial port
        self.ser = serial.Serial(
            port, 
            baudrate=baud, 
            timeout=timeout, 
            write_timeout=timeout
        )
        
        # Wait for Pico to reboot after serial connection
        # (Opening the port triggers a reset on most Pico boards)
        time.sleep(1.5)
        
        # Perform a soft reset to ensure main.py is running
        # This is important if the Pico was in REPL mode
        self._soft_reset()
        time.sleep(1.0)
        
        # Clear any stale data from the serial buffers
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass  # Ignore buffer clear errors
    
    def close(self):
        """
        Close the serial connection to the Pico.
        
        This method safely closes the serial port and cleans up resources.
        It's safe to call even if no connection is open.
        
        Example:
            >>> pico.close()
        """
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass  # Ignore close errors
        self.ser = None
    
    def _require(self):
        """
        Internal method to verify a connection is open.
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Note:
            This is called by all command methods to ensure a valid connection.
        """
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Not connected to Pico. Click Connect first.")
    
    def _readline(self) -> str:
        """
        Read a line from the Pico with error handling.
        
        Returns:
            str: The line read from the Pico (stripped of whitespace),
                 or empty string if timeout or read error
        
        Note:
            - Uses the timeout specified in connect()
            - Handles decode errors gracefully
            - Strips whitespace from the result
        """
        self._require()
        
        # Read a line (blocking up to timeout)
        line = self.ser.readline()
        
        if not line:
            return ""
        
        # Decode with error handling
        try:
            return line.decode("utf-8", errors="replace").strip()
        except Exception:
            return str(line)  # Fallback to string representation
    
    def _soft_reset(self):
        """
        Send a soft reset command to the Pico.
        
        This sends the MicroPython soft reset sequence:
        - Ctrl-C twice (break out of any running code)
        - Ctrl-D (soft reset, runs main.py)
        
        This is useful for recovering from REPL mode and ensuring
        the profile runner firmware is active.
        
        Note:
            - Safe to call even if already in the correct mode
            - Does nothing if not connected
        """
        if not self.ser or not self.ser.is_open:
            return
        
        try:
            # Send Ctrl-C twice to interrupt any running code
            self.ser.write(b"\x03\x03")
            self.ser.flush()
            time.sleep(0.1)
            
            # Send Ctrl-D to perform soft reset
            self.ser.write(b"\x04")
            self.ser.flush()
        except Exception:
            pass  # Ignore reset errors
    
    def ping(self) -> str:
        """
        Check if the Pico is responsive by sending a PING command.
        
        This method:
        1. Clears serial buffers
        2. Sends "PING\n"
        3. Waits up to 5 seconds for "PONG" response
        4. If no response, tries a soft reset and retries once
        
        Returns:
            str: "PONG" if successful, or error message starting with "ERR"
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> response = pico.ping()
            >>> if response == "PONG":
            ...     print("Pico is responsive")
            ... else:
            ...     print(f"Ping failed: {response}")
        
        Note:
            - Thread-safe (uses internal lock)
            - Automatically attempts recovery via soft reset
            - 5 second initial timeout, 3 second retry timeout
        """
        self._require()
        
        with self._lock:
            # Clear any stale data
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception:
                pass
            
            # Send PING command
            self.ser.write(b"PING\n")
            self.ser.flush()
            
            # Wait for PONG response (up to 5 seconds)
            deadline = time.monotonic() + 5.0
            last = ""
            
            while time.monotonic() < deadline:
                line = self._readline()
                if not line:
                    continue
                
                last = line
                if line == "PONG":
                    return line
            
            # If we got no response at all, try a soft reset and retry
            if not last:
                self._soft_reset()
                time.sleep(1.0)
                
                # Clear buffers again
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
                
                # Retry PING once
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
            
            # Got a response but it wasn't PONG
            return last or "ERR no response"
    
    def put_json(self, filename: str, json_text: str) -> str:
        """
        Upload a JSON profile to the Pico's filesystem.
        
        This sends the PUT command with the specified filename and data.
        The Pico firmware will save the JSON to its local filesystem.
        
        Command format:
            PUT <filename> <nbytes>\n
            <json_text>
        
        Args:
            filename (str): Name to save the file as on the Pico (e.g., "profile.json")
            json_text (str): The JSON content to upload
        
        Returns:
            str: Response from Pico ("OK PUT" if successful, or error message)
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> profile_json = '{"cycles": 1, "positions": [...]}'
            >>> response = pico.put_json("myprofile.json", profile_json)
            >>> if response.startswith("OK"):
            ...     print("Upload successful")
        
        Note:
            - Thread-safe (uses internal lock)
            - Stores filename for later use with run()
            - Timeout depends on data size and baud rate
        """
        self._require()
        
        # Encode JSON text to bytes
        data = json_text.encode("utf-8")
        
        # Construct PUT command header
        header = f"PUT {filename} {len(data)}\n".encode("utf-8")
        
        with self._lock:
            # Send header
            self.ser.write(header)
            
            # Send JSON data
            self.ser.write(data)
            self.ser.flush()
            
            # Remember this filename for convenience
            self.last_filename = filename
            
            # Read response (should be "OK PUT" or error)
            return self._readline()
    
    def run(self, filename: Optional[str] = None) -> str:
        """
        Start executing a profile on the Pico.
        
        This sends the RUN command to start executing the specified profile.
        The profile must already be uploaded via put_json().
        
        Command format:
            RUN <filename>\n
        
        Args:
            filename (Optional[str]): Profile filename to run. If None, uses
                                     the last filename from put_json()
        
        Returns:
            str: Response from Pico ("OK RUN" if started, or error message)
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> pico.put_json("test.json", json_data)
            >>> response = pico.run("test.json")
            >>> if response.startswith("OK"):
            ...     print("Profile execution started")
            ...     done = pico.wait_done(timeout_s=120.0)
        
        Note:
            - Thread-safe (uses internal lock)
            - Does not wait for completion (use wait_done() for that)
            - The Pico will begin executing immediately after OK RUN
        """
        self._require()
        
        # Use provided filename or fall back to last uploaded file
        fn = filename or self.last_filename
        
        with self._lock:
            # Send RUN command
            self.ser.write(f"RUN {fn}\n".encode("utf-8"))
            self.ser.flush()
            
            # Read response (should be "OK RUN" or error)
            return self._readline()
    
    def wait_done(self, timeout_s: float = 120.0) -> str:
        """
        Wait for profile execution to complete.
        
        This method blocks until the Pico sends a DONE or ERR message,
        indicating that profile execution has finished.
        
        Expected responses:
            DONE <info>\n    - Execution completed successfully
            ERR <message>\n  - Execution failed
        
        Args:
            timeout_s (float): Maximum time to wait in seconds (default: 120.0)
        
        Returns:
            str: DONE or ERR message from Pico, or "ERR timeout" if timeout reached
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> pico.run("profile.json")
            >>> result = pico.wait_done(timeout_s=300.0)
            >>> if result.startswith("DONE"):
            ...     print("Profile completed successfully")
            ... else:
            ...     print(f"Error: {result}")
        
        Note:
            - Thread-safe (uses internal lock)
            - Blocks the calling thread until completion or timeout
            - Should be called from a background thread to avoid GUI freezing
        """
        self._require()
        
        # Record start time for timeout checking
        t0 = time.time()
        
        while True:
            # Check for timeout
            if (time.time() - t0) > timeout_s:
                return "ERR timeout waiting for DONE"
            
            # Read a line from the Pico
            with self._lock:
                line = self._readline()
            
            # Skip empty lines
            if not line:
                continue
            
            # Check for completion messages
            if line.startswith("DONE"):
                return line
            if line.startswith("ERR"):
                return line
            
            # Other messages are ignored (progress updates, debug info, etc.)
    
    def stop(self) -> str:
        """
        Stop profile execution on the Pico.
        
        This sends the STOP command to immediately halt execution.
        
        Command format:
            STOP\n
        
        Returns:
            str: Response from Pico ("OK STOP" if successful, or error message)
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> pico.run("profile.json")
            >>> # ... later ...
            >>> pico.stop()
            'OK STOP'
        
        Note:
            - Thread-safe (uses internal lock)
            - Takes effect immediately
            - The Pico will respond to wait_done() with an error after stopping
        """
        self._require()
        
        with self._lock:
            self.ser.write(b"STOP\n")
            self.ser.flush()
            return self._readline()
    
    def pause(self) -> str:
        """
        Pause profile execution on the Pico.
        
        This sends the PAUSE command to temporarily halt execution.
        Use resume() to continue from the current position.
        
        Command format:
            PAUSE\n
        
        Returns:
            str: Response from Pico ("OK PAUSE" if successful, or error message)
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> pico.run("profile.json")
            >>> # ... during execution ...
            >>> pico.pause()
            'OK PAUSE'
            >>> # ... later ...
            >>> pico.resume()
        
        Note:
            - Thread-safe (uses internal lock)
            - Execution can be resumed with resume()
            - The Pico maintains its position during pause
        """
        self._require()
        
        with self._lock:
            self.ser.write(b"PAUSE\n")
            self.ser.flush()
            return self._readline()
    
    def resume(self) -> str:
        """
        Resume paused profile execution on the Pico.
        
        This sends the RESUME command to continue execution from
        where it was paused.
        
        Command format:
            RESUME\n
        
        Returns:
            str: Response from Pico ("OK RESUME" if successful, or error message)
        
        Raises:
            RuntimeError: If not connected to the Pico
        
        Example:
            >>> pico.pause()
            'OK PAUSE'
            >>> # ... some time passes ...
            >>> pico.resume()
            'OK RESUME'
        
        Note:
            - Thread-safe (uses internal lock)
            - Only works if execution was previously paused
            - Execution continues from the exact position where it was paused
        """
        self._require()
        
        with self._lock:
            self.ser.write(b"RESUME\n")
            self.ser.flush()
            return self._readline()
