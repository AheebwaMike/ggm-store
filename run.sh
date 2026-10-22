#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "Starting Gunicorn server..."
uv run gunicorn core.wsgi:application --bind 0.0.0.0:$PORT