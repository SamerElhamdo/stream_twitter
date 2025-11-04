#!/usr/bin/env python3
"""Flask routes for stream server API."""
from flask import Blueprint, request, jsonify, Response, abort
from typing import Optional
import os
import re
import json
import pathlib
from werkzeug.utils import secure_filename

from stream_manager import StreamManager
from utils import require_auth, validate_stream_request
import config

# Create stream manager instance
stream_manager = StreamManager()

# Create Blueprint for routes
api = Blueprint("api", __name__)


@api.route("/start", methods=["POST"])
def start_stream():
    """Start a new stream."""
    require_auth()
    
    body = request.get_json(force=True) or {}
    hls, rtmp, stream_id, extra_args, error = validate_stream_request(body)
    
    if error:
        return jsonify({"error": error}), 400
    
    try:
        pid = stream_manager.start_stream(
            hls=hls,
            rtmp=rtmp,
            stream_id=stream_id,
            extra_args=extra_args
        )
        return jsonify({
            "status": "started",
            "id": stream_id,
            "pid": pid
        }), 200
        
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api.route("/stop", methods=["POST"])
def stop_stream():
    """Stop a running stream."""
    require_auth()
    
    body = request.get_json(force=True) or {}
    stream_id = body.get("id", "stream").strip()
    
    if not stream_id:
        stream_id = "stream"
    
    try:
        pid = stream_manager.stop_stream(stream_id)
        return jsonify({
            "status": "stopped",
            "id": stream_id,
            "pid": pid,
            "note": "Only processes managed by this application were affected"
        }), 200
        
    except FileNotFoundError:
        return jsonify({"error": "Stream is not running"}), 404
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api.route("/kill-and-cleanup", methods=["POST"])
def kill_and_cleanup_stream():
    """
    Kill a specific stream and clean up its files.
    
    SAFE: Only kills processes that have PID files in our PIDS_DIR.
    Does NOT affect other processes on the system.
    """
    require_auth()
    
    body = request.get_json(force=True) or {}
    stream_id = body.get("id", "").strip()
    
    if not stream_id:
        return jsonify({"error": "Stream ID is required"}), 400
    
    try:
        # Try to stop the stream first (this will kill the process if running)
        killed_pid = None
        try:
            killed_pid = stream_manager.stop_stream(stream_id)
        except FileNotFoundError:
            # Stream might not be running, but PID file might still exist
            pass
        
        # Clean up any stale PID files for this specific stream
        cleaned = stream_manager.cleanup_stale_pids()
        cleaned_for_stream = [c for c in cleaned if c.get("id") == stream_id]
        
        return jsonify({
            "status": "killed_and_cleaned",
            "id": stream_id,
            "pid": killed_pid,
            "cleaned": cleaned_for_stream,
            "note": "Only processes managed by this application were affected"
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api.route("/status", methods=["GET"])
def get_status():
    """Get the status of a stream."""
    require_auth()
    
    stream_id = request.args.get("id", "stream").strip()
    if not stream_id:
        stream_id = "stream"
    
    status = stream_manager.get_stream_status(stream_id)
    return jsonify(status), 200


@api.route("/list", methods=["GET"])
def list_streams():
    """
    List all streams with their detailed status.
    No authentication required for UI compatibility.
    """
    streams = stream_manager.list_streams()
    return jsonify({
        "count": len(streams),
        "streams": streams
    }), 200


@api.route("/logs", methods=["GET"])
def get_logs():
    """Get logs for a stream."""
    require_auth()
    
    stream_id = request.args.get("id", "").strip()
    if not stream_id:
        return jsonify({"error": "Stream ID is required"}), 400
    
    try:
        lines = int(request.args.get("lines", "200"))
        lines = max(1, min(lines, 10000))  # Limit between 1 and 10000
    except (ValueError, TypeError):
        lines = 200
    
    try:
        log_content = stream_manager.get_logs(stream_id, lines)
        return Response(log_content, mimetype="text/plain"), 200
    except FileNotFoundError:
        return jsonify({"error": "Log file not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@api.route("/cleanup", methods=["POST"])
def cleanup():
    """
    Clean up stale PID files and optionally kill FFmpeg processes.
    
    SAFE: Only kills FFmpeg processes that were started by this application
    (those with PID files in our PIDS_DIR). Does NOT affect other FFmpeg
    processes running on the system.
    """
    require_auth()
    
    body = request.get_json(silent=True) or {}
    kill_all = bool(body.get("kill_all_ffmpeg", False))
    
    cleaned = stream_manager.cleanup_stale_pids()
    
    if kill_all:
        killed = stream_manager.kill_all_ffmpeg()
        return jsonify({
            "cleaned": cleaned,
            "killed_ffmpeg": killed,
            "note": "Only processes managed by this application were killed"
        }), 200
    
    return jsonify({"cleaned": cleaned}), 200


@api.route("/stop-all", methods=["POST"])
def stop_all_streams():
    """
    Stop all running streams managed by this application.
    
    SAFE: Only stops streams that have PID files in our PIDS_DIR.
    Does NOT affect other FFmpeg processes on the system.
    """
    require_auth()
    
    stopped = stream_manager.stop_all_streams()
    return jsonify({
        "stopped": stopped,
        "note": "Only streams managed by this application were stopped"
    }), 200


@api.route("/m3u/upload", methods=["POST"])
def upload_m3u():
    """Upload M3U file."""
    # No auth required for upload
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.m3u') and not file.filename.endswith('.m3u8'):
        return jsonify({"error": "Invalid file type. Only .m3u and .m3u8 files are allowed"}), 400
    
    try:
        # Create uploads directory if it doesn't exist
        project_dir = pathlib.Path(__file__).parent.absolute()
        uploads_dir = project_dir / "uploads"
        uploads_dir.mkdir(exist_ok=True)
        
        # Save file
        filename = secure_filename(file.filename)
        filepath = uploads_dir / filename
        file.save(str(filepath))
        
        return jsonify({
            "status": "uploaded",
            "filename": filename,
            "path": str(filepath)
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error uploading file: {str(e)}"}), 500


@api.route("/m3u/channels", methods=["GET", "POST"])
def get_m3u_channels():
    """Parse M3U file and return list of channels."""
    # No auth required for reading M3U file
    
    # Support both GET (file path) and POST (file content)
    if request.method == "POST":
        # Parse file content directly from request
        file_content = request.data.decode('utf-8')
    else:
        # Read from file path
        m3u_path = request.args.get("file", "").strip()
        
        if not m3u_path:
            # Try to find uploaded files
            project_dir = pathlib.Path(__file__).parent.absolute()
            uploads_dir = project_dir / "uploads"
            if uploads_dir.exists():
                m3u_files = list(uploads_dir.glob("*.m3u*"))
                if m3u_files:
                    # Use the most recently modified file
                    m3u_path = str(sorted(m3u_files, key=lambda p: p.stat().st_mtime, reverse=True)[0])
            
            if not m3u_path:
                # Try default file
                m3u_path = "tv_channels_wawi_plus.m3u"
        
        # Resolve path relative to project directory
        if not pathlib.Path(m3u_path).is_absolute():
            project_dir = pathlib.Path(__file__).parent.absolute()
            # Check uploads first, then project root
            uploads_path = project_dir / "uploads" / m3u_path
            if uploads_path.exists():
                m3u_path = str(uploads_path)
            else:
                m3u_path = str(project_dir / m3u_path)
        
        if not os.path.exists(m3u_path):
            return jsonify({"error": f"M3U file not found: {m3u_path}"}), 404
        
        try:
            with open(m3u_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
        except Exception as e:
            return jsonify({"error": f"Error reading file: {str(e)}"}), 500
    
    try:
        channels = []
        current_channel = None
        
        for line in file_content.splitlines():
            line = line.strip()
            
            # Skip empty lines and header
            if not line or line == '#EXTM3U':
                continue
            
            # Parse EXTINF line
            if line.startswith('#EXTINF:'):
                # Extract tvg-name and group-title
                name_match = re.search(r'tvg-name="([^"]*)"', line)
                group_match = re.search(r'group-title="([^"]*)"', line)
                logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                
                channel_name = name_match.group(1) if name_match else ""
                group_title = group_match.group(1) if group_match else ""
                logo_url = logo_match.group(1) if logo_match else ""
                
                # Extract channel name from end of line if not in tvg-name
                if not channel_name:
                    parts = line.split(',')
                    if len(parts) > 1:
                        channel_name = parts[-1].strip()
                
                current_channel = {
                    "name": channel_name,
                    "group": group_title,
                    "logo": logo_url,
                    "url": None
                }
            
            # Parse URL line
            elif line.startswith('http') and current_channel:
                current_channel["url"] = line
                channels.append(current_channel)
                current_channel = None
        
        return jsonify({
            "count": len(channels),
            "channels": channels
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error parsing M3U file: {str(e)}"}), 500


@api.route("/settings/save", methods=["POST"])
def save_settings():
    """Save settings to a JSON file."""
    # No auth required for saving settings
    body = request.get_json(force=True) or {}
    
    try:
        # Create settings directory if it doesn't exist
        project_dir = pathlib.Path(__file__).parent.absolute()
        settings_file = project_dir / "settings.json"
        
        # Extract settings from request
        settings = {
            "token": body.get("token", ""),
            "id": body.get("id", ""),
            "hls": body.get("hls", ""),
            "rtmp": body.get("rtmp", ""),
            "image": body.get("image", ""),
            "extra": body.get("extra", "")
        }
        
        # Save to file
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        
        return jsonify({
            "status": "saved",
            "message": "Settings saved successfully",
            "path": str(settings_file)
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error saving settings: {str(e)}"}), 500


@api.route("/settings/load", methods=["GET"])
def load_settings():
    """Load settings from JSON file."""
    # No auth required for loading settings
    try:
        project_dir = pathlib.Path(__file__).parent.absolute()
        settings_file = project_dir / "settings.json"
        
        if not settings_file.exists():
            return jsonify({
                "status": "not_found",
                "message": "No saved settings found",
                "settings": {}
            }), 200
        
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        
        return jsonify({
            "status": "loaded",
            "message": "Settings loaded successfully",
            "settings": settings
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error loading settings: {str(e)}"}), 500


@api.route("/source/check", methods=["POST"])
def check_source():
    """
    Check if HLS source is available and accessible.
    Returns status without actually playing the stream.
    """
    # No auth required for source check
    body = request.get_json(force=True) or {}
    source_url = body.get("url", "").strip()
    
    if not source_url:
        return jsonify({"error": "Source URL is required"}), 400
    
    try:
        import requests
        import time
        
        # timeout للتحقق من المصدر (10 ثوان)
        timeout = 10
        
        # محاولة الوصول إلى ملف M3U8
        start_time = time.time()
        
        try:
            response = requests.head(source_url, timeout=timeout, allow_redirects=True)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                return jsonify({
                    "status": "available",
                    "message": "المصدر متاح",
                    "response_time": round(elapsed, 2),
                    "status_code": response.status_code
                }), 200
            else:
                return jsonify({
                    "status": "unavailable",
                    "message": f"المصدر غير متاح (HTTP {response.status_code})",
                    "response_time": round(elapsed, 2),
                    "status_code": response.status_code
                }), 200
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            return jsonify({
                "status": "timeout",
                "message": "انتهى وقت الانتظار - المصدر بطيء أو غير متاح",
                "response_time": round(elapsed, 2)
            }), 200
            
        except requests.exceptions.ConnectionError:
            elapsed = time.time() - start_time
            return jsonify({
                "status": "unavailable",
                "message": "خطأ في الاتصال - المصدر غير متاح",
                "response_time": round(elapsed, 2)
            }), 200
            
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            return jsonify({
                "status": "error",
                "message": f"خطأ في التحقق: {str(e)}",
                "response_time": round(elapsed, 2)
            }), 200
            
    except ImportError:
        # إذا لم يكن requests متوفر، استخدم urllib
        try:
            from urllib.request import urlopen, Request
            from urllib.error import URLError, HTTPError
            import time
            
            start_time = time.time()
            req = Request(source_url, method='HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0')
            
            try:
                response = urlopen(req, timeout=timeout)
                elapsed = time.time() - start_time
                
                if response.status == 200:
                    return jsonify({
                        "status": "available",
                        "message": "المصدر متاح",
                        "response_time": round(elapsed, 2),
                        "status_code": response.status
                    }), 200
                else:
                    return jsonify({
                        "status": "unavailable",
                        "message": f"المصدر غير متاح (HTTP {response.status})",
                        "response_time": round(elapsed, 2),
                        "status_code": response.status
                    }), 200
                    
            except HTTPError as e:
                elapsed = time.time() - start_time
                return jsonify({
                    "status": "unavailable",
                    "message": f"المصدر غير متاح (HTTP {e.code})",
                    "response_time": round(elapsed, 2),
                    "status_code": e.code
                }), 200
                
            except URLError as e:
                elapsed = time.time() - start_time
                return jsonify({
                    "status": "error",
                    "message": f"خطأ في الاتصال: {str(e.reason)}",
                    "response_time": round(elapsed, 2)
                }), 200
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"خطأ في التحقق: {str(e)}"
            }), 500
            
    except Exception as e:
        return jsonify({"error": f"Error checking source: {str(e)}"}), 500


@api.route("/", methods=["GET"])
def ui():
    """Serve the web UI for stream control."""
    # No auth required for UI page - user enters token in the form
    # Authentication is still required for all API endpoints
    
    # Load HTML template from file
    template_path = pathlib.Path(__file__).parent / "templates" / "index.html"
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
        
        # Replace placeholders with actual values
        html = html.replace('{TOKEN_PLACEHOLDER}', config.WEBHOOK_TOKEN)
        html = html.replace('{RTMP_URL_PLACEHOLDER}', config.RTMP_URL)
    except Exception as e:
        return jsonify({"error": f"Failed to load template: {str(e)}"}), 500
    
    # HTML template is now in templates/index.html
    return Response(html, mimetype="text/html")
