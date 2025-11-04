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
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 16px;
      background: #1a1a1a;
      border-radius: 4px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid #333;
    }}
    th {{
      background: #222;
      color: #0a84ff;
      font-weight: 600;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    td {{
      color: #e0e0e0;
      font-size: 13px;
    }}
    tr:hover {{
      background: #252525;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .status-running {{
      background: #34c759;
      color: #fff;
    }}
    .status-stopped {{
      background: #ff3b30;
      color: #fff;
    }}
    .action-buttons {{
      display: flex;
      gap: 6px;
    }}
    .action-buttons button {{
      padding: 6px 12px;
      font-size: 12px;
      margin: 0;
    }}
    .refresh-indicator {{
      color: #666;
      font-size: 12px;
      margin-top: 8px;
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
    <input id="rtmp" value="{config.RTMP_URL}" placeholder="Output RTMP stream URL" />
    
    <label>Image Path (optional)</label>
    <input id="image" value="" placeholder="Path to overlay image" />
    
    <label>Extra Args (JSON array) — leave empty to copy video</label>
    <textarea id="extra" rows="4"></textarea>
  </div>

  <div class="button-group">
    <button onclick="start()">▶ Start Stream</button>
    <button onclick="stop()">■ Stop Stream</button>
    <button onclick="status()">📊 Status</button>
    <button onclick="refreshStreamsTable()">🔄 Refresh</button>
    <button onclick="viewLogs()">📄 View Logs</button>
    <button onclick="saveSettings()" style="background: #34c759;">💾 حفظ الإعدادات</button>
  </div>

  <div class="section">
    <h3>Running Streams <span id="streamsCount" style="color: #666; font-size: 14px; font-weight: normal;">(0)</span></h3>
    <div id="streamsTableContainer">
      <table id="streamsTable">
        <thead>
          <tr>
            <th>Stream ID</th>
            <th>Status</th>
            <th>PID</th>
            <th>Uptime</th>
            <th>Log Size</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="streamsTableBody">
          <tr>
            <td colspan="6" style="text-align: center; color: #666; padding: 20px;">
              Loading streams...
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="refresh-indicator">
      Auto-refresh: <span id="autoRefreshStatus">Enabled</span> | 
      Last updated: <span id="lastUpdate">Never</span>
      <button onclick="toggleAutoRefresh()" style="margin-left: 12px; padding: 4px 8px; font-size: 11px;">Toggle Auto-Refresh</button>
    </div>
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

// Streams table management
let autoRefreshInterval = null;
let autoRefreshEnabled = true;

function formatUptime(seconds) {{
  if (!seconds) return 'N/A';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) {{
    return `${{hours}}h ${{minutes}}m ${{secs}}s`;
  }} else if (minutes > 0) {{
    return `${{minutes}}m ${{secs}}s`;
  }} else {{
    return `${{secs}}s`;
  }}
}}

function formatSize(bytes) {{
  if (!bytes || bytes === 0) return '0 B';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}}

async function refreshStreamsTable() {{
  try {{
    const response = await fetch('/list', {{
      method: 'GET',
      headers: {{
        'Authorization': authHeader()
      }}
    }});
    
    const result = await response.json();
    const tbody = document.getElementById('streamsTableBody');
    const countSpan = document.getElementById('streamsCount');
    
    if (response.ok && result.streams) {{
      const streams = result.streams;
      countSpan.textContent = `(${{streams.length}})`;
      
      if (streams.length === 0) {{
        tbody.innerHTML = `
          <tr>
            <td colspan="6" style="text-align: center; color: #666; padding: 20px;">
              No streams found
            </td>
          </tr>
        `;
      }} else {{
        tbody.innerHTML = streams.map(stream => {{
          const statusClass = stream.running ? 'status-running' : 'status-stopped';
          const statusText = stream.running ? 'Running' : 'Stopped';
          const uptime = stream.uptime_seconds ? formatUptime(stream.uptime_seconds) : 'N/A';
          const logSize = formatSize(stream.log_size || 0);
          const streamId = stream.id;
          
          return `
            <tr>
              <td><strong>${{stream.id}}</strong></td>
              <td><span class="status-badge ${{statusClass}}">${{statusText}}</span></td>
              <td style="font-family: monospace;">${{stream.pid || 'N/A'}}</td>
              <td>${{uptime}}</td>
              <td>${{logSize}}</td>
              <td>
                <div class="action-buttons">
                  ${{stream.running ? 
                    `<button onclick="stopStream('` + streamId + `')" style="background: #ff3b30;" title="إيقاف المعالجة">⏹ إيقاف</button>
                     <button onclick="viewStreamLogs('` + streamId + `')" title="عرض السجلات">📄 سجلات</button>
                     <button onclick="killAndDeleteStream('` + streamId + `')" style="background: #8e0000;" title="قتل وحذف المعالجة">🗑️ حذف</button>` : 
                    `<button onclick="cleanupStream('` + streamId + `')" style="background: #666;" title="تنظيف وحذف المعالجة العالقة">🗑️ حذف</button>`
                  }}
                </div>
              </td>
            </tr>
          `;
        }}).join('');
      }}
      
      document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
    }} else {{
      tbody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; color: #ff3b30; padding: 20px;">
            Error loading streams: ${{result.error || 'Unknown error'}}
          </td>
        </tr>
      `;
    }}
  }} catch (error) {{
    const tbody = document.getElementById('streamsTableBody');
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: #ff3b30; padding: 20px;">
          Error: ${{error.message}}
        </td>
      </tr>
    `;
  }}
}}

async function stopStream(streamId) {{
  if (!confirm(`هل أنت متأكد من إيقاف المعالجة "${{streamId}}"?`)) {{
    return;
  }}
  
  try {{
    // إظهار حالة التحميل
    const row = document.querySelector(`tr:has(button[onclick*="'${{streamId}}'"])`);
    if (row) {{
      const statusBadge = row.querySelector('.status-badge');
      if (statusBadge) {{
        statusBadge.textContent = 'إيقاف...';
        statusBadge.style.background = '#ff9500';
      }}
    }}
    
    const response = await fetch('/stop', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'Authorization': authHeader()
      }},
      body: JSON.stringify({{ id: streamId }})
    }});
    
    const result = await response.json();
    
    if (response.ok) {{
      alert(`✅ تم إيقاف المعالجة "${{streamId}}" بنجاح`);
      document.getElementById('out').textContent = `✅ تم إيقاف المعالجة "${{streamId}}" بنجاح\\n${{JSON.stringify(result, null, 2)}}`;
      
      // تحديث الجدول مع أنيميشن
      if (row) {{
        row.style.transition = 'background-color 0.3s';
        row.style.backgroundColor = '#ff3b3020';
        setTimeout(() => {{
          refreshStreamsTable();
        }}, 500);
      }} else {{
        setTimeout(refreshStreamsTable, 500);
      }}
    }} else {{
      alert(`❌ خطأ في إيقاف المعالجة: ${{result.error || 'Unknown error'}}`);
      document.getElementById('out').textContent = `❌ خطأ في إيقاف المعالجة: ${{result.error || 'Unknown error'}}`;
      // إعادة تحديث الجدول لإزالة حالة التحميل
      setTimeout(refreshStreamsTable, 500);
    }}
  }} catch (error) {{
    alert(`❌ خطأ: ${{error.message}}`);
    document.getElementById('out').textContent = `❌ خطأ: ${{error.message}}`;
    setTimeout(refreshStreamsTable, 500);
  }}
}}

async function viewStreamLogs(streamId) {{
  document.getElementById('id').value = streamId;
  await viewLogs();
}}

async function killAndDeleteStream(streamId) {{
  if (!confirm(`⚠️ تحذير: هل أنت متأكد من قتل وحذف المعالجة "${{streamId}}"?\\n\\nسيتم:\\n- قتل العملية الخاصة بهذه المعالجة فقط\\n- حذف ملفات PID والسجلات المتعلقة\\n\\n⚠️ سيتم التأثير فقط على معالجات هذا المشروع`)) {{
    return;
  }}
  
  try {{
    // إظهار حالة التحميل
    const row = document.querySelector(`tr:has(button[onclick*="'${{streamId}}'"])`);
    if (row) {{
      row.style.transition = 'opacity 0.3s';
      row.style.opacity = '0.5';
      const statusBadge = row.querySelector('.status-badge');
      if (statusBadge) {{
        statusBadge.textContent = 'جاري الحذف...';
        statusBadge.style.background = '#8e0000';
      }}
    }}
    
    // استخدام endpoint مخصص لقتل وحذف معالجة محددة فقط
    const response = await fetch('/kill-and-cleanup', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'Authorization': authHeader()
      }},
      body: JSON.stringify({{ id: streamId }})
    }});
    
    const result = await response.json();
    
    if (response.ok) {{
      alert(`✅ تم قتل وحذف المعالجة "${{streamId}}" بنجاح\\n\\nملاحظة: تم التأثير فقط على معالجات هذا المشروع`);
      document.getElementById('out').textContent = `✅ تم قتل وحذف المعالجة "${{streamId}}" بنجاح\\n\\nملاحظة: ${{result.note || 'تم التأثير فقط على معالجات هذا المشروع'}}\\n${{JSON.stringify(result, null, 2)}}`;
      
      // إخفاء الصف من الجدول مع أنيميشن
      if (row) {{
        row.style.transition = 'opacity 0.3s, transform 0.3s';
        row.style.opacity = '0';
        row.style.transform = 'translateX(-100%)';
        setTimeout(() => {{
          refreshStreamsTable();
        }}, 300);
      }} else {{
        setTimeout(refreshStreamsTable, 500);
      }}
    }} else {{
      alert(`❌ خطأ في حذف المعالجة: ${{result.error || 'Unknown error'}}`);
      document.getElementById('out').textContent = `❌ خطأ في حذف المعالجة: ${{result.error || 'Unknown error'}}`;
      if (row) {{
        row.style.opacity = '1';
      }}
      setTimeout(refreshStreamsTable, 500);
    }}
  }} catch (error) {{
    alert(`❌ خطأ: ${{error.message}}`);
    document.getElementById('out').textContent = `❌ خطأ: ${{error.message}}`;
    setTimeout(refreshStreamsTable, 500);
  }}
}}

