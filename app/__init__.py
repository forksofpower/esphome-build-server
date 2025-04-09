"""
Application factory for the Flask app.
"""

import logging
from flask import Flask
from .app_config import config

def create_app():
    """
    Creates and configures the Flask application instance.
    """
    app = Flask(__name__)

    # Set logging level from config
    log_level_numeric = getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(level=log_level_numeric, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Register the main blueprint that contains all routes
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app

