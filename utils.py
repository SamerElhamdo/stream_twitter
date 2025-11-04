#!/usr/bin/env python3
"""Utility functions for stream server."""
from flask import request, abort
from typing import Optional, List
import config


def require_auth():
    """Require Bearer token authentication."""
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {config.WEBHOOK_TOKEN}"
    
    if auth_header != expected_token:
        abort(401, description="Unauthorized: Invalid or missing Bearer token")


def build_overlay_args(
    image_path: str,
    overlay_mode: Optional[str] = None,
    existing_args: Optional[List] = None
) -> List[str]:
    """
    Build FFmpeg overlay arguments from image path and mode.
    
    Args:
        image_path: Path to overlay image
        overlay_mode: Overlay mode (e.g., "full" for full screen overlay)
        existing_args: Existing extra args to merge with
    
    Returns:
        List of FFmpeg arguments
    """
    args = existing_args.copy() if existing_args else []
    
    # Add image input if not already present
    if "-i" not in args or image_path not in args:
        # Insert image input after the first -i (HLS input)
        insert_index = 0
        for i, arg in enumerate(args):
            if arg == "-i":
                insert_index = i + 2
                break
        args.insert(insert_index, image_path)
        args.insert(insert_index, "-i")
    
    # Add overlay filter if mode is "full" and no filter_complex exists
    if overlay_mode == "full":
        args_str = " ".join(args).lower()
        if "-filter_complex" not in args_str and "overlay" not in args_str:
            # Full screen overlay: overlay image centered on video
            # Using direct overlay without scaling first - if image matches video size it works perfectly
            # If sizes differ, we can use scale separately, but for now this is simplest
            filter_complex = (
                "[0:v][1:v]overlay=(W-w)/2:(H-h)/2:format=auto"
            )
            args.extend(["-filter_complex", filter_complex])
    
    return args


def validate_stream_request(body: dict) -> tuple:
    """
    Validate stream start request body.
    
    Args:
        body: Request JSON body
    
    Returns:
        Tuple of (hls, rtmp, stream_id, extra_args, error_message)
        If error_message is not None, validation failed
    """
    hls = body.get("hls", "").strip()
    rtmp = body.get("rtmp", "").strip()
    stream_id = body.get("id", "stream").strip()
    extra_args = body.get("extra_args")
    image = body.get("image", "").strip()
    overlay_mode = body.get("overlay_mode")
    
    if not hls:
        return None, None, None, None, "HLS URL is required"
    
    if not rtmp:
        return None, None, None, None, "RTMP URL is required"
    
    if not stream_id:
        stream_id = "stream"
    
    # Build extra_args if image is provided
    if image:
        extra_args = build_overlay_args(image, overlay_mode, extra_args)
    
    # Validate extra_args is a list if provided
    if extra_args is not None and not isinstance(extra_args, list):
        return None, None, None, None, "extra_args must be a list"
    
    return hls, rtmp, stream_id, extra_args, None
