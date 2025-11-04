#!/usr/bin/env python3
"""Configuration module for stream server."""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# Server Configuration
APP_PORT = int(os.getenv("PORT", "3000"))
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "CHANGE_ME")

RTMP_URL = os.getenv("RTMP_URL", "rtmp://live.example.com/live/stream_key")

# Paths Configuration
BASE_DIR = pathlib.Path(os.getenv("STREAM_CTL_DIR", "/var/streamctl"))
PIDS_DIR = BASE_DIR / "pids"
LOGS_DIR = BASE_DIR / "logs"

# FFmpeg Configuration
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "/usr/bin/ffmpeg")

# Video Encoding Defaults
VIDEO_CODEC = "libx264"
VIDEO_PRESET = "veryfast"
VIDEO_TUNE = "zerolatency"
VIDEO_BITRATE = "2000k"

# Audio Encoding Defaults
AUDIO_CODEC = "aac"
AUDIO_SAMPLE_RATE = "44100"
AUDIO_BITRATE = "128k"

# Overlay Image Configuration
# Default overlay image path (can be overridden via API)
OVERLAY_IMAGE_DEFAULT = os.getenv("OVERLAY_IMAGE", "overlay_straem.png")
# Get absolute path if relative path is provided
if not pathlib.Path(OVERLAY_IMAGE_DEFAULT).is_absolute():
    PROJECT_DIR = pathlib.Path(__file__).parent.absolute()
    OVERLAY_IMAGE_DEFAULT = str(PROJECT_DIR / OVERLAY_IMAGE_DEFAULT)

# Create necessary directories
for directory in (PIDS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
