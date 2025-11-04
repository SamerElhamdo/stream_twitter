#!/usr/bin/env python3
"""Gunicorn configuration file for stream server."""
import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5

# Logging
accesslog = "/var/log/stream-server/access.log"
errorlog = "/var/log/stream-server/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "stream-server"

# Server mechanics
daemon = False
pidfile = "/var/run/stream-server.pid"
umask = 0o007
user = None  # Set to user name or UID
group = None  # Set to group name or GID
tmp_upload_dir = None

# SSL (if needed in future)
# keyfile = None
# certfile = None
