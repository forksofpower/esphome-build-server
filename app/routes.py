"""
Flask routes (views) for the application.
"""

import os
import uuid
import tempfile
import shutil
import datetime
import json
import queue
from flask import (
    Blueprint, request, jsonify, send_from_directory, abort, 
    render_template_string, Response, redirect, url_for, 
    current_app as app
)

from .app_config import config
from .jobs_state import (
    JOBS_DB, JOBS_DB_LOCK, 
    JOB_LOG_BROADCASTER, JOB_LOG_BROADCASTER_LOCK
)
from .services import get_device_name_from_yaml, LogParser
from .jobs import run_esphome_task

# Create a Blueprint
main_bp = Blueprint('main', __name__)

@main_bp.route('/compile', methods=['POST'])
def handle_compile_request():
    """API endpoint to submit a new *compile* job."""
    files = request.files.getlist("file")
    if not files or all(f.filename == '' for f in files):
        return jsonify({"success": False, "error": "No files provided in the request"}), 400

    job_id = str(uuid.uuid4())
    main_yaml_filename = None
    main_yaml_path = None
    
    temp_dir = tempfile.mkdtemp()
    app.logger.info(f"Job {job_id}: Created temp dir: {temp_dir}")
    saved_files = []

    try:
        for file in files:
            if file and file.filename:
                filename = file.filename
                if not (filename.endswith('.yaml') or filename.endswith('.yml') or filename.endswith('.h')):
                    app.logger.warning(f"Job {job_id}: Skipping file with invalid extension: {filename}")
                    continue
                
                file_path = os.path.join(temp_dir, filename)
                file.save(file_path)
                saved_files.append(filename)
                
                if filename not in config.SECRET_FILENAMES and not filename.endswith('.h'):
                    if main_yaml_filename is not None:
                        raise ValueError(f"Ambiguous request: Found multiple non-secret YAML files: {main_yaml_filename} and {filename}")
                    main_yaml_filename = filename
                    main_yaml_path = file_path
        
        if main_yaml_filename is None or main_yaml_path is None:
            raise ValueError("No main device YAML file found. Please upload a device config, not just secret files.")

        device_name = get_device_name_from_yaml(main_yaml_path)
        if not device_name:
             raise ValueError("Could not parse 'name:' from your YAML file. Make sure it's set.")

        project_dir = os.path.join(config.PROJECTS_DIR, device_name)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
            app.logger.info(f"Job {job_id}: Created new persistent project dir: {project_dir}")
        
        for filename in saved_files:
            shutil.move(
                os.path.join(temp_dir, filename),
                os.path.join(project_dir, filename)
            )
        app.logger.info(f"Job {job_id}: Saved files to project dir: {project_dir}")
        
        log_path = os.path.join(config.LOGS_DIR, f"{job_id}.log")
        
        with JOBS_DB_LOCK:
            JOBS_DB[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "job_type": "compile", 
                "target_device": None,
                "api_password": None, 
                "log_file": log_path,
                "project_dir": project_dir,
                "main_yaml": main_yaml_filename,
                "device_name": device_name,
                "submitted_time": datetime.datetime.now().isoformat(),
                "start_time": None,
                "end_time": None,
                "duration": None,
                "binary_file": None,
                "error": None
            }
        
        # Submit to Celery
        run_esphome_task.delay(
            job_id, project_dir, main_yaml_filename, device_name, 
            log_path, "compile", None, None
        )
        app.logger.info(f"Job {job_id}: Submitted to Celery for project '{device_name}'.")

        return jsonify({
            "success": True,
            "message": "Job submitted and is pending.",
            "job_id": job_id,
            "device_name": device_name,
            "status_url": url_for('main.get_job_status', job_id=job_id),
            "logs_url": url_for('main.get_live_job_page', job_id=job_id),
            "jobs_dashboard_url": url_for('main.get_jobs_dashboard')
        }), 202
            
    except ValueError as e:
        app.logger.error(f"Job {job_id}: Validation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Job {job_id}: Unhandled exception during submission: {e}")
        return jsonify({"success": False, "error": f"Unhandled server error: {e}"}), 500
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

