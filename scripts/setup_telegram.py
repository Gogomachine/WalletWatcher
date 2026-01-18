#!/usr/bin/env python3
"""Setup script for Telegram channel parser authentication.

This script performs one-time authentication with Telegram to create a session file.
After running this once, the bot can reuse the session without requiring login again.

Usage:
    python3 scripts/setup_telegram.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from telethon import TelegramClient


async def main():
    """Setup Telegram session."""
    # Load environment variables
    load_dotenv()

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        print("❌ Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env file")
        print("\n📝 Get your credentials from https://my.telegram.org:")
        print("   1. Login with your phone number")
        print("   2. Go to 'API development tools'")
        print("   3. Create an app to get api_id and api_hash")
        print("   4. Add them to your .env file")
        return

    try:
        api_id = int(api_id)
    except ValueError:
        print("❌ Error: TELEGRAM_API_ID must be a number")
        return

    print("🔐 Telegram Authentication Setup")
    print("=" * 50)
    print("\nThis will authenticate with Telegram and create a session file.")
    print("You only need to do this once.\n")

    # Create session in project root
    session_file = "whale_parser"

    client = TelegramClient(session_file, api_id, api_hash)

    try:
        await client.start()

        # Test if we can access the channel
        print("\n✅ Authentication successful!")
        print(f"📁 Session file created: {session_file}.session")

        try:
            channel = await client.get_entity("solanawhaletracking")
            print(f"✅ Successfully connected to @solanawhaletracking")
            print(f"   Channel: {channel.title}")
            print(f"   Subscribers: {channel.participants_count if hasattr(channel, 'participants_count') else 'N/A'}")

            # Fetch a few recent messages to verify
            print("\n📨 Fetching recent messages...")
            count = 0
            async for message in client.iter_messages("solanawhaletracking", limit=5):
                if message.text:
                    count += 1
                    preview = message.text[:50].replace('\n', ' ')
                    print(f"   • {preview}...")

            print(f"\n✅ Successfully fetched {count} messages")

        except Exception as e:
            print(f"\n⚠️  Warning: Could not verify channel access: {e}")
            print("   Make sure you have access to @solanawhaletracking")

        print("\n" + "=" * 50)
        print("✅ Setup complete! You can now run the bot with:")
        print("   python3 main.py")
        print("\n💡 The session file will be reused automatically.")

    except Exception as e:
        print(f"\n❌ Error during authentication: {e}")
        print("\nPlease try again and make sure:")
        print("   • Your phone number is correct")
        print("   • You have access to your Telegram app to receive the code")
        print("   • Your API credentials are correct")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
