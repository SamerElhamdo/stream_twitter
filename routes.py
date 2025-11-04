#!/usr/bin/env python3
"""Flask routes for stream server API."""
from flask import Blueprint, request, jsonify, Response
from typing import Optional

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
            "pid": pid
        }), 200
        
    except FileNotFoundError:
        return jsonify({"error": "Stream is not running"}), 404
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
    """List all streams with their status."""
    require_auth()
    
    streams = stream_manager.list_streams()
    return jsonify(streams), 200


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
    """Clean up stale PID files and optionally kill all FFmpeg processes."""
    require_auth()
    
    body = request.get_json(silent=True) or {}
    kill_all = bool(body.get("kill_all_ffmpeg", False))
    
    cleaned = stream_manager.cleanup_stale_pids()
    
    if kill_all:
        killed = stream_manager.kill_all_ffmpeg()
        return jsonify({
            "cleaned": cleaned,
            "killed_ffmpeg": killed
        }), 200
    
    return jsonify({"cleaned": cleaned}), 200


@api.route("/stop-all", methods=["POST"])
def stop_all_streams():
    """Stop all running streams."""
    require_auth()
    
    stopped = stream_manager.stop_all_streams()
    return jsonify({"stopped": stopped}), 200


@api.route("/", methods=["GET"])
def ui():
    """Serve the web UI for stream control."""
    require_auth()
    
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Stream Control</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ 
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      padding: 20px;
      background: #0a0a0a;
      color: #e0e0e0;
      max-width: 1200px;
      margin: 0 auto;
      line-height: 1.6;
    }}
    h2 {{ color: #0a84ff; margin-top: 0; }}
    h3 {{ color: #5ac8fa; margin-top: 24px; }}
    label {{ 
      display: block;
      margin-top: 12px;
      margin-bottom: 4px;
      color: #aaa;
      font-size: 14px;
      font-weight: 500;
    }}
    input, textarea {{ 
      width: 100%;
      padding: 10px 12px;
      margin: 4px 0 12px 0;
      background: #1a1a1a;
      color: #e0e0e0;
      border: 1px solid #333;
      border-radius: 4px;
      font-size: 14px;
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    }}
    input:focus, textarea:focus {{
      outline: none;
      border-color: #0a84ff;
      box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.2);
    }}
    button {{
      padding: 10px 16px;
      margin: 6px 4px;
      background: #0a84ff;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      transition: background 0.2s;
    }}
    button:hover {{
      background: #0071e3;
    }}
    button:active {{
      background: #0051a5;
    }}
    .button-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 16px 0;
    }}
    pre {{
      background: #000;
      padding: 16px;
      border-radius: 4px;
      max-height: 400px;
      overflow: auto;
      font-size: 12px;
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      border: 1px solid #333;
      white-space: pre-wrap;
      word-wrap: break-word;
    }}
    .section {{
      background: #111;
      padding: 20px;
      border-radius: 8px;
      margin-bottom: 20px;
      border: 1px solid #222;
    }}
    textarea {{
      resize: vertical;
      min-height: 80px;
    }}
  </style>
</head>
<body>
  <h2>Stream Control Panel</h2>
  
  <div class="section">
    <label>Authorization Token</label>
    <input id="token" placeholder="Bearer token" value="Bearer {config.WEBHOOK_TOKEN}" />
    
    <label>Stream ID</label>
    <input id="id" value="full_overlay_test" placeholder="Unique stream identifier" />
    
    <label>HLS URL</label>
    <input id="hls" value="http://5.9.243.47:8080/live/wawi/Yyf6Y7gQwC/664.m3u8" placeholder="Input HLS stream URL" />
    
    <label>RTMP URL</label>
    <input id="rtmp" value="rtmp://live.restream.io/live/re_10661273_event5fdc0f9d1a224a50bb0d78b13c0e953b" placeholder="Output RTMP stream URL" />
    
    <label>Image Path (optional)</label>
    <input id="image" value="/root/straem_twitter/ad_overlay.png" placeholder="Path to overlay image" />
    
    <label>Extra Args (JSON array) — leave empty to copy video</label>
    <textarea id="extra" rows="4" placeholder='["-i", "/path/to/image.png", "-filter_complex", "..."]'>["-i","/root/straem_twitter/ad_overlay.png","-filter_complex","[1:v]scale=iw*min(1280/iw,720/ih):ih*min(1280/iw,720/ih)[scaled];[0:v][scaled]overlay=(W-w)/2:(H-h)/2:format=auto"]</textarea>
  </div>

  <div class="button-group">
    <button onclick="start()">▶ Start Stream</button>
    <button onclick="stop()">■ Stop Stream</button>
    <button onclick="status()">📊 Status</button>
    <button onclick="listStreams()">📋 List All</button>
    <button onclick="viewLogs()">📄 View Logs</button>
  </div>

  <div class="section">
    <h3>Output</h3>
    <pre id="out">Ready...</pre>
  </div>

<script>
function authHeader() {{
  let token = document.getElementById('token').value || '';
  if (!token.startsWith('Bearer ')) {{
    token = 'Bearer ' + token;
  }}
  return token;
}}

async function apiCall(endpoint, method, payload = null) {{
  const options = {{
    method: method,
    headers: {{
      'Content-Type': 'application/json',
      'Authorization': authHeader()
    }}
  }};
  
  if (payload) {{
    options.body = JSON.stringify(payload);
  }}
  
  try {{
    const response = await fetch(endpoint, options);
    const text = await response.text();
    let output = `Status: ${{response.status}} ${{response.statusText}}\\n\\n`;
    
    try {{
      const json = JSON.parse(text);
      output += JSON.stringify(json, null, 2);
    }} catch {{
      output += text;
    }}
    
    document.getElementById('out').textContent = output;
  }} catch (error) {{
    document.getElementById('out').textContent = `Error: ${{error.message}}`;
  }}
}}

async function start() {{
  const payload = {{
    id: document.getElementById('id').value,
    hls: document.getElementById('hls').value,
    rtmp: document.getElementById('rtmp').value,
  }};
  
  const image = document.getElementById('image').value.trim();
  if (image) {{
    payload.image = image;
    payload.overlay_mode = 'full';
  }}
  
  const extraRaw = document.getElementById('extra').value.trim();
  if (extraRaw) {{
    try {{
      payload.extra_args = JSON.parse(extraRaw);
    }} catch (e) {{
      alert('extra_args must be valid JSON array');
      return;
    }}
  }}
  
  await apiCall('/start', 'POST', payload);
}}

async function stop() {{
  const payload = {{ id: document.getElementById('id').value }};
  await apiCall('/stop', 'POST', payload);
}}

async function status() {{
  const id = document.getElementById('id').value;
  await apiCall(`/status?id=${{encodeURIComponent(id)}}`, 'GET');
}}

async function listStreams() {{
  await apiCall('/list', 'GET');
}}

async function viewLogs() {{
  const id = document.getElementById('id').value;
  await apiCall(`/logs?id=${{encodeURIComponent(id)}}&lines=200`, 'GET');
}}
</script>
</body>
</html>"""
    
    return Response(html, mimetype="text/html")
