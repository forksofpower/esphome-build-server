"""
PlatformIO extra script to wrap compilers with ccache.
Based on https://github.com/platformio/platformio-core/issues/5018
"""

Import("env")
import os

# Get ccache directory from environment
ccache_dir = os.environ.get('CCACHE_DIR', '/opt/esphome-cache/ccache')

print("=" * 60)
print("ENABLING CCACHE FOR COMPILATION")
print(f"CCACHE_DIR: {ccache_dir}")
print("=" * 60)

# Set ccache environment variables for the build
env['ENV']['CCACHE_DIR'] = ccache_dir
env['ENV']['CCACHE_COMPRESS'] = '1'
env['ENV']['CCACHE_COMPRESSLEVEL'] = '6'
env['ENV']['CCACHE_MAXSIZE'] = '2G'

# PlatformIO uses SCons which respects these wrappers
# This wraps ALL compilers including cross-compilers like xtensa-esp32-elf-gcc
original_cc = env.get('CC')
original_cxx = env.get('CXX')

print(f"Original CC: {original_cc}")
print(f"Original CXX: {original_cxx}")

# Wrap compilers - ccache will handle all the caching
if 'ccache' not in str(original_cc):
    env.Replace(CC='ccache $CC')
    print(f"✓ Wrapped CC with ccache")

if 'ccache' not in str(original_cxx):
    env.Replace(CXX='ccache $CXX')
    print(f"✓ Wrapped CXX with ccache")

print(f"New CC: {env['CC']}")
print(f"New CXX: {env['CXX']}")
print("=" * 60)
