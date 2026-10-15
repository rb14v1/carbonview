#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python -m pip install -r requirements.txt
exec gunicorn config.wsgi:application --bind=0.0.0.0:8000