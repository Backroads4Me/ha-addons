#!/usr/bin/env python3
import py_compile
import sys

try:
    py_compile.compile('C:/GitHub/ha-addons/bluetooth-wifi-setup/rootfs/usr/local/btwifiset/btwifiset.py', doraise=True)
    print("SUCCESS: No syntax errors found!")
    sys.exit(0)
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR FOUND:")
    print(f"  File: {e.file}")
    print(f"  Message: {e.msg}")
    print(f"  Details: {e.exc_value}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
