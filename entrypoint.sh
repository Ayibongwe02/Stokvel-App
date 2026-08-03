#!/bin/sh
# Runs as root (briefly) so it can fix ownership on a freshly-mounted
# Render persistent disk at /app/data, which mounts owned by root and
# overrides whatever the image's build-time chown set — then drops to
# the unprivileged 'stokvel' user before actually starting the app.
set -e

mkdir -p /app/data
chown -R stokvel:stokvel /app/data

exec su -s /bin/sh stokvel -c "PATH=/home/stokvel/.local/bin:\$PATH gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --timeout 120 --max-requests 60 --max-requests-jitter 15 app:app"
