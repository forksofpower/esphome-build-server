#!/bin/bash
# Wrapper for 'esphome compile' that injects ccache configuration

set -e

if [ $# -lt 2 ]; then
    echo "Usage: esphome-compile-with-ccache.sh <command> <yaml_file>"
    exit 1
fi

COMMAND=$1
YAML_FILE=$2
PROJECT_DIR=$(dirname "$YAML_FILE")

echo "=== ESPHome Compile with ccache ==="
echo "YAML: $YAML_FILE"
echo "Project Dir: $PROJECT_DIR"

# Run ESPHome config phase to generate platformio.ini
echo "Step 1: Generating platformio.ini..."
esphome config "$YAML_FILE" > /dev/null 2>&1 || true

# Find the build directory (ESPHome creates it with device name)
ESPHOME_BUILD_BASE="$PROJECT_DIR/.esphome/build"
echo "Step 2: Looking for build directory at $ESPHOME_BUILD_BASE"

if [ -d "$ESPHOME_BUILD_BASE" ]; then
    # Find the actual build dir (usually named after the device)
    BUILD_DIR=$(find "$ESPHOME_BUILD_BASE" -maxdepth 1 -type d ! -path "$ESPHOME_BUILD_BASE" | head -1)
    
    if [ -n "$BUILD_DIR" ]; then
        echo "  Found build dir: $BUILD_DIR"
        
        # Copy ccache wrapper script
        echo "Step 3: Copying ccache wrapper script..."
        cp /opt/ccache_wrapper.py "$BUILD_DIR/inject_ccache_wrapper.py"
        echo "  ✓ Copied wrapper to $BUILD_DIR/inject_ccache_wrapper.py"
        
        # Modify platformio.ini
        PLATFORMIO_INI="$BUILD_DIR/platformio.ini"
        if [ -f "$PLATFORMIO_INI" ]; then
            echo "Step 4: Injecting ccache into platformio.ini..."
            
            # Check if already injected
            if ! grep -q "inject_ccache_wrapper" "$PLATFORMIO_INI"; then
                # Add to existing extra_scripts line or create new one
                if grep -q "^extra_scripts" "$PLATFORMIO_INI"; then
                    # Append to existing extra_scripts
                    sed -i '/^extra_scripts/a \    pre:inject_ccache_wrapper.py' "$PLATFORMIO_INI"
                else
                    # Add new extra_scripts after [env:xxx] section
                    sed -i '/^\[env:/a extra_scripts =\n    pre:inject_ccache_wrapper.py' "$PLATFORMIO_INI"
                fi
                echo "  ✓ Injected ccache wrapper into platformio.ini"
            else
                echo "  ✓ ccache wrapper already configured"
            fi
        else
            echo "  ✗ platformio.ini not found at $PLATFORMIO_INI"
        fi
    else
        echo "  ✗ Could not find build directory under $ESPHOME_BUILD_BASE"
    fi
else
    echo "  ✗ Build base directory does not exist: $ESPHOME_BUILD_BASE"
fi

# Step 5: Run the actual compile command
echo "Step 5: Running compilation..."
esphome "$COMMAND" "$YAML_FILE"
