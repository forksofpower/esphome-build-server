"""
Global state for the job queue.

This file exists to break circular dependencies.
Other modules can safely import these state objects.
"""

import threading
import queue
from .app_config import config

# In-memory "database" to track job status.
JOBS_DB = {}
JOBS_DB_LOCK = threading.Lock()

# Queue to hold pending job IDs
job_queue = queue.Queue()

# Semaphore to limit concurrent workers
worker_semaphore = threading.Semaphore(config.MAX_CONCURRENT_JOBS)

# Pub/Sub for live log streaming
JOB_LOG_BROADCASTER = {}
JOB_LOG_BROADCASTER_LOCK = threading.Lock()