async function cleanupStream(streamId) {{
  if (!confirm(`هل أنت متأكد من حذف المعالجة العالقة "${{streamId}}"?\\nسيتم قتل العملية وحذف الملفات المتعلقة.\\n\\n⚠️ سيتم التأثير فقط على معالجات هذا المشروع`)) {{
    return;
  }}
  
  try {{
    // استخدام endpoint مخصص لقتل وحذف معالجة محددة فقط
    const response = await fetch('/kill-and-cleanup', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'Authorization': authHeader()
      }},
      body: JSON.stringify({{ id: streamId }})
    }});
    
    const result = await response.json();
    
    if (response.ok) {{
      alert(`✅ تم تنظيف المعالجة العالقة "${{streamId}}" بنجاح`);
      document.getElementById('out').textContent = `✅ تم تنظيف وحذف المعالجة "${{streamId}}"\\n\\nملاحظة: ${{result.note || 'تم التأثير فقط على معالجات هذا المشروع'}}\\n${{JSON.stringify(result, null, 2)}}`;
      
      // إخفاء الصف من الجدول مع أنيميشن
      const row = document.querySelector(`tr:has(button[onclick*="'${{streamId}}'"])`);
      if (row) {{
        row.style.transition = 'opacity 0.3s';
        row.style.opacity = '0';
        setTimeout(() => {{
          refreshStreamsTable();
        }}, 300);
      }} else {{
        // تحديث الجدول بعد قليل
        setTimeout(refreshStreamsTable, 500);
      }}
    }} else {{
      alert(`❌ خطأ في تنظيف المعالجة: ${{result.error || 'Unknown error'}}`);
      document.getElementById('out').textContent = `❌ خطأ في تنظيف المعالجة: ${{result.error || 'Unknown error'}}`;
    }}
  }} catch (error) {{
    alert(`❌ خطأ: ${{error.message}}`);
    document.getElementById('out').textContent = `❌ خطأ: ${{error.message}}`;
  }}
}}

