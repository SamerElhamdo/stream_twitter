#!/usr/bin/env python3
"""Stream manager module for handling FFmpeg processes."""
import os
import pathlib
import signal
import subprocess
import time
from typing import Optional, Dict, Any

import config


class StreamManager:
    """Manages FFmpeg streaming processes."""
    
    def __init__(self):
        """Initialize the stream manager with process handles storage."""
        # Keep references to open file handles so they are not GC'd
        self._process_handles: Dict[str, Dict[str, Any]] = {}
    
    def pid_file(self, stream_id: str) -> pathlib.Path:
        """Get the PID file path for a stream ID."""
        return config.PIDS_DIR / f"{stream_id}.pid"
    
    def log_file(self, stream_id: str) -> pathlib.Path:
        """Get the log file path for a stream ID."""
        return config.LOGS_DIR / f"{stream_id}.log"
    
    @staticmethod
    def is_running(pid: int) -> bool:
        """Check if a process with the given PID is running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    
    @staticmethod
    def _should_reencode(extra_args: Optional[list]) -> bool:
        """Determine if video should be re-encoded based on extra args."""
        if not extra_args:
            return False
        
        args_str = " ".join(map(str, extra_args)).lower()
        reencode_keywords = [
            "-filter_complex", "-vf", "drawtext", 
            "overlay", "format=", "scale", "crop"
        ]
        return any(keyword in args_str for keyword in reencode_keywords)
    
    def _build_ffmpeg_args(
        self, 
        hls: str, 
        rtmp: str, 
        extra_args: Optional[list] = None
    ) -> list:
        """Build FFmpeg command arguments."""
        # Validate FFmpeg binary exists
        if not pathlib.Path(config.FFMPEG_BIN).exists():
            raise FileNotFoundError(
                f"FFmpeg binary not found at {config.FFMPEG_BIN}"
            )
        
        # Base args: input HLS with -re (read input at native frame rate)
        args = [config.FFMPEG_BIN, "-re", "-i", hls]
        
        # Add extra args if provided
        if extra_args:
            args += list(map(str, extra_args))
        
        # Determine if re-encoding is needed
        if self._should_reencode(extra_args):
            args += [
                "-c:v", config.VIDEO_CODEC,
                "-preset", config.VIDEO_PRESET,
                "-tune", config.VIDEO_TUNE,
                "-b:v", config.VIDEO_BITRATE
            ]
        else:
            args += ["-c:v", "copy"]
        
        # Audio encoding (always encode audio for RTMP compatibility)
        args += [
            "-c:a", config.AUDIO_CODEC,
            "-ar", config.AUDIO_SAMPLE_RATE,
            "-b:a", config.AUDIO_BITRATE,
            "-f", "flv",
            rtmp
        ]
        
        return args
    
    def start_stream(
        self,
        hls: str,
        rtmp: str,
        stream_id: str = "stream",
        extra_args: Optional[list] = None
    ) -> int:
        """
        Start an FFmpeg streaming process.
        
        Args:
            hls: Input HLS stream URL
            rtmp: Output RTMP stream URL
            stream_id: Unique identifier for the stream
            extra_args: Optional list of extra FFmpeg arguments
        
        Returns:
            Process ID of the started stream
            
        Raises:
            RuntimeError: If stream is already running
            FileNotFoundError: If FFmpeg binary is not found
        """
        pid_file_path = self.pid_file(stream_id)
        
        # Check if stream is already running
        if pid_file_path.exists():
            try:
                pid = int(pid_file_path.read_text().strip())
                if self.is_running(pid):
                    raise RuntimeError(
                        f"Stream '{stream_id}' already running (PID: {pid})"
                    )
                else:
                    # Remove stale PID file
                    pid_file_path.unlink()
            except (ValueError, OSError):
                pid_file_path.unlink(missing_ok=True)
        
        # Build FFmpeg arguments
        args = self._build_ffmpeg_args(hls, rtmp, extra_args)
        
        # Open log file
        log_file_path = self.log_file(stream_id)
        log_file_handle = open(log_file_path, "ab")
        
        try:
            # Spawn process with new process group for clean termination
            process = subprocess.Popen(
                args,
                stdout=log_file_handle,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid
            )
            
            # Store PID and process info
            pid_file_path.write_text(str(process.pid))
            self._process_handles[stream_id] = {
                "proc": process,
                "logf": log_file_handle,
                "pid": process.pid,
                "args": args
            }
            
            return process.pid
            
        except Exception as e:
            # Clean up on failure
            log_file_handle.close()
            pid_file_path.unlink(missing_ok=True)
            raise
    
    def stop_stream(self, stream_id: str) -> int:
        """
        Stop a running stream process.
        
        Args:
            stream_id: Unique identifier for the stream
        
        Returns:
            Process ID of the stopped stream
            
        Raises:
            FileNotFoundError: If stream is not running
        """
        pid_file_path = self.pid_file(stream_id)
        
        if not pid_file_path.exists():
            raise FileNotFoundError(f"Stream '{stream_id}' is not running")
        
        try:
            pid = int(pid_file_path.read_text().strip())
            process_group = os.getpgid(pid)
            
            # Send SIGTERM to process group
            try:
                os.killpg(process_group, signal.SIGTERM)
                time.sleep(1.5)
                
                # Force kill if still running
                if self.is_running(pid):
                    os.killpg(process_group, signal.SIGKILL)
                    time.sleep(0.5)
            except ProcessLookupError:
                # Process already terminated
                pass
                
        finally:
            # Clean up PID file
            if pid_file_path.exists():
                pid_file_path.unlink()
            
            # Close log file and remove handle
            process_info = self._process_handles.pop(stream_id, None)
            if process_info:
                try:
                    log_handle = process_info.get("logf")
                    if log_handle:
                        log_handle.flush()
                        log_handle.close()
                except Exception:
                    pass
        
        return pid
    
    def get_stream_status(self, stream_id: str) -> Dict[str, Any]:
        """
        Get the status of a stream.
        
        Args:
            stream_id: Unique identifier for the stream
        
        Returns:
            Dictionary with stream status information
        """
        pid_file_path = self.pid_file(stream_id)
        
        if not pid_file_path.exists():
            return {"running": False, "id": stream_id}
        
        try:
            pid = int(pid_file_path.read_text().strip())
            running = self.is_running(pid)
            return {
                "running": running,
                "id": stream_id,
                "pid": pid
            }
        except (ValueError, OSError):
            return {"running": False, "id": stream_id}
    
    def list_streams(self) -> list:
        """
        List all streams with their status.
        
        Returns:
            List of dictionaries containing stream information
        """
        streams = []
        
        for pid_file_path in config.PIDS_DIR.glob("*.pid"):
            stream_id = pid_file_path.stem
            
            try:
                pid = int(pid_file_path.read_text().strip())
                running = self.is_running(pid)
            except (ValueError, OSError):
                pid = None
                running = False
            
            streams.append({
                "id": stream_id,
                "pid": pid,
                "running": running,
                "log": str(self.log_file(stream_id))
            })
        
        return streams
    
    def get_logs(self, stream_id: str, lines: int = 200) -> str:
        """
        Get the last N lines of a stream's log file.
        
        Args:
            stream_id: Unique identifier for the stream
            lines: Number of lines to retrieve
        
        Returns:
            Log content as string
            
        Raises:
            FileNotFoundError: If log file doesn't exist
        """
        log_file_path = self.log_file(stream_id)
        
        if not log_file_path.exists():
            raise FileNotFoundError(f"Log file not found for stream '{stream_id}'")
        
        # Efficient tail-like read
        try:
            with open(log_file_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                
                if file_size == 0:
                    return ""
                
                chunk_size = 1024
                data = bytearray()
                position = file_size
                
                while position > 0 and lines > 0:
                    read_size = min(chunk_size, position)
                    f.seek(position - read_size, os.SEEK_SET)
                    chunk = f.read(read_size)
                    data[:0] = chunk  # Prepend chunk
                    position -= read_size
                    
                    # Count newlines
                    newline_count = data.count(b"\n")
                    if newline_count >= lines:
                        break
                    
                    chunk_size = min(chunk_size * 2, 10 * 1024 * 1024)
                
                # Decode and return last N lines
                text = data.decode(errors="ignore")
                text_lines = text.splitlines()
                return "\n".join(text_lines[-lines:])
                
        except Exception:
            # Fallback: read entire file
            with open(log_file_path, "rb") as f:
                content = f.read().decode(errors="ignore")
                content_lines = content.splitlines()
                return "\n".join(content_lines[-lines:])
    
    def cleanup_stale_pids(self) -> list:
        """
        Remove stale PID files for processes that are no longer running.
        
        Returns:
            List of cleaned up stream IDs
        """
        cleaned = []
        
        for pid_file_path in config.PIDS_DIR.glob("*.pid"):
            stream_id = pid_file_path.stem
            
            try:
                pid = int(pid_file_path.read_text().strip())
                if not self.is_running(pid):
                    pid_file_path.unlink(missing_ok=True)
                    cleaned.append({
                        "id": stream_id,
                        "action": "removed_stale_pidfile",
                        "pid": pid
                    })
            except (ValueError, OSError):
                pid_file_path.unlink(missing_ok=True)
                cleaned.append({
                    "id": stream_id,
                    "action": "removed_invalid_pidfile"
                })
        
        return cleaned
    
    def kill_all_ffmpeg(self) -> list:
        """
        Kill all FFmpeg processes that were started by this application.
        Only kills processes that have PID files in our PIDS_DIR.
        
        WARNING: This does NOT kill all FFmpeg processes on the system,
        only those managed by this application.
        
        Returns:
            List of killed process IDs with their stream IDs
        """
        killed = []
        
        # Only kill processes that we have PID files for
        for pid_file_path in config.PIDS_DIR.glob("*.pid"):
            stream_id = pid_file_path.stem
            
            try:
                pid = int(pid_file_path.read_text().strip())
                
                # Verify it's actually running
                if not self.is_running(pid):
                    continue
                
                # Verify it's actually an FFmpeg process by checking command line
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmdline = f.read().decode(errors="ignore")
                        if "ffmpeg" not in cmdline.lower():
                            # Not an FFmpeg process, skip it
                            continue
                except (OSError, FileNotFoundError):
                    # Can't verify (might be on different OS), but proceed
                    pass
                
                # Kill the process using process group (same as stop_stream)
                try:
                    process_group = os.getpgid(pid)
                    os.killpg(process_group, signal.SIGTERM)
                    time.sleep(1.5)
                    
                    if self.is_running(pid):
                        os.killpg(process_group, signal.SIGKILL)
                        time.sleep(0.5)
                    
                    killed.append({
                        "id": stream_id,
                        "pid": pid
                    })
                    
                    # Clean up PID file
                    pid_file_path.unlink(missing_ok=True)
                    
                except (ProcessLookupError, OSError):
                    # Process already terminated
                    pid_file_path.unlink(missing_ok=True)
                    pass
                    
            except (ValueError, OSError, ProcessLookupError):
                # Invalid PID file, clean it up
                pid_file_path.unlink(missing_ok=True)
                pass
        
        return killed
    
    def stop_all_streams(self) -> list:
        """
        Stop all running streams.
        
        Returns:
            List of stopped stream information
        """
        stopped = []
        
        for pid_file_path in config.PIDS_DIR.glob("*.pid"):
            stream_id = pid_file_path.stem
            try:
                pid = self.stop_stream(stream_id)
                stopped.append({"id": stream_id, "pid": pid})
            except Exception as e:
                stopped.append({"id": stream_id, "error": str(e)})
        
        return stopped
