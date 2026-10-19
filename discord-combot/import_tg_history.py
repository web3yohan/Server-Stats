import os
import re
import json
import sqlite3
import datetime
from pathlib import Path

# ==========================================
# 1. SETUP REGEX & DATABASE
# ==========================================
X_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)

def extract_text_from_tg(text_obj):
    """Telegram export text can be a string OR a list of mixed strings/entity dicts."""
    if isinstance(text_obj, str):
        return text_obj
    elif isinstance(text_obj, list):
        parts = []
        for item in text_obj:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        return "".join(parts)
    return ""

def import_telegram_history(json_filepath="result.json"):
    path = Path(json_filepath)
    if not path.exists():
        # Check parent folder or common locations if not in cwd
        alt_path = Path("..") / json_filepath
        if alt_path.exists():
            path = alt_path
        else:
            print(f"❌ File '{json_filepath}' not found!")
            print(f"👉 Please place your exported 'result.json' file into this folder:")
            print(f"   {Path('.').resolve()}")
            return

    print(f"📂 Loading '{path}' ({path.stat().st_size / (1024*1024):.2f} MB)...")
    start_time = datetime.datetime.now()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    total_raw = len(messages)
    print(f"🔍 Found {total_raw:,} total messages. Parsing & classifying...")

    conn = sqlite3.connect("activity.db")
    c = conn.cursor()
    c.execute("PRAGMA journal_mode = WAL;")
    c.execute("PRAGMA synchronous = NORMAL;")

    # Ensure tables exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            user_id TEXT,
            username TEXT,
            message_id TEXT PRIMARY KEY,
            timestamp DATETIME,
            is_x_post BOOLEAN,
            is_gif BOOLEAN,
            is_sticker BOOLEAN,
            is_pure_text BOOLEAN,
            link_count INTEGER,
            avatar_url TEXT
        )
    ''')

    rows_to_insert = []
    text_lengths = []
    skipped_service = 0

    for msg in messages:
        # Ignore service notifications (user joins, pin events, call logs)
        if msg.get("type") != "message":
            skipped_service += 1
            continue

        raw_from_id = str(msg.get("from_id", ""))
        if not raw_from_id:
            skipped_service += 1
            continue

        # Format user_id: 'user12345' -> 'tg_12345'
        clean_user_id = "tg_" + raw_from_id.replace("user", "").replace("channel", "")
        username = msg.get("from") or "Telegram User"
        msg_id = f"tg_{msg.get('id')}"
        iso_date = msg.get("date")  # e.g. "2024-05-10T14:22:10"

        content = extract_text_from_tg(msg.get("text", "")).strip()

        # Classifications
        media_type = msg.get("media_type")
        is_x_post = bool(X_PATTERN.search(content))
        link_count = len(URL_PATTERN.findall(content))
        
        is_sticker = (media_type == "sticker")
        is_gif = (media_type == "animation") or ("tenor.com" in content.lower()) or ("giphy.com" in content.lower())
        is_media = bool(msg.get("photo") or msg.get("file"))

        # Skip pure stickers/gifs/photos with no text
        if (is_sticker or is_gif or is_media) and not content:
            is_pure_text = False
        else:
            is_pure_text = not is_gif and not is_sticker and not is_media and not is_x_post and (link_count == 0)

        if content:
            text_lengths.append(len(content))

        rows_to_insert.append((
            clean_user_id,
            username,
            msg_id,
            iso_date,
            is_x_post,
            is_gif,
            is_sticker,
            is_pure_text,
            link_count,
            None
        ))

    # Batch insert in chunks of 10,000 for maximum speed
    print(f"⚡ Batch inserting {len(rows_to_insert):,} messages into activity.db...")
    batch_size = 10000
    for i in range(0, len(rows_to_insert), batch_size):
        chunk = rows_to_insert[i:i + batch_size]
        c.executemany('''
            INSERT OR IGNORE INTO messages 
            (user_id, username, message_id, timestamp, is_x_post, is_gif, is_sticker, is_pure_text, link_count, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', chunk)
        conn.commit()

    conn.close()

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    print("\n" + "="*50)
    print("🎉 IMPORT COMPLETE!")
    print(f"⏱  Time taken: {elapsed:.2f} seconds")
    print(f"📊 Valid messages imported: {len(rows_to_insert):,}")
    print(f"🚫 Service messages skipped: {skipped_service:,}")

    # ==========================================
    # QUICK PATTERN ANALYSIS (Tier 2 Insights)
    # ==========================================
    if text_lengths:
        text_lengths.sort()
        avg_len = sum(text_lengths) / len(text_lengths)
        median_len = text_lengths[len(text_lengths) // 2]
        under_5_chars = sum(1 for x in text_lengths if x <= 5)
        
        print("\n📈 30-DAY CHAT PATTERN ANALYSIS:")
        print(f"   • Average message length: {avg_len:.1f} characters")
        print(f"   • Median message length:  {median_len} characters")
        print(f"   • Short/Filler messages (<= 5 chars like 'gm', 'ok'): {under_5_chars:,} ({under_5_chars/len(text_lengths)*100:.1f}%)")
        print("💡 Recommendation for Tier 2: Require messages to be at least 6-8 characters to count towards contest points!")
    print("="*50 + "\n")

if __name__ == '__main__':
    # You can pass a custom path if your file is named differently
    import sys
    file_arg = sys.argv[1] if len(sys.argv) > 1 else "result.json"
    import_telegram_history(file_arg)