@main_bp.route('/jobs', methods=['GET'])
def get_jobs_dashboard():
    """Renders an HTML dashboard of all jobs."""
    with JOBS_DB_LOCK:
        jobs_list = sorted(JOBS_DB.values(), key=lambda j: j['submitted_time'], reverse=True)
    
    formatted_jobs = []
    for job in jobs_list:
        job_dict = job.copy()
        job_dict['submitted_time_human'] = datetime.datetime.fromisoformat(job['submitted_time']).strftime('%Y-%m-%d %H:%M:%S')
        if 'job_type' not in job_dict: job_dict['job_type'] = 'compile'
        if 'device_name' not in job_dict: job_dict['device_name'] = job_dict.get('main_yaml', 'unknown') # Fallback
        formatted_jobs.append(job_dict)

    active_jobs = len([j for j in jobs_list if j.get('status') == 'running'])
    
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>ESPHome Compile Jobs</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2em; background: #f9f9f9; }
                h1 { color: #333; }
                table { border-collapse: collapse; width: 100%; box-shadow: 0 2px 8px rgba(0,0,0,0.05); background: #fff; border-radius: 8px; overflow: hidden; }
                th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
                th { background-color: #f4f4f4; }
                tr:last-child td { border-bottom: 0; }
                .status { font-weight: bold; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 0.9em; }
                .status-pending { background-color: #eef; color: #55d; }
                .status-running { background-color: #e6f7ff; color: #096dd9; }
                .status-success { background-color: #f6ffed; color: #52c41a; }
                .status-failed { background-color: #fff1f0; color: #f5222d; }
                a { color: #096dd9; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 0.95em; }
                .header-info { display: flex; justify-content: space-between; align-items: center; }
                .header-info p { color: #666; }
                .job-type { font-size: 0.8em; color: #888; display: block; margin-top: 4px; }
                .device-name { font-weight: bold; display: block; }
            </style>
            <meta http-equiv="refresh" content="5">
        </head>
        <body>
            <div class="header-info">
                <h1>ESPHome Compile Jobs</h1>
                <p><strong>{{ active_jobs }} / {{ max_jobs }}</strong> active workers</p>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Project / Job ID</th>
                        <th>Status</th>
                        <th>Submitted</th>
                        <th>Duration</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for job in jobs %}
                    <tr>
                        <td class="mono">
                            <span class="device-name">{{ job.device_name }}</span>
                            {{ job.job_id }}
                            <span class="job-type">
                                {% if job.job_type == 'upload' %}
                                    UPLOAD (for {{ job.original_job_id[:8] }}...)
                                {% else %}
                                    COMPILE
                                {% endif %}
                            </span>
                        </td>
                        <td><span class="status status-{{ job.status }}">{{ job.status }}</span></td>
                        <td>{{ job.submitted_time_human }}</td>
                        <td>{{ "%.2f s" % job.duration if job.duration else "N/A" }}</td>
                        <td>
                            <a href="{{ url_for('main.get_live_job_page', job_id=job.job_id) }}" target="_blank">View Live Log</a>
                            | <a href="{{ url_for('main.get_job_log', job_id=job.job_id) }}" target="_blank">(Raw Log)</a>
                            {% if job.status == 'success' and job.binary_file %}
                                | <a href="{{ url_for('main.download_binary', job_id=job.job_id) }}">Download Binary</a>
                            {% endif %}
                            {% if job.status == 'success' and job.job_type == 'compile' %}
                                | <a href="{{ url_for('main.handle_upload_page', original_job_id=job.job_id) }}" style="font-weight:bold;">Upload OTA</a>
                            {% endif %}
                            {% if job.status == 'failed' and job.error %}
                                <br><small style="color: #f5222d;">Error: {{ job.error }}</small>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="5" style="text-align: center; padding: 20px; color: #888;">No jobs submitted yet.</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </body>
        </html>
        """,
        jobs=formatted_jobs,
        active_jobs=active_jobs,
        max_jobs=config.MAX_CONCURRENT_JOBS
    )

@main_bp.route('/job/<original_job_id>/upload', methods=['GET', 'POST'])
def handle_upload_page(original_job_id):
    """Shows a page to start an OTA upload for a previously successful compile job."""
    with JOBS_DB_LOCK:
        job = JOBS_DB.get(original_job_id)
        
    if not job: abort(404, "Original compile job not found")
    if job['status'] != 'success': abort(400, "Original job was not successful. Cannot upload.")

    if request.method == 'POST':
        target_device = request.form.get('target')
        api_password = request.form.get('api_password')
        if not target_device: return "Error: 'target' is required.", 400
        
        new_job_id = str(uuid.uuid4())
        log_path = os.path.join(config.LOGS_DIR, f"{new_job_id}.log")
        
        with JOBS_DB_LOCK:
            JOBS_DB[new_job_id] = {
                "job_id": new_job_id,
                "status": "pending",
                "job_type": "upload",
                "target_device": target_device,
                "api_password": api_password if api_password else None, 
                "original_job_id": original_job_id,
                "log_file": log_path,
                "project_dir": job['project_dir'], 
                "main_yaml": job['main_yaml'],
                "device_name": job['device_name'],
                "submitted_time": datetime.datetime.now().isoformat(),
                "start_time": None,
                "end_time": None,
                "duration": None,
                "binary_file": None,
                "error": None
            }
        
        # Submit to Celery
        run_esphome_task.delay(
            new_job_id, job['project_dir'], job['main_yaml'], job['device_name'],
            log_path, "upload", target_device, api_password
        )
        app.logger.info(f"Job {new_job_id}: Submitted UPLOAD task for {original_job_id} -> {target_device}")
        return redirect(url_for('main.get_live_job_page', job_id=new_job_id))

    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Upload {{ job.device_name }}</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2em; background: #f9f9f9; }
                h1 { color: #333; }
                .container { background: #fff; padding: 2em; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); max-width: 600px; }
                .form-group { margin-bottom: 1.5em; }
                label { display: block; font-weight: bold; margin-bottom: 0.5em; }
                input[type="text"], input[type="password"] { width: 100%; padding: 10px; font-size: 1.1em; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
                button { background: #096dd9; color: #fff; font-weight: bold; padding: 12px 20px; font-size: 1.1em; border: none; border-radius: 4px; cursor: pointer; margin-top: 1em; }
                button:hover { background: #085cb0; }
                .mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Start OTA Upload</h1>
                <p>This will start a new job to upload for:
                    <br><strong>{{ job.device_name }}</strong>
                    (from job <span class="mono">{{ job.job_id[:12] }}...</span>)
                </p>
                <form method="POST">
                    <div class="form-group">
                        <label for="target">Target Device (e.g., <span class="mono">device.local</span> or <span class="mono">192.168.1.50</span>):</label>
                        <input type="text" name="target" id="target" placeholder="device.local" required>
                    </div>
                    <div class="form-group">
                        <label for="api_password">API Password (leave blank if none):</label>
                        <input type="password" name="api_password" id="api_password" placeholder="Optional API password">
                    </div>
                    <button type="submit">Start Upload Job</button>
                </form>
            </div>
        </body>
        </html>
        """, 
        job=job
    )


@main_bp.route('/job/<job_id>', methods=['GET'])
def get_live_job_page(job_id):
    """Renders the new live log streaming page."""
    with JOBS_DB_LOCK:
        job = JOBS_DB.get(job_id)
    if not job: abort(404, "Job not found")

    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Live Log: {{ job.device_name }}</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f6f8fa; color: #24292e; }
                .header { background: #fff; padding: 16px 24px; border-bottom: 1px solid #e1e4e8; display: flex; align-items: center; justify-content: space-between; }
                h1 { margin: 0; color: #24292e; font-size: 1.5em; }
                .status { font-weight: bold; padding: 6px 12px; border-radius: 2em; display: inline-block; font-size: 1em; }
                .status-pending { background-color: #eef; color: #55d; }
                .status-running { background-color: #e6f7ff; color: #096dd9; }
                .status-success { background-color: #f6ffed; color: #52c41a; }
                .status-failed { background-color: #fff1f0; color: #f5222d; }
                .container { padding: 24px; max-width: 1000px; margin: 0 auto; }
                details { background: #fff; border: 1px solid #e1e4e8; border-radius: 6px; margin-bottom: 16px; }
                summary { padding: 12px 16px; font-weight: bold; cursor: pointer; list-style: none; display: flex; align-items: center; font-size: 1.1em; }
                summary::-webkit-details-marker { display: none; }
                summary:before { content: '►'; margin-right: 8px; font-size: 0.8em; transform: rotate(0deg); transition: transform 0.1s; color: #586069; }
                details[open] summary:before { transform: rotate(90deg); }
                pre {
                    background: #1e1e1e; color: #d4d4d4; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
                    font-size: 14px; white-space: pre-wrap; word-wrap: break-word; margin: 0; padding: 16px;
                    overflow: auto; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; max-height: 400px;
                }
                pre.progress-block { background: #fff; color: #24292e; padding-left: 16px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{{ job.device_name }} <span style="font-weight:normal; color: #586069;">({{ job.main_yaml }})</span></h1>
                <div id="status-container">
                    <span class="status status-{{ job.status }}" id="status-badge">{{ job.status }}</span>
                </div>
            </div>
            <div class="container" id="log-output-container"></div>
            <script>
                const jobId = "{{ job.job_id }}";
                const logOutputContainer = document.getElementById('log-output-container');
                const statusBadge = document.getElementById('status-badge');
                let currentDetails = null, currentPre = null, progressBlocks = {}; 
                function addLogLine(text) {
                    if (!currentPre) createNewStep('Log'); 
                    const line = document.createTextNode(text + '\\n');
                    currentPre.appendChild(line);
                    currentPre.scrollTop = currentPre.scrollHeight;
                }
                function createNewStep(milestoneName, id = null) {
                    if (currentDetails) currentDetails.open = false;
                    currentDetails = document.createElement('details');
                    currentDetails.open = true;
                    const summary = document.createElement('summary');
                    if (id) summary.id = id;
                    summary.innerHTML = `<span class="summary-text">${milestoneName}</span>`;
                    currentDetails.appendChild(summary);
                    currentPre = document.createElement('pre');
                    currentDetails.appendChild(currentPre);
                    logOutputContainer.appendChild(currentDetails);
                    updateStatusBadge(milestoneName);
                }
                function updateSummaryText(targetId, newText) {
                    const summaryEl = document.getElementById(targetId);
                    if (summaryEl) {
                        const textSpan = summaryEl.querySelector('.summary-text');
                        if (textSpan) textSpan.textContent = newText;
                    }
                }
                function updateProgressBar(progressData) {
                    if (!currentPre) {
                        let milestoneName = 'Log';
                        if (progressData.name === 'Downloading' || progressData.name === 'Unpacking') milestoneName = 'Installing Dependencies';
                        else if (progressData.name === 'RAM' || progressData.name === 'Flash') milestoneName = 'Calculating Firmware Size';
                        createNewStep(milestoneName);
                    }
                    const blockId = `progress-${progressData.name}`;
                    let progressPre = progressBlocks[blockId];
                    if (!progressPre) {
                        progressPre = document.createElement('pre');
                        progressPre.id = blockId;
                        progressPre.classList.add('progress-block');
                        currentPre.appendChild(progressPre); 
                        progressBlocks[blockId] = progressPre;
                    }
                    progressPre.textContent = `${progressData.name}: ${progressData.bar} ${progressData.percent}`;
                }
                function updateStatusBadge(text) {
                    statusBadge.textContent = text;
                    statusBadge.className = 'status'; 
                    if (text.toLowerCase().includes('fail') || text.toLowerCase().includes('error')) statusBadge.classList.add('status-failed');
                    else if (text.toLowerCase().includes('success')) statusBadge.classList.add('status-success');
                    else statusBadge.classList.add('status-running');
                }
                function finishStream(finalStatus) {
                    updateStatusBadge(finalStatus);
                    if (currentDetails) currentDetails.open = false;
                }
                createNewStep('Connecting to Live Log Stream...');
                const eventSource = new EventSource("{{ url_for('main.log_stream', job_id=job.job_id) }}");
                eventSource.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    switch(data.event) {
                        case 'milestone':
                            createNewStep(data.milestone, data.id);
                            if (data.line) addLogLine(data.line);
                            break;
                        case 'log': addLogLine(data.line); break;
                        case 'progress': updateProgressBar(data.data); break;
                        case 'update_summary': updateSummaryText(data.target_id, data.text); break;
                        case 'CLOSE':
                            eventSource.close();
                            fetch("{{ url_for('main.get_job_status', job_id=job.job_id) }}")
                                .then(res => res.json())
                                .then(job => {
                                    finishStream(job.status);
                                    if (job.status === 'success' && job.binary_file) {
                                         const downloadLink = document.createElement('a');
                                         downloadLink.href = "{{ url_for('main.download_binary', job_id=job.job_id) }}";
                                         downloadLink.textContent = 'Download Binary';
                                         downloadLink.style.marginTop = '1em';
                                         downloadLink.style.display = 'inline-block';
                                         downloadLink.style.fontWeight = 'bold';
                                         logOutputContainer.appendChild(downloadLink);
                                    }
                               });
                            break;
                    }
                };
                eventSource.onerror = function(err) {
                    createNewStep('Error');
                    addLogLine('--- Lost connection to log stream. Stopping. ---');
                    eventSource.close();
                    finishStream('failed');
                };
            </script>
        </body>
        </html>
        """, 
        job=job
    )


@main_bp.route('/log-stream/<job_id>')
def log_stream(job_id):
    """Server-Sent Event (SSE) stream."""
    with JOBS_DB_LOCK:
        job = JOBS_DB.get(job_id)
        if not job: abort(404)
        status = job['status']
        log_path = job['log_file']

    def subscribe_to_live_events():
        listener_queue = queue.Queue()
        with JOB_LOG_BROADCASTER_LOCK:
            if job_id not in JOB_LOG_BROADCASTER: JOB_LOG_BROADCASTER[job_id] = []
            JOB_LOG_BROADCASTER[job_id].append(listener_queue)
        try:
            while True:
                log_data = listener_queue.get()
                yield f"data: {json.dumps(log_data)}\n\n"
                if log_data.get('event') == 'CLOSE': break
        except GeneratorExit:
            app.logger.info(f"Log stream client disconnected for job {job_id}")
        finally:
            with JOB_LOG_BROADCASTER_LOCK:
                if job_id in JOB_LOG_BROADCASTER and listener_queue in JOB_LOG_BROADCASTER[job_id]:
                    JOB_LOG_BROADCASTER[job_id].remove(listener_queue)
    
    def replay_log_events():
        app.logger.info(f"Replaying log file for job {job_id}")
        parser = LogParser()
        try:
            with open(log_path, 'r') as log_file:
                for line in log_file:
                    line_stripped = line.strip()
                    if not line_stripped: continue
                    if line_stripped.startswith("---") or \
                       line_stripped.startswith("Command:") or \
                       line_stripped.startswith("Project Dir:") or \
                       line_stripped.startswith("PlatformIO Cache:") or \
                       line_stripped.startswith("Env:"):
                        continue
                    for event in parser.parse_line(line_stripped):
                        yield f"data: {json.dumps(event)}\n\n"
            for event in parser.finalize():
                yield f"data: {json.dumps(event)}\n\n"
        except FileNotFoundError:
            app.logger.error(f"Cannot replay log: File not found {log_path}")
            yield f"data: {json.dumps({'event': 'milestone', 'milestone': 'Error: Log file not found', 'id': 'err'})}\n\n"
        except Exception as e:
            app.logger.error(f"Error replaying log {job_id}: {e}")
            yield f"data: {json.dumps({'event': 'milestone', 'milestone': f'Error: {e}', 'id': 'err'})}\n\n"
        finally:
            yield f"data: {json.dumps({'event': 'CLOSE'})}\n\n"

    if status == 'running' or status == 'pending':
        return Response(subscribe_to_live_events(), mimetype='text/event-stream')
    else:
        return Response(replay_log_events(), mimetype='text/event-stream')


@main_bp.route('/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Returns the JSON status for a single job."""
    with JOBS_DB_LOCK:
        job = JOBS_DB.get(job_id)
    if not job: abort(404, "Job not found")
    return jsonify(job.copy())

@main_bp.route('/logs/<job_id>', methods=['GET'])
def get_job_log(job_id):
    """Returns the raw text log file for a job."""
    with JOBS_DB_LOCK:
        log_path = JOBS_DB.get(job_id, {}).get('log_file')
    if not log_path: abort(404, "Job not found")
    if not os.path.exists(log_path):
        return "Log file not created yet. Job may be pending.", 200, {'Content-Type': 'text/plain'}
    try:
        return send_from_directory(os.path.dirname(log_path), os.path.basename(log_path), mimetype='text/plain')
    except Exception as e:
        app.logger.error(f"Could not send log file {log_path}: {e}")
        return "Error reading log file.", 500, {'Content-Type': 'text/plain'}

@main_bp.route('/download/<job_id>', methods=['GET'])
def download_binary(job_id):
    """Lets the user download the compiled binary if the job succeeded."""
    with JOBS_DB_LOCK:
        job = JOBS_DB.get(job_id)
    
    if not job: abort(404, "Job not found")
    if job['status'] != 'success': abort(400, f"Job status is '{job['status']}', not 'success'. Binary not available.")
    binary_file = job.get('binary_file')
    if not binary_file: abort(404, "Job succeeded, but binary file reference is missing.")
         
    binary_path = os.path.join(config.BINARIES_DIR, binary_file)
    if not os.path.exists(binary_path):
        app.logger.error(f"Job {job_id} succeeded but binary file is missing from disk: {binary_path}")
        abort(500, "Binary file not found on server, may have been cleaned up.")
        
    try:
        return send_from_directory(
            config.BINARIES_DIR,
            binary_file,
            as_attachment=True,
            download_name=binary_file.split('-', 1)[-1] 
        )
    except Exception as e:
        app.logger.error(f"Could not send binary file {binary_path}: {e}")
        abort(500, "Error sending binary file.")

@main_bp.route('/', methods=['GET'])
def index():
    """Simple index page with instructions."""
    # --- THIS IS THE FIX ---
    # 1. This is no longer an f-string. It's a regular string.
    # 2. Variables are passed into render_template_string as Jinja2 context.
    template = """
        <html>
            <head><title>ESPHome Compile Server</title></head>
            <body style="font-family: sans-serif; padding: 2em; line-height: 1.6;">
                <h1>ESPHome Compile Server is running</h1>
                <p>This is an asynchronous job server. Max concurrent jobs: <strong>{{ max_jobs }}</strong></p>
                <p><a href="{{ url_for('main.get_jobs_dashboard') }}" style="font-size: 1.2em; font-weight: bold;">View Job Dashboard</a></p>
                <h2>API Endpoints:</h2>
                <ul>
                    <li><code>POST /compile</code>: Upload files (device YAML + secrets) to start a new compile-only job.</li>
                    <li><code>GET /jobs</code>: View the HTML dashboard of all jobs.</li>
                    <li><code>GET /job/&lt;job_id&gt;</code>: View the live log for any job.</li>
                    <li><code>GET /job/&lt;job_id&gt;/upload</code>: Page to start an OTA upload for a successful compile job.</li>
                    <li><code>GET /status/&lt;job_id&gt;</code>: Get JSON status for a job.</li>
                    <li><code>GET /logs/&lt;job_id&gt;</code>: View the raw compile log.</li>
                    <li><code>GET /download/&lt;job_id&gt;</code>: Download the binary after success.</li>
                </ul>
                <p><strong>Example (from your terminal):**</p>
                <pre style="background: #eee; padding: 1em; border-radius: 5px;">
    curl -X POST \
      -F "file=@/path/to/your/my-device.yaml" \
      -F "file=@/path/to/your/secrets.yaml" \
      http://127.0.0.1:{{ port }}/compile</pre>
            </body>
        </html>
    """
    return render_template_string(
        template,
        max_jobs=config.MAX_CONCURRENT_JOBS,
        port=config.PORT
    )

