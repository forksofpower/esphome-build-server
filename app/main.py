import uvicorn
from fastapi import FastAPI
import logging
from .app_config import config, settings
from .celery_app import celery
from .routers import jobs
# from .routes import main_bp

app = FastAPI(
    title="esphome-build-server-api",
    root_path="/api/v1",
    openapi_url="/api/v1/openapi.json",
)

# Set logging level from config
log_level_numeric = getattr(logging, config.LOG_LEVEL, logging.INFO)
logging.basicConfig(level=log_level_numeric, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Celery with Flask app context
celery.conf.update(settings)

# Register the main blueprint that contains all routes
# app.register_blueprint(main_bp)

# Include routers
app.include_router(jobs.router)

# Health check endpoint
@app.get("/health")
def health_check():
    return { "status": "ok" }

if __name__ == '__main__':
    uvicorn.run(app)
