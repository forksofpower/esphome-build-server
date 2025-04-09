"""
Stateless services and helper functions.
- Log parsing
- File/YAML helpers
"""

import re
import os
import uuid
import logging # <-- Import logging
from flask import current_app as app # Keep for routes, but avoid in services

# --- Log Parsing ---
progress_bar_regex = re.compile(r"^(RAM|Flash):\s*(\[.*?\])\s*(\d+\.\d+%)")
download_bar_regex = re.compile(r"\[\?25l(Downloading|Unpacking)\s*(\[.*?\])\s*(\d+%)")

def _parse_log_line_type(line):
    """Parses a log line to find key milestones for the accordion UI."""
    if "Successfully uploaded" in line or line.startswith("===== [SUCCESS]"):
        return {'type': 'milestone', 'data': 'Upload Succeeded'}
    if "[SUCCESS]" in line and "Successfully created" in line:
        return {'type': 'milestone', 'data': 'Build Succeeded'}
    if "[FAILED]" in line or ("error" in line and "compilation terminated" in line) or line.startswith("===== [FAILED]"):
        return {'type': 'milestone', 'data': 'Build Failed'}
    if "ERROR" in line and "Authentication invalid" in line:
        return {'type': 'milestone', 'data': 'Upload Failed: Authentication Invalid'}
    if "Error:" in line and "Could not find" in line and ".local" in line:
         return {'type': 'milestone', 'data': f'Upload Failed: Host not found'}
    if "ERROR" in line and "Connecting to" in line:
         return {'type': 'milestone', 'data': f'Upload Failed: {line.strip()}'}
    if line.startswith("Error:"):
        return {'type': 'milestone', 'data': f'Error: {line[6:].strip()}'}

    progress_match = progress_bar_regex.match(line)
    if progress_match:
        return {'type': 'progress_bar', 'data': {'name': progress_match.group(1), 'bar': progress_match.group(2), 'percent': progress_match.group(3)}}
    
    download_match = download_bar_regex.match(line)
    if download_match:
        return {'type': 'progress_bar', 'data': {'name': download_match.group(1), 'bar': download_match.group(2), 'percent': download_match.group(3)}}

    if "Looking for upload port..." in line:
        return {'type': 'milestone', 'data': 'Finding Device...'}
    if "Uploading" in line and ".bin" in line:
        return {'type': 'milestone', 'data': 'Uploading Firmware'}
    if "Connecting to" in line:
        return {'type': 'milestone', 'data': line.strip()} 
    if "merging binaries into" in line or "esp32_copy_ota_bin" in line or ("Successfully created" in line and ".bin" in line):
        return {'type': 'milestone', 'data': 'Creating Final Binaries'}
    if line.startswith("RAM:"): 
        return {'type': 'milestone', 'data': 'Calculating Firmware Size'}
    if "Linking .pioenvs" in line and "firmware.elf" in line:
        return {'type': 'milestone', 'data': 'Linking Firmware'}
    if "Linking .pioenvs" in line and "bootloader.elf" in line:
        return {'type': 'milestone', 'data': 'Linking Bootloader'}
    if "Generating project linker script" in line:
        return {'type': 'milestone', 'data': 'Generating Linker Script'}
    if "Compiling .pioenvs" in line or "Archiving .pioenvs" in line:
        return {'type': 'compile_archive_line'}
    if "scons:" in line or "Platformio:" in line or "NOTICE:" in line or "Resolving" in line or \
       line.startswith("Platform Manager: Installing") or line.startswith("Tool Manager: Installing") or \
       line.startswith("Library Manager: Installing"):
        return {'type': 'milestone', 'data': 'Installing Dependencies'}
    if "Generating C++ code" in line:
        return {'type': 'milestone', 'data': 'Generating C++'}
    if "Running: platformio" in line or "Initializing Platformio" in line:
        return {'type': 'milestone', 'data': 'Initializing PlatformIO'}
    if "Validating" in line:
        return {'type': 'milestone', 'data': 'Validating Config'}
    return {'type': 'log'} 


