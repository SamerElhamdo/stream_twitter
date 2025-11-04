#!/usr/bin/env python3
"""Flask routes for stream server API."""
from flask import Blueprint, request, jsonify, Response
from typing import Optional
import os
import re
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


@api.route("/", methods=["GET"])
def ui():
    """Serve the web UI for stream control."""
    # No auth required for UI page - user enters token in the form
    # Authentication is still required for all API endpoints
    
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
        input, textarea, select {{
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
    input:focus, textarea:focus, select:focus {{
      outline: none;
      border-color: #0a84ff;
      box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.2);
    }}
    select {{
      cursor: pointer;
    }}
    input[type="file"] {{
      padding: 8px;
      cursor: pointer;
    }}
    .channel-select-group {{
      display: flex;
      gap: 8px;
      align-items: flex-end;
    }}
    .channel-select-group select {{
      flex: 1;
    }}
    .channel-select-group button {{
      flex: 0 0 auto;
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
    <h3>M3U Channel Selector</h3>
    <label>Upload M3U File</label>
    <input type="file" id="m3uFile" accept=".m3u,.m3u8" />
    <button onclick="uploadM3U()" style="margin-top: 8px;">📤 Upload & Load Channels</button>
    
    <label style="margin-top: 20px;">Select Channel</label>
    <div class="channel-select-group">
      <select id="channelSelect" onchange="selectChannel()">
        <option value="">-- Select a channel --</option>
      </select>
      <button onclick="loadChannels()">🔄 Reload Channels</button>
    </div>
    <small style="color: #666; display: block; margin-top: -8px; margin-bottom: 12px;">
      Total channels: <span id="channelCount">0</span>
    </small>
  </div>
  
  <div class="section">
    <h3>Stream Settings</h3>
    <label>Authorization Token</label>
    <input id="token" placeholder="Bearer token" value="Bearer {config.WEBHOOK_TOKEN}" />
    
    <label>Stream ID</label>
    <input id="id" value="full_overlay_test" placeholder="Unique stream identifier" />
    
    <label>HLS URL</label>
    <input id="hls" value="http://5.9.243.47:8080/live/wawi/Yyf6Y7gQwC/664.m3u8" placeholder="Input HLS stream URL" />
    
    <label>RTMP URL</label>
    <input id="rtmp" value="rtmp://live.restream.io/live/re_10661273_event5fdc0f9d1a224a50bb0d78b13c0e953b" placeholder="Output RTMP stream URL" />
    
    <label>Image Path (optional)</label>
    <input id="image" value="{config.OVERLAY_IMAGE_DEFAULT}" placeholder="Path to overlay image" />
    
    <label>Extra Args (JSON array) — leave empty to copy video</label>
    <textarea id="extra" rows="4" placeholder='["-i", "/path/to/image.png", "-filter_complex", "..."]'>["-i","{config.OVERLAY_IMAGE_DEFAULT}","-filter_complex","[0:v][1:v]overlay=(W-w)/2:(H-h)/2:format=auto"]</textarea>
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
let channelsData = [];

function authHeader() {{
  let token = document.getElementById('token').value || '';
  if (!token.startsWith('Bearer ')) {{
    token = 'Bearer ' + token;
  }}
  return token;
}}

async function uploadM3U() {{
  const fileInput = document.getElementById('m3uFile');
  const file = fileInput.files[0];
  
  if (!file) {{
    alert('Please select a file first');
    return;
  }}
  
  const formData = new FormData();
  formData.append('file', file);
  
  try {{
    const response = await fetch('/m3u/upload', {{
      method: 'POST',
      body: formData
    }});
    
    const result = await response.json();
    
    if (response.ok) {{
      document.getElementById('out').textContent = `File uploaded successfully: ${{result.filename}}\\n\\n${{JSON.stringify(result, null, 2)}}`;
      // Automatically load channels after upload
      await loadChannels();
    }} else {{
      document.getElementById('out').textContent = `Error: ${{result.error}}`;
    }}
  }} catch (error) {{
    document.getElementById('out').textContent = `Error: ${{error.message}}`;
  }}
}}

async function loadChannels() {{
  try {{
    const response = await fetch('/m3u/channels');
    const result = await response.json();
    
    if (response.ok && result.channels) {{
      channelsData = result.channels;
      const select = document.getElementById('channelSelect');
      
      // Clear existing options except the first one
      select.innerHTML = '<option value="">-- Select a channel --</option>';
      
      // Group channels by group title
      const groupedChannels = {{}};
      result.channels.forEach((channel, index) => {{
        const group = channel.group || 'Other';
        if (!groupedChannels[group]) {{
          groupedChannels[group] = [];
        }}
        groupedChannels[group].push({{...channel, index}});
      }});
      
      // Add options grouped by category
      Object.keys(groupedChannels).sort().forEach(group => {{
        const optgroup = document.createElement('optgroup');
        optgroup.label = group;
        
        groupedChannels[group].forEach(channel => {{
          const option = document.createElement('option');
          option.value = channel.index;
          option.textContent = channel.name || 'Unnamed Channel';
          optgroup.appendChild(option);
        }});
        
        select.appendChild(optgroup);
      }});
      
      document.getElementById('channelCount').textContent = result.count;
      document.getElementById('out').textContent = `Loaded ${{result.count}} channels from M3U file`;
    }} else {{
      document.getElementById('out').textContent = `Error: ${{result.error || 'Failed to load channels'}}`;
    }}
  }} catch (error) {{
    document.getElementById('out').textContent = `Error: ${{error.message}}`;
  }}
}}

function selectChannel() {{
  const select = document.getElementById('channelSelect');
  const selectedIndex = select.value;
  
  if (selectedIndex && channelsData[selectedIndex]) {{
    const channel = channelsData[selectedIndex];
    document.getElementById('hls').value = channel.url || '';
    document.getElementById('id').value = channel.name.toLowerCase().replace(/[^a-z0-9]+/g, '_') || 'channel_stream';
    
    document.getElementById('out').textContent = `Selected channel: ${{channel.name}}\\nGroup: ${{channel.group || 'N/A'}}\\nURL: ${{channel.url}}`;
  }}
}}

// Load channels on page load
window.addEventListener('DOMContentLoaded', () => {{
  loadChannels();
}});

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
