#!/usr/bin/env python3
"""
ESPHome Compile Server Entry Point

This file initializes and runs the Flask application.
It performs startup checks, creates necessary directories,
and starts the background worker manager thread.
"""

import logging
import shutil
from app import create_app
from app.app_config import config
from app.jobs import setup_directories

# Create the Flask app instance
app = create_app()

if __name__ == '__main__':
    # Wrap all startup logic in an app context.
    # This makes 'app.logger' available to all functions called here.
    with app.app_context():
        # Setup directories on startup
        setup_directories()

        # --- Startup Logging & Checks ---
        app.logger.info("="*50)
        app.logger.info(f"--- STARTING ESPHOME JOB SERVER {config.APP_VERSION} ---")
        app.logger.info("="*50)
        
        app.logger.info(f"Max concurrent jobs: {config.MAX_CONCURRENT_JOBS}")
        
        # Check for required command-line tools
        esphome_ok = shutil.which("esphome")
        platformio_ok = shutil.which("platformio")
        
        if not esphome_ok:
            app.logger.error("="*50)
            app.logger.error("FATAL: 'esphome' command not found in PATH. Please install: pip install esphome")
            app.logger.error("="*50)
            exit(1)
        else:
            app.logger.info("'esphome' command found in PATH.")
            
        if not platformio_ok:
            app.logger.error("="*50)
            app.logger.error("FATAL: 'platformio' command not found in PATH. Please install: pip install platformio")
            app.logger.error("This is required for 'true upload' caching.")
            app.logger.error("="*50)
            exit(1)
        else:
            app.logger.info("'platformio' command found in PATH.")
        
        app.logger.info(f"Base Jobs Directory: {config.JOBS_DIR}")
        app.logger.info(f"Persistent Project Directory: {config.PROJECTS_DIR}")
        app.logger.info(f"Isolated PlatformIO Cache: {config.PLATFORMIO_CACHE_DIR}")

        app.logger.info("Celery workers will handle job processing.")
        app.logger.info(f"Starting Flask server on http://{config.HOST}:{config.PORT}")
    
    # --- END OF APP CONTEXT BLOCK ---

    # Run the Flask app
    # This call is (and must be) outside the app_context block
    app.run(debug=config.DEBUG, host=config.HOST, port=config.PORT)