import argparse
import logging
import os
import threading
import webbrowser
from pathlib import Path

import truststore

from minman import __version__
from minman.app import app
from minman.storage import configure


def main():
    parser = argparse.ArgumentParser(prog="minman", description="MinMan - a tiny local API client.")
    # 3326 avoids Flask's busy default 5000 (macOS AirPlay, ASP.NET, Docker registry).
    parser.add_argument("--port", type=int, default=3326)
    parser.add_argument("--data-dir", default=os.environ.get("MINMAN_HOME") or Path.home() / ".minman")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--logs", action=argparse.BooleanOptionalAction, default=False, help="show request logs")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    data_dir = configure(args.data_dir)
    truststore.inject_into_ssl()
    url = f"http://127.0.0.1:{args.port}"
    print(f"MinMan running at {url}  (data: {data_dir})")
    if not args.no_browser:
        threading.Timer(1, webbrowser.open, [url]).start()
    logging.getLogger("werkzeug").disabled = not args.logs
    app.run(host="127.0.0.1", port=args.port, debug=False)
