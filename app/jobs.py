"""
Core job management logic.
- Worker thread entry point
- Background worker manager
- Log broadcasting
- Directory setup
"""

import os
import logging # <-- Import logging
import subprocess
import datetime
import shutil
import queue
import threading
import uuid
from flask import current_app as app # Import app context

from .app_config import config
from .jobs_state import (
    JOBS_DB, JOBS_DB_LOCK, JOB_LOG_BROADCASTER, 
    JOB_LOG_BROADCASTER_LOCK, worker_semaphore
)
from .services import LogParser, _find_firmware_bin

def setup_directories():
    """Creates all the necessary persistent directories from config."""
    paths_to_create = [
        config.JOBS_DIR, 
        config.LOGS_DIR, 
        config.PROJECTS_DIR,
        config.BINARIES_DIR, 
        config.PLATFORMIO_CACHE_DIR
    ]
    for path in paths_to_create:
        if not os.path.exists(path):
            try:
                os.makedirs(path)
                # Use app.logger since this is still called from run.py's context
                app.logger.info(f"Created directory: {path}")
            except OSError as e:
                # Use standard logging for fatal errors
                logging.error(f"FATAL: Could not create directory {path}: {e}")
                exit(1)

def _broadcast_log(job_id, payload):
    """Puts a log message (as a dict) into all subscriber queues for a job_id."""
    with JOB_LOG_BROADCASTER_LOCK:
        if job_id in JOB_LOG_BROADCASTER:
            for q in list(JOB_LOG_BROADCASTER[job_id]):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass 

