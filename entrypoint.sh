#!/bin/bash
set -e

echo "=== Starting manage-machines ==="
echo "Role: $ROLE"
echo "Redis URL: $REDIS_URL"
echo "Python version: $(python --version)"
echo ""

# Run python with unbuffered output
exec python -u main.py "$@"
