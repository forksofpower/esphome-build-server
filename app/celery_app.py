"""
Celery configuration and task definitions.
"""

import os
from celery import Celery

def make_celery():
    """
    Creates and configures a Celery instance.
    """
    broker_url = os.environ.get('CELERY_BROKER_URL', 'amqp://guest:guest@rabbitmq:5672//')
    result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'rpc://')
    
    celery = Celery(
        'esphome_relay',
        broker=broker_url,
        backend=result_backend
    )
    
    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_send_sent_event=True,
    )
    
    return celery

celery = make_celery()