def _run_esphome_task(job_id, project_dir, yaml_filename, device_name, log_path, job_type, target_device, api_password):
    """
    THE ACTUAL WORKER TASK (LOCAL). Runs in its own thread.
    'project_dir' is the persistent project cache directory.
    """
    start_time = datetime.datetime.now()
    with JOBS_DB_LOCK:
        JOBS_DB[job_id]["status"] = "running"
        JOBS_DB[job_id]["start_time"] = start_time.isoformat()

    # --- Build the command based on job type ---
    if job_type == "upload" and target_device:
        # Use standard logging for background threads
        logging.info(f"Job {job_id}: Starting TRUE UPLOAD task for '{device_name}'. Target: {target_device}")
        local_command = [
            "platformio", "run",
            "--target", "upload",
            "--project-dir", project_dir,
            "--environment", device_name,
            "--upload-port", target_device
        ]
    else:
        job_type = "compile"
        # Use standard logging for background threads
        logging.info(f"Job {job_id}: Starting COMPILE task for '{device_name}'.")
        local_command = ["esphome", "compile", yaml_filename]
    
    parser = LogParser()
    
    env = os.environ.copy()
    env['PLATFORMIO_CORE_DIR'] = config.PLATFORMIO_CACHE_DIR
    if api_password:
        env['ESPHOME_API_PASSWORD'] = api_password
    
    # Use standard logging for background threads
    logging.info(f"Job {job_id}: Setting PLATFORMIO_CORE_DIR to {config.PLATFORMIO_CACHE_DIR}")
    
    try:
        with open(log_path, 'w') as log_file:
            log_file.write(f"--- RUNNING SCRIPT VERSION {config.APP_VERSION} ---\n")
            log_file.write(f"--- Starting {job_type.upper()} job {job_id} for project '{device_name}' ---\n")
            log_command = local_command[:]
            if api_password: log_file.write(f"Env: ESPHOME_API_PASSWORD set to '********'\n")
            log_file.write(f"Command: {' '.join(log_command)}\n")
            log_file.write(f"Project Dir: {project_dir}\n")
            log_file.write(f"PlatformIO Cache: {config.PLATFORMIO_CACHE_DIR}\n")
            log_file.write("-" * 40 + "\n\n")
            log_file.flush()

            if job_type == 'compile':
                for event in parser.parse_line("Validating Config"): _broadcast_log(job_id, event)
            elif job_type == 'upload':
                for event in parser.parse_line(f"Starting Upload to {target_device}"): _broadcast_log(job_id, event)

            process = subprocess.Popen(
                local_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                cwd=project_dir if job_type == 'compile' else None,
                env=env
            )
            
            last_lines = [] 
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                line_stripped = line.strip()
                if not line_stripped: continue
                last_lines.append(line_stripped)
                if len(last_lines) > 10: last_lines.pop(0)
                for event in parser.parse_line(line_stripped):
                    _broadcast_log(job_id, event)
            process.wait()
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            log_file.write(f"\n{'-' * 40}\n--- Job finished at {end_time.isoformat()} ---\n")
            log_file.write(f"Return Code: {process.returncode}\nDuration: {duration:.2f} seconds\n")
            
            for event in parser.finalize(): _broadcast_log(job_id, event)
            
            with JOBS_DB_LOCK:
                job_details = JOBS_DB[job_id]
                job_details["end_time"] = end_time.isoformat()
                job_details["duration"] = duration
                
                is_upload_success = any("Successfully uploaded" in l or "===== [SUCCESS]" in l for l in last_lines)
                is_auth_fail = any("Authentication invalid" in l for l in last_lines)
                
                if process.returncode == 0 and (is_upload_success or job_type == "compile"):
                    log_file.write("Status: SUCCESS\n")
                    source_binary_path = _find_firmware_bin(project_dir, device_name)
                    
                    if source_binary_path and os.path.exists(source_binary_path):
                        final_binary_name = f"{job_id}-{device_name}-firmware.bin"
                        final_binary_path = os.path.join(config.BINARIES_DIR, final_binary_name)
                        shutil.copy(source_binary_path, final_binary_path)
                        
                        job_details["status"] = "success"
                        job_details["binary_file"] = final_binary_name
                        # Use standard logging for background threads
                        logging.info(f"Job {job_id}: {job_type.upper()} SUCCESS. Binary at {final_binary_path}")
                        
                        if job_type == "compile":
                            for event in parser.parse_line("[SUCCESS] Build Succeeded"): _broadcast_log(job_id, event)
                    else:
                        log_msg = f"Source binary not found in {project_dir}"
                        # Use standard logging for background threads
                        logging.error(f"Job {job_id}: Succeeded but {log_msg}")
                        log_file.write(f"Status: FAILED ({log_msg})\n")
                        job_details["status"] = "failed"
                        job_details["error"] = log_msg
                        for event in parser.parse_line(f"[FAILED] Error: {log_msg}"): _broadcast_log(job_id, event)
                else:
                    # Use standard logging for background threads
                    logging.error(f"Job {job_id}: {job_type.upper()} FAILED. Check log: {log_path}")
                    log_file.write("Status: FAILED\n")
                    job_details["status"] = "failed"
                    if is_auth_fail: job_details["error"] = "Upload failed: Authentication Invalid."
                    else: job_details["error"] = "Process failed. Check log for details."
                    for event in parser.parse_line(f"[FAILED] Error: Process returned code {process.returncode}"):
                        _broadcast_log(job_id, event)

    except Exception as e:
        # Use standard logging for background threads
        logging.error(f"Job {job_id}: Worker thread crashed: {e}")
        try:
            with JOBS_DB_LOCK:
                JOBS_DB[job_id]["status"] = "failed"
                JOBS_DB[job_id]["error"] = f"Python worker crashed: {e}"
            with open(log_path, 'a') as log_file:
                log_file.write(f"\n--- PYTHON WORKER CRASHED ---\n{e}\n")
            _broadcast_log(job_id, {'event': 'milestone', 'milestone': 'Server Crash', 'id': f"step-{uuid.uuid4().hex}", 'line': f'Error: {e}'})
        except: pass 
    finally:
        _broadcast_log(job_id, {'event': 'CLOSE'})
        with JOB_LOG_BROADCASTER_LOCK:
            if job_id in JOB_LOG_BROADCASTER: del JOB_LOG_BROADCASTER[job_id]
        worker_semaphore.release()
        # Use standard logging for background threads
        logging.info(f"Job {job_id}: Worker slot released. {config.MAX_CONCURRENT_JOBS - worker_semaphore._value} active.")


def worker_manager_thread():
    """The main worker manager. Runs in a separate thread."""
    from .jobs_state import job_queue # Import here to avoid circularity at load time
    
    while True:
        try:
            job_id = job_queue.get()
            # Use standard logging for background threads
            logging.info(f"Job {job_id}: Picked up from queue. Waiting for worker slot...")
            worker_semaphore.acquire()
            logging.info(f"Job {job_id}: Worker slot acquired. Starting job thread.")
            
            with JOBS_DB_LOCK:
                job_details = JOBS_DB.get(job_id)
            if not job_details:
                # Use standard logging for background threads
                logging.error(f"Job {job_id}: Was in queue but not in DB. Discarding.")
                worker_semaphore.release()
                continue
            
            project_dir = job_details["project_dir"]
            yaml_filename = job_details["main_yaml"]
            device_name = job_details["device_name"]
            log_path = job_details["log_file"]
            job_type = job_details.get("job_type", "compile") 
            target_device = job_details.get("target_device")
            api_password = job_details.get("api_password")

            compile_thread = threading.Thread(
                target=_run_esphome_task,
                args=(job_id, project_dir, yaml_filename, device_name, log_path, job_type, target_device, api_password)
            )
            compile_thread.start()
        except Exception as e:
            # Use standard logging for background threads
            logging.error(f"FATAL: Worker manager thread crashed: {e}")

