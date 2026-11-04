#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "Installing uv..."
pip install uv

echo "Installing dependencies..."
uv sync

echo "Building CSS..."
bash scripts/build_css.sh

echo "Collecting static files..."
uv run python manage.py collectstatic --no-input

echo "Running migrations..."
uv run python manage.py migrate