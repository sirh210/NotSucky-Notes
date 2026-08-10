#!/usr/bin/env python3
"""Dump main.py contents to stdout with UTF-8 encoding."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()
print(content)
