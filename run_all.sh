#!/usr/bin/env bash
set -e

echo "=== CINEMA AI — Unified Test and Verification Suite ==="
python3 -m pytest tests/ -v
echo "✓ All test suites passed successfully!"
