#!/usr/bin/env python3
"""
Celery Worker Entry Point

Run this file to start a Celery worker that processes ESPHome compilation jobs.

Usage:
    python celery_worker.py
    
Or via Celery CLI:
    celery -A celery_worker.celery worker --loglevel=info
"""

from app.celery_app import celery
import app.jobs  # Import module to register tasks

if __name__ == '__main__':
    celery.start()
