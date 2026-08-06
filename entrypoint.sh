#!/bin/sh
set -e

mkdir -p /app/data
chown -R stokvel:stokvel /app/data

exec su -s /bin/sh stokvel -c "PATH=/home/stokvel/.local/bin:\$PATH gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --timeout 120 --max-requests 60 --max-requests-jitter 15 app:app"
