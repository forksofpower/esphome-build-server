"""
Configuration loader for the application.
Reads 'config.ini' and provides a global 'config' object.
"""

import os
import configparser

class AppConfig:
    """Loads and holds all application configuration from config.ini."""
    
    def __init__(self, config_path='config.ini'):
        parser = configparser.ConfigParser()
        
        self.SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
        # Look for config.ini in the *root* directory (one level up)
        config_file_path = os.path.join(self.SCRIPT_DIR, '..', config_path)

        if not os.path.exists(config_file_path):
            print(f"INFO: Config file not found. Creating default config at: {config_file_path}")
            self._create_default_config(config_file_path)

        parser.read(config_file_path)
        
        self.HOST = parser.get('server', 'host', fallback='0.0.0.0')
        self.PORT = parser.getint('server', 'port', fallback=5001)
        self.DEBUG = parser.getboolean('server', 'debug', fallback=False)
        self.LOG_LEVEL = parser.get('server', 'log_level', fallback='INFO').upper()
        self.APP_VERSION = parser.get('server', 'app_version', fallback='v17.0 (project-caching)')

        self.MAX_CONCURRENT_JOBS = parser.getint('jobs', 'max_concurrent_jobs', fallback=2)
        secrets_str = parser.get('jobs', 'secret_filenames', fallback='secrets.yaml, secrets.yml')
        self.SECRET_FILENAMES = [s.strip() for s in secrets_str.split(',') if s.strip()]

        # Check for environment variable override first
        env_base_dir = os.environ.get('ESPHOME_SERVER_BASE_DIR')
        if env_base_dir:
            # Use environment variable (for Docker)
            self.JOBS_DIR = os.path.join(env_base_dir, 'esphome_jobs')
        else:
            # Use config file setting
            base_dir_config = parser.get('paths', 'base_dir', fallback='esphome_jobs')
            # Use script's PARENT dir (root) as base for relative paths
            root_dir = os.path.join(self.SCRIPT_DIR, '..')
            if os.path.isabs(base_dir_config):
                self.JOBS_DIR = base_dir_config
            else:
                self.JOBS_DIR = os.path.join(root_dir, base_dir_config)
        
        self.LOGS_DIR = os.path.join(self.JOBS_DIR, parser.get('paths', 'logs_dir', fallback='logs'))
        self.PROJECTS_DIR = os.path.join(self.JOBS_DIR, parser.get('paths', 'projects_dir', fallback='projects'))
        self.BINARIES_DIR = os.path.join(self.JOBS_DIR, parser.get('paths', 'binaries_dir', fallback='binaries'))
        self.PLATFORMIO_CACHE_DIR = os.path.join(self.JOBS_DIR, parser.get('paths', 'platformio_cache_dir', fallback='platformio_cache'))

    def _create_default_config(self, config_path):
        """Writes a default config.ini file."""
        default_config = """[server]
# --- Server Settings ---
host = 0.0.0.0
port = 5001
debug = false
log_level = INFO
app_version = v17.0 (project-caching)

[jobs]
# --- Job Settings ---
max_concurrent_jobs = 2
secret_filenames = secrets.yaml, secrets.yml

[paths]
# --- Path Settings ---
# Base directory for all job data.
base_dir = esphome_jobs
logs_dir = logs
# --- NEW: This is the directory that holds all your project build caches ---
projects_dir = projects
binaries_dir = binaries
platformio_cache_dir = platformio_cache
"""
        try:
            with open(config_path, 'w') as f:
                f.write(default_config)
        except IOError as e:
            print(f"FATAL: Could not write default config file to {config_path}: {e}")
            exit(1)

# Create a single, global config instance
config = AppConfig('config.ini')
