import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# Working directory inside discord-combot where bot scripts expect to run
BASE_DIR = Path(__file__).resolve().parent
BOT_DIR = BASE_DIR / "discord-combot" if (BASE_DIR / "discord-combot").exists() else BASE_DIR

processes = []

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

    # 1. Discord Bot (if DISCORD_TOKEN is set)
    if os.getenv("DISCORD_TOKEN"):
        print("[LAUNCH] Starting Discord Bot...")
        p_discord = subprocess.Popen(
            [sys.executable, "bot.py"],
            cwd=str(BOT_DIR)
        )
        processes.append(p_discord)
    else:
        print("[SKIP] DISCORD_TOKEN not set in environment.")

    # 2. Telegram Bot (if TELEGRAM_BOT_TOKEN is set)
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
