#!/usr/bin/env python3
"""Run Cinema Studio server (production-ready entry point)."""
from studio.app import create_app

if __name__ == "__main__":
    app = create_app()
    print("=" * 60)
    print("  CINEMA STUDIO — Starting")
    print("  Server: http://127.0.0.1:8770")
    print("  Health: http://127.0.0.1:8770/api/cinema/health")
    print("=" * 60)
    app.run(host="127.0.0.1", port=8770, debug=False, threaded=True)
