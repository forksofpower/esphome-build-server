#!/usr/bin/env python3
"""
Script to inject ccache configuration into ESPHome-generated platformio.ini files.
This gets called before compilation to wrap the toolchain compilers with ccache.
"""

import os
import sys

def inject_ccache_into_platformio_ini(project_dir):
    """
    Modifies the platformio.ini file in the project directory to use ccache.
    """
    platformio_ini = os.path.join(project_dir, '.esphome', 'build', 'platformio.ini')
    
    if not os.path.exists(platformio_ini):
        print(f"platformio.ini not found at {platformio_ini}")
        return False
    
    with open(platformio_ini, 'r') as f:
        content = f.read()
    
    # Check if ccache is already configured
    if 'build_unflags' in content and '-fno-' in content:
        print("platformio.ini already has ccache configuration")
        return True
    
    # Inject ccache configuration into the [env] section
    ccache_config = """
; Enable ccache for faster recompilation
build_unflags = 
    -fno-rtti
build_flags = 
    ${env.build_flags}
    -fno-rtti

; Use ccache as compiler wrapper
; This wraps xtensa-esp32-elf-gcc, xtensa-esp32-elf-g++, etc.
extra_scripts = 
    pre:inject_ccache_wrapper.py
"""
    
    # Find the [env] or [env:NAME] section
    lines = content.split('\n')
    env_section_idx = -1
    
    for i, line in enumerate(lines):
        if line.strip().startswith('[env'):
            env_section_idx = i
            break
    
    if env_section_idx == -1:
        print("Could not find [env] section in platformio.ini")
        return False
    
    # Insert after the [env] line
    lines.insert(env_section_idx + 1, ccache_config)
    
    with open(platformio_ini, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"Successfully injected ccache config into {platformio_ini}")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: inject_ccache.py <project_dir>")
        sys.exit(1)
    
    project_dir = sys.argv[1]
    success = inject_ccache_into_platformio_ini(project_dir)
    sys.exit(0 if success else 1)
