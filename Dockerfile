# 1. Base Image
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# 2. Install System Dependencies
RUN apt-get update && apt-get install -y \
    git \
    ccache \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Python Dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# This is the path for the PlatformIO cache
ENV TRUSTED_PIO_CACHE_DIR=/opt/esphome-cache/platformio
# This ENV must be set *before* any RUN command that uses it
ENV PLATFORMIO_CORE_DIR=${TRUSTED_PIO_CACHE_DIR}

# Configure ccache for compiled object caching
ENV CCACHE_DIR=/opt/esphome-cache/ccache
RUN mkdir -p ${CCACHE_DIR} && \
    ccache --set-config=cache_dir=${CCACHE_DIR} && \
    ccache --set-config=max_size=2G && \
    ccache --set-config=compression=true && \
    ccache --set-config=compression_level=6

# Copy ccache wrapper scripts
COPY docker/inject_ccache.py /usr/local/bin/inject_ccache.py
COPY docker/inject_ccache_wrapper.py /opt/ccache_wrapper.py
COPY docker/esphome-compile-with-ccache.sh /usr/local/bin/esphome-compile-with-ccache.sh
RUN chmod +x /usr/local/bin/inject_ccache.py && \
    chmod +x /usr/local/bin/esphome-compile-with-ccache.sh

# Copy the application code
COPY . .

# Define Volumes for user data
VOLUME /data/esphome_jobs/projects
VOLUME /data/esphome_jobs/binaries
VOLUME /data/esphome_jobs/logs

# Set final environment variables for the running container
ENV ESPHOME_SERVER_BASE_DIR=/data
# This ensures running jobs also use the trusted cache
ENV PLATFORMIO_CORE_DIR=${TRUSTED_PIO_CACHE_DIR}
ENV CCACHE_DIR=/opt/esphome-cache/ccache

# Update config.ini to use /data as base_dir
RUN sed -i 's|^base_dir = esphome_jobs|base_dir = /data/esphome_jobs|' config.ini

# Expose port and run
EXPOSE 5001
CMD ["python3", "run.py"]