class LogParser:
    """Holds the state for the accordion log parser."""
    def __init__(self):
        self.current_milestone = "Starting..."
        self.in_compile_step = False
        self.compile_count = 0
        self.summary_id = None
        self.milestone_id = None
    
    def _start_milestone(self, name, line=None):
        self.current_milestone = name
        self.milestone_id = f"step-{uuid.uuid4().hex}"
        event = {'event': 'milestone', 'milestone': name, 'id': self.milestone_id}
        if line: event['line'] = line
        return [event]
    
    def _close_compile_step(self, interrupted=False):
        events = []
        if self.in_compile_step:
            summary_text = f"Compiling C/C++ Sources & Archiving ({self.compile_count} files)"
            if interrupted: summary_text += " - Interrupted"
            events.append({'event': 'update_summary', 'target_id': self.summary_id, 'text': summary_text})
            self.in_compile_step = False
            self.compile_count = 0
        return events

    def parse_line(self, line):
        events = []
        parse_result = _parse_log_line_type(line)
        line_type = parse_result['type']
        payload = {'event': 'log', 'line': line}

        if line_type == 'compile_archive_line':
            if not self.in_compile_step:
                events.extend(self._close_compile_step()) 
                self.in_compile_step = True
                self.compile_count = 1
                self.current_milestone = "Compiling C/C++ Sources & Archiving"
                self.summary_id = f"step-{uuid.uuid4().hex}"
                payload['event'] = 'milestone'
                payload['milestone'] = self.current_milestone
                payload['id'] = self.summary_id
            else:
                self.compile_count += 1
                if self.compile_count % 25 == 0:
                    events.append({'event': 'update_summary', 'target_id': self.summary_id, 'text': f"Compiling C/C++ Sources & Archiving ({self.compile_count} files...)"})
            events.append(payload)
        elif line_type == 'milestone':
            milestone_text = parse_result['data']
            if self.current_milestone != milestone_text:
                events.extend(self._close_compile_step())
                events.extend(self._start_milestone(milestone_text))
            if milestone_text not in ["Upload Succeeded", "Build Succeeded", "Upload Failed: Authentication Invalid"]:
                events.append({'event': 'log', 'line': line})
        elif line_type == 'progress_bar':
            data = parse_result['data']
            milestone_text = self.current_milestone
            if data['name'] in ['RAM', 'Flash']: milestone_text = 'Calculating Firmware Size'
            elif data['name'] in ['Downloading', 'Unpacking']: milestone_text = 'Installing Dependencies'
            if self.current_milestone != milestone_text:
                events.extend(self._close_compile_step())
                events.extend(self._start_milestone(milestone_text))
            payload['event'] = 'progress'
            payload['data'] = data
            events.append(payload)
        elif line_type == 'log':
            events.append(payload)
        return events

    def finalize(self):
        return self._close_compile_step()

# --- File Helpers ---

def get_device_name_from_yaml(yaml_path):
    """Quickly parses the YAML file to find the 'name:' field under 'esphome:'."""
    try:
        with open(yaml_path, 'r') as f:
            for line in f:
                if 'name:' in line and not line.strip().startswith('#'):
                    parts = line.split('name:')
                    if len(parts) > 1:
                        device_name = parts[1].strip().strip('"').strip("'")
                        if device_name and not device_name.startswith('!'):
                            return device_name
    except Exception as e:
        # Use standard logging
        logging.warning(f"Could not parse device name from YAML: {e}. Falling back to filename.")
    return None # Return None on failure

def _find_firmware_bin(project_dir, device_name):
    """
    Searches the project build directory for the compiled firmware.bin.
    'project_dir' is the *persistent* path, e.g., .../projects/my_device/
    """
    build_dir = os.path.join(project_dir, ".esphome", "build", device_name)
    # Use standard logging
    logging.info(f"Searching for binary in: {build_dir}")
    if os.path.isdir(build_dir):
        for root, dirs, files in os.walk(build_dir):
            if "firmware.bin" in files:
                found_path = os.path.join(root, "firmware.bin")
                # Use standard logging
                logging.info(f"Found binary at: {found_path}")
                return found_path
    return None

