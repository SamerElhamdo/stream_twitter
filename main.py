#!/usr/bin/env python3
"""Main entry point for the stream server application."""
from flask import Flask

from routes import api
import config

# Create Flask application
app = Flask(__name__)

# Register API routes
app.register_blueprint(api)


@app.errorhandler(401)
def unauthorized(error):
    """Handle 401 Unauthorized errors."""
    return {"error": "Unauthorized", "message": str(error.description)}, 401


@app.errorhandler(404)
def not_found(error):
    """Handle 404 Not Found errors."""
    return {"error": "Not Found", "message": str(error.description)}, 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 Internal Server errors."""
    return {"error": "Internal Server Error", "message": str(error)}, 500


if __name__ == "__main__":
    print(f"Starting Stream Server on port {config.APP_PORT}")
    print(f"Base directory: {config.BASE_DIR}")
    print(f"FFmpeg binary: {config.FFMPEG_BIN}")
    
    app.run(
        host="0.0.0.0",
        port=config.APP_PORT,
        debug=False
    )
