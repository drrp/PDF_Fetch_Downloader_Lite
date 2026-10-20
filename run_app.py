"""Start the library app and open it in your browser.

Double-click run_windows.bat to use this - you do not need to run it by hand.
It starts the server, waits until it is actually accepting connections, then
opens your browser at the right address.
"""

import os
import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PREFERRED_PORT = 8000


def free_port(preferred=PREFERRED_PORT, tries=10):
    """Return the first port from `preferred` upwards that nothing is using."""
    for port in range(preferred, preferred + tries):
        with socket.socket() as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    return preferred


def open_browser_when_ready(port):
    """Wait for the server to answer, then open the browser - not before."""
    for _ in range(160):  # up to about 40 seconds
        try:
            socket.create_connection((HOST, port), timeout=0.5).close()
        except OSError:
            time.sleep(0.25)
            continue
        webbrowser.open(f"http://{HOST}:{port}")
        return


def main():
    # A packaged copy of the app listens on this machine only, so there is nothing to
    # keep out - open it without sign-in rather than showing a login page that cannot
    # work without Google credentials.
    if getattr(sys, "frozen", False) and not os.getenv("GOOGLE_CLIENT_ID"):
        os.environ.setdefault("DEV_NO_LOGIN", "true")

    try:
        import uvicorn
        from backend.main import app
    except ModuleNotFoundError as e:
        print()
        print(f"  Missing package: {e.name}")
        print("  Install the requirements first, then try again:")
        print()
        print("      python -m pip install -r requirements.txt")
        print()
        return 1

    port = free_port()
    if port != PREFERRED_PORT:
        print(f"  Port {PREFERRED_PORT} is busy, using {port} instead.")

    print()
    print("  Library app is starting...")
    print(f"  It will open at  http://{HOST}:{port}")
    print()
    print("  Keep this window open while you use the app.")
    print("  Close this window (or press Ctrl+C) to stop it.")
    print()

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
