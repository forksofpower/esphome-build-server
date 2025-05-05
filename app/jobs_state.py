"""
Global state for job tracking.

This file exists to break circular dependencies.
Other modules can safely import these state objects.
"""

import threading
from .redis_db import RedisJobDB

# Redis-backed "database" to track job status (shared across processes)
JOBS_DB = RedisJobDB()
JOBS_DB_LOCK = threading.Lock()  # Keep for compatibility, but Redis handles locking

# Pub/Sub for live log streaming
JOB_LOG_BROADCASTER = {}
JOB_LOG_BROADCASTER_LOCK = threading.Lock()
