import os
import sys
import time
import signal
import threading
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Working directory inside discord-combot where bot scripts expect to run
BASE_DIR = Path(__file__).resolve().parent
BOT_DIR = BASE_DIR / "discord-combot" if (BASE_DIR / "discord-combot").exists() else BASE_DIR

processes = []

# ==========================================
# HEALTHCHECK HTTP SERVER (For Free Cloud Hosts)
# ==========================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "online", "services": ["discord_bot", "telegram_bot"]}')

    def log_message(self, format, *args):
        # Silence HTTP access logs to keep console clean
        return

def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"[HEALTHCHECK] HTTP server listening on port {port} for cloud ping.")
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTHCHECK] Error starting health server: {e}")

# ==========================================
# PROCESS MANAGEMENT
# ==========================================
def signal_handler(sig, frame):
    print("\n[CLOUD MANAGER] Stopping all bot services...")
    for p in processes:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def start_services():
    print("=" * 60)
    print("[CLOUD MANAGER] Initializing Server Stats Bot Services")
    print(f"Working Directory: {BOT_DIR}")
    print("=" * 60)

    # Start healthcheck web server in background thread so free cloud platforms (Render, Koyeb) accept it
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # 1. Discord Bot
    if os.getenv("DISCORD_TOKEN"):
        print("[LAUNCH] Starting Discord Bot...")
        p_discord = subprocess.Popen(
            [sys.executable, "bot.py"],
            cwd=str(BOT_DIR)
        )
        processes.append(p_discord)
    else:
        print("[SKIP] DISCORD_TOKEN not set in environment.")

    # 2. Telegram Bot
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("[LAUNCH] Starting Telegram Bot...")
        p_telegram = subprocess.Popen(
            [sys.executable, "telegram_bot.py"],
            cwd=str(BOT_DIR)
        )
        processes.append(p_telegram)
    else:
        print("[SKIP] TELEGRAM_BOT_TOKEN not set in environment.")

    if not processes:
        print("[ERROR] Neither DISCORD_TOKEN nor TELEGRAM_BOT_TOKEN was found! Please configure your environment variables.")
        sys.exit(1)

    print("[SUCCESS] Bot services launched. Monitoring...")
    while True:
        for p in list(processes):
            poll = p.poll()
            if poll is not None:
                print(f"[WARNING] A service exited with code {poll}. Exiting container to trigger restart...")
                sys.exit(poll)
        time.sleep(2)

if __name__ == '__main__':
    start_services()