function toggleAutoRefresh() {{
  autoRefreshEnabled = !autoRefreshEnabled;
  document.getElementById('autoRefreshStatus').textContent = autoRefreshEnabled ? 'Enabled' : 'Disabled';
  
  if (autoRefreshEnabled) {{
    startAutoRefresh();
  }} else {{
    stopAutoRefresh();
  }}
}}

function startAutoRefresh() {{
  stopAutoRefresh(); // Clear existing interval
  refreshStreamsTable(); // Initial load
  autoRefreshInterval = setInterval(refreshStreamsTable, 5000); // Refresh every 5 seconds
}}

function stopAutoRefresh() {{
  if (autoRefreshInterval) {{
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
  }}
}}

async function saveSettings() {{
  const settings = {{
    token: document.getElementById('token').value,
    id: document.getElementById('id').value,
    hls: document.getElementById('hls').value,
    rtmp: document.getElementById('rtmp').value,
    image: document.getElementById('image').value,
    extra: document.getElementById('extra').value
  }};
  
  try {{
    const response = await fetch('/settings/save', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json'
      }},
      body: JSON.stringify(settings)
    }});
    
    const result = await response.json();
    
    if (response.ok) {{
      // إظهار رسالة تأكيد
      alert('✅ تم حفظ الإعدادات بنجاح!');
      document.getElementById('out').textContent = `✅ الإعدادات تم حفظها بنجاح\\n${{JSON.stringify(result, null, 2)}}`;
    }} else {{
      alert('❌ خطأ في حفظ الإعدادات: ' + (result.error || 'Unknown error'));
      document.getElementById('out').textContent = `❌ خطأ في حفظ الإعدادات: ${{result.error || 'Unknown error'}}`;
    }}
  }} catch (error) {{
    alert('❌ خطأ: ' + error.message);
    document.getElementById('out').textContent = `❌ خطأ: ${{error.message}}`;
  }}
}}

