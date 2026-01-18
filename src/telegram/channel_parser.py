"""Telegram channel parser for whale tracking."""

import re
import random
from typing import Optional, List
from telethon import TelegramClient
from telethon.tl.types import Message


class WhaleChannelParser:
    """Parser for @solanawhaletracking Telegram channel."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = "whale_parser"):
        """Initialize Telegram client.

        Args:
            api_id: Telegram API ID from my.telegram.org
            api_hash: Telegram API hash from my.telegram.org
            session_name: Session file name for Telethon
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client = None
        self.channel_username = "solanawhaletracking"

    async def connect(self):
        """Connect to Telegram."""
        if self.client is None:
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.start()

    async def disconnect(self):
        """Disconnect from Telegram."""
        if self.client:
            await self.client.disconnect()

    def _extract_address_from_message(self, message_text: str) -> Optional[str]:
        """Extract Solana address from message text.

        Looks for "👨‍💼 To:" field and extracts the address after it.

        Args:
            message_text: Message text to parse

        Returns:
            Solana address or None
        """
        # Pattern to match "👨‍💼 To:" followed by a Solana address
        # Solana addresses are base58 encoded, 32-44 characters
        patterns = [
            r'👨‍💼\s*To:\s*([1-9A-HJ-NP-Za-km-z]{32,44})',
            r'To:\s*([1-9A-HJ-NP-Za-km-z]{32,44})',
            r'💼\s*To:\s*([1-9A-HJ-NP-Za-km-z]{32,44})',
        ]

        for pattern in patterns:
            match = re.search(pattern, message_text)
            if match:
                return match.group(1)

        return None

    async def get_recent_whale_addresses(self, limit: int = 100) -> List[str]:
        """Get recent whale addresses from the channel.

        Args:
            limit: Number of recent messages to parse

        Returns:
            List of unique Solana addresses
        """
        if not self.client:
            await self.connect()

        addresses = []

        try:
            # Fetch recent messages from the channel
            async for message in self.client.iter_messages(self.channel_username, limit=limit):
                if not isinstance(message, Message) or not message.text:
                    continue

                # Extract address from message
                address = self._extract_address_from_message(message.text)
                if address and address not in addresses:
                    addresses.append(address)

        except Exception as e:
            print(f"Error fetching messages from {self.channel_username}: {e}")

        return addresses

    async def get_random_whale_address(self) -> Optional[str]:
        """Get a random whale address from recent channel messages.

        Returns:
            Random Solana address or None if no addresses found
        """
        addresses = await self.get_recent_whale_addresses(limit=100)

        if not addresses:
            return None

        # Return random address
        selected = random.choice(addresses)
        print(f"Found {len(addresses)} whale addresses from channel, selected: {selected}")
        return selected
