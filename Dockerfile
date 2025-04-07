# # Use a stable, slim Python base image
# FROM python:3.11-slim

# # Set the working directory inside the container
# WORKDIR /app

# # Install system deps
# RUN apt-get update && apt-get install -y \
#     git ccache\
#     && rm -rf /var/lib/apt/lists/*

# # Install dependencies: Flask (for the server) and ESPHome
# # We use --no-cache-dir to keep the image size smaller
# RUN pip install --no-cache-dir flask esphome

# # Copy your new server script AND its config file
# COPY esphome-compile-job-server.py .
# COPY config.ini .

# # Expose the port the server runs on (from config.ini)
# EXPOSE 5001

# # Define the single persistent volume.
# # This one directory now holds everything:
# #  - /app/esphome_jobs/logs
# #  - /app/esphome_jobs/files
# #  - /app/esphome_jobs/binaries
# #  - /app/esphome_jobs/platformio_cache (thanks to your new config!)
# VOLUME ["/app/esphome_jobs"]

# # The command to run when the container starts
# CMD ["python3", "esphome-compile-job-server.py"]

# 1. Base Image: Use an official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# 2. Install System Dependencies:
#    - 'git' is required by PlatformIO/ESPHome for some dependencies
#    - 'build-essential' and 'python3-dev' for compiling Python packages
RUN apt-get update && apt-get install -y \
    git \
    ccache \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Python Dependencies
#    - Copy *only* requirements.txt first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Install ESPHome & PlatformIO (and pre-cache)
#    This is the "pre-load" step, moved into the build
RUN pip install --no-cache-dir esphome platformio 
# && \
#     # Create dummy files to force pre-caching
#     mkdir -p /tmp/dummy-project && \
#     echo 'esphome:
#       name: dummy32
#       platform: ESP32
#       board: esp32dev
#     ' > /tmp/dummy-project/dummy32.yaml && \
#     echo 'esphome:
#       name: dummy8266
#       platform: ESP8266
#       board: nodemcuv2
#     ' > /tmp/dummy-project/dummy8266.yaml && \
#     # Run the pre-compiles. This will download toolchains.
#     # We point the cache to a *build-time* location.
#     esphome compile /tmp/dummy-project/dummy32.yaml --build-path /tmp/dummy-project/build && \
#     esphome compile /tmp/dummy-project/dummy8266.yaml --build-path /tmp/dummy-project/build && \
#     # Clean up
#     rm -rf /tmp/dummy-project

# 5. Copy the Application Code
#    This includes run.py, config.ini, and the 'app/' directory
COPY . .

# 6. Define Volumes
#    This is where all your persistent data will live on the *host*
VOLUME /data/esphome_jobs/projects
VOLUME /data/esphome_jobs/binaries
VOLUME /data/esphome_jobs/logs
VOLUME /data/esphome_jobs/platformio_cache

# 7. Set environment variables to point to the volumes
#    This tells our app and PlatformIO to use the persistent data volumes
ENV PLATFORMIO_CORE_DIR=/data/esphome_jobs/platformio_cache
# We'll also point the app config to this path
ENV ESPHOME_SERVER_BASE_DIR=/data

# 8. Expose the port and set the run command
EXPOSE 5001
CMD ["python3", "run.py"]

