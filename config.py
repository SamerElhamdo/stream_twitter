#!/usr/bin/env python3
"""Configuration module for stream server."""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# Server Configuration
APP_PORT = int(os.getenv("PORT", "3000"))
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "CHANGE_ME")

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

# Create necessary directories
for directory in (PIDS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