async function loadSettings() {{
  try {{
    // انتظر قليلاً للتأكد من أن DOM جاهز تماماً
    await new Promise(resolve => setTimeout(resolve, 100));
    
    const response = await fetch('/settings/load');
    const result = await response.json();
    
    console.log('Settings load response:', result);
    
    if (response.ok && result.status === 'loaded' && result.settings) {{
      const settings = result.settings;
      let loadedCount = 0;
      
      // التحقق من وجود العناصر قبل تعيين القيم
      const tokenEl = document.getElementById('token');
      const idEl = document.getElementById('id');
      const hlsEl = document.getElementById('hls');
      const rtmpEl = document.getElementById('rtmp');
      const imageEl = document.getElementById('image');
      const extraEl = document.getElementById('extra');
      
      if (tokenEl && settings.token !== undefined && settings.token !== null && settings.token !== '') {{
        tokenEl.value = settings.token;
        loadedCount++;
        console.log('Loaded token:', settings.token);
      }}
      if (idEl && settings.id !== undefined && settings.id !== null && settings.id !== '') {{
        idEl.value = settings.id;
        loadedCount++;
        console.log('Loaded id:', settings.id);
      }}
      if (hlsEl && settings.hls !== undefined && settings.hls !== null && settings.hls !== '') {{
        hlsEl.value = settings.hls;
        loadedCount++;
        console.log('Loaded hls:', settings.hls);
      }}
      if (rtmpEl && settings.rtmp !== undefined && settings.rtmp !== null && settings.rtmp !== '') {{
        rtmpEl.value = settings.rtmp;
        loadedCount++;
        console.log('Loaded rtmp:', settings.rtmp);
      }}
      if (imageEl && settings.image !== undefined && settings.image !== null && settings.image !== '') {{
        imageEl.value = settings.image;
        loadedCount++;
        console.log('Loaded image:', settings.image);
      }}
      if (extraEl && settings.extra !== undefined && settings.extra !== null && settings.extra !== '') {{
        extraEl.value = settings.extra;
        loadedCount++;
        console.log('Loaded extra:', settings.extra);
      }}
      
      if (loadedCount > 0) {{
        const message = `✅ تم تحميل الإعدادات المحفوظة (${{loadedCount}} حقول)`;
        console.log(message);
        document.getElementById('out').textContent = message;
      }} else {{
        const message = `ℹ️ تم تحميل الإعدادات لكن جميع الحقول فارغة`;
        console.log(message);
        document.getElementById('out').textContent = message;
      }}
    }} else if (result.status === 'not_found') {{
      // No saved settings, use defaults - this is fine
      const message = `ℹ️ لا توجد إعدادات محفوظة، سيتم استخدام القيم الافتراضية`;
      console.log(message);
      document.getElementById('out').textContent = message;
    }} else {{
      console.log('Unexpected response:', result);
      document.getElementById('out').textContent = `⚠️ استجابة غير متوقعة: ${{JSON.stringify(result)}}`;
    }}
  }} catch (error) {{
    console.error('Error loading settings:', error);
    document.getElementById('out').textContent = `⚠️ خطأ في تحميل الإعدادات: ${{error.message}}`;
  }}
}}

// Load channels and streams on page load
window.addEventListener('DOMContentLoaded', () => {{
  console.log('DOM loaded, starting initialization...');
  // تحميل الإعدادات أولاً مع تأخير صغير للتأكد من جاهزية DOM
  setTimeout(() => {{
    loadSettings();
  }}, 200);
  loadChannels();
  startAutoRefresh();
}});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {{
  stopAutoRefresh();
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
  // Refresh streams table after starting
  setTimeout(refreshStreamsTable, 1000);
}}

async function stop() {{
  const payload = {{ id: document.getElementById('id').value }};
  await apiCall('/stop', 'POST', payload);
  // Refresh streams table after stopping
  setTimeout(refreshStreamsTable, 1000);
}}

async function status() {{
  const id = document.getElementById('id').value;
  await apiCall(`/status?id=${{encodeURIComponent(id)}}`, 'GET');
}}

async function listStreams() {{
  await refreshStreamsTable();
}}

async function viewLogs() {{
  const id = document.getElementById('id').value;
  await apiCall(`/logs?id=${{encodeURIComponent(id)}}&lines=200`, 'GET');
}}
</script>
</body>
</html>"""
    
    return Response(html, mimetype="text/html")
