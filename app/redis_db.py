"""
Redis-backed job database
"""

import os
import json
import redis
import threading

class RedisJobDB:
    """Thread-safe Redis-backed job database."""
    
    def __init__(self):
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self._lock = threading.Lock()
    
    def _key(self, job_id):
        return f"job:{job_id}"
    
    def __setitem__(self, job_id, value):
        """Store job data in Redis."""
        with self._lock:
            self.redis_client.set(self._key(job_id), json.dumps(value))
    
    def __getitem__(self, job_id):
        """Retrieve job data from Redis."""
        with self._lock:
            data = self.redis_client.get(self._key(job_id))
            if data is None:
                raise KeyError(job_id)
            return json.loads(data)
    
    def get(self, job_id, default=None):
        """Get job data with default fallback."""
        try:
            return self[job_id]
        except KeyError:
            return default
    
    def __contains__(self, job_id):
        """Check if job exists."""
        with self._lock:
            return self.redis_client.exists(self._key(job_id)) > 0
    
    def values(self):
        """Get all job values."""
        with self._lock:
            keys = self.redis_client.keys("job:*")
            return [json.loads(self.redis_client.get(k)) for k in keys if self.redis_client.get(k)]
    
    def items(self):
        """Get all job items as (job_id, data) tuples."""
        with self._lock:
            keys = self.redis_client.keys("job:*")
            result = []
            for k in keys:
                data = self.redis_client.get(k)
                if data:
                    job_id = k.split(":", 1)[1]
                    result.append((job_id, json.loads(data)))
            return result
