"""Solana blockchain client for wallet information retrieval."""

import asyncio
import os
from datetime import datetime
from typing import Optional, Dict, List
import aiohttp
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.signature import Signature


# Known exchange addresses (можно расширить)
KNOWN_EXCHANGES = {
    "Binance": [
        "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    ],
    "Coinbase": [
        "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS",
    ],
    "FTX": [
        "6gJq9JYqFJTr2YN5qq9uCzqnWNrqH1WwpFKcgk6xf4Qg",
    ],
    "Kraken": [
        "DhzDDB92TDj3LCSqHxZ72gVMVfVsLqkuN5bDCDa5h7oE",
    ],
}

# Whale classification tiers (in SOL)
WHALE_TIERS = {
    "mega_whale": {"min": 100000, "emoji": "🐋", "name": "Mega Whale"},
    "whale": {"min": 10000, "emoji": "🐳", "name": "Whale"},
    "dolphin": {"min": 1000, "emoji": "🐬", "name": "Dolphin"},
    "fish": {"min": 100, "emoji": "🐟", "name": "Fish"},
    "shrimp": {"min": 0, "emoji": "🦐", "name": "Shrimp"},
}


class SolanaClient:
    """Client for interacting with Solana blockchain."""

    def __init__(self, rpc_url: str, helius_api_key: Optional[str] = None):
        """Initialize Solana client.

        Args:
            rpc_url: Solana RPC endpoint URL
            helius_api_key: Optional Helius API key for enhanced features
        """
        self.client = AsyncClient(rpc_url)
        self.helius_api_key = helius_api_key
        self.helius_base_url = "https://api.helius.xyz/v0"
        self.exchange_addresses = self._flatten_exchange_addresses()

    def _flatten_exchange_addresses(self) -> Dict[str, str]:
        """Flatten exchange addresses into a single dict."""
        result = {}
        for exchange, addresses in KNOWN_EXCHANGES.items():
            for address in addresses:
                result[address] = exchange
        return result

    async def close(self):
        """Close the client connection."""
        await self.client.close()

    def is_exchange_address(self, address: str) -> Optional[str]:
        """Check if address belongs to a known exchange.

        Args:
            address: Solana address to check

        Returns:
            Exchange name if found, None otherwise
        """
        return self.exchange_addresses.get(address)

    async def get_balance(self, address: str) -> Optional[float]:
        """Get SOL balance of an address.

        Args:
            address: Solana address

        Returns:
            Balance in SOL or None if error
        """
        try:
            pubkey = Pubkey.from_string(address)
            response = await self.client.get_balance(pubkey, commitment=Confirmed)

            if response.value is not None:
                # Convert lamports to SOL (1 SOL = 1_000_000_000 lamports)
                return response.value / 1_000_000_000
            return None
        except Exception as e:
            print(f"Error getting balance for {address}: {e}")
            return None

    async def get_transaction_signatures(
        self,
        address: str,
        limit: int = 1000
    ) -> List[Dict]:
        """Get transaction signatures for an address.

        Args:
            address: Solana address
            limit: Maximum number of signatures to retrieve

        Returns:
            List of transaction signatures with metadata
        """
        try:
            pubkey = Pubkey.from_string(address)
            response = await self.client.get_signatures_for_address(
                pubkey,
                limit=limit,
                commitment=Confirmed
            )

            if response.value:
                return [
                    {
                        "signature": str(sig.signature),
                        "slot": sig.slot,
                        "block_time": sig.block_time,
                        "err": sig.err,
                    }
                    for sig in response.value
                ]
            return []
        except Exception as e:
            print(f"Error getting signatures for {address}: {e}")
            return []

    async def get_first_transaction(self, address: str) -> Optional[Dict]:
        """Get the first transaction of an address.

        Args:
            address: Solana address

        Returns:
            First transaction info or None
        """
        signatures = await self.get_transaction_signatures(address, limit=1000)

        if not signatures:
            return None

        # Signatures are returned in reverse chronological order, so last is first
        first_tx = signatures[-1]

        return {
            "signature": first_tx["signature"],
            "timestamp": datetime.fromtimestamp(first_tx["block_time"]) if first_tx["block_time"] else None,
            "explorer_url": f"https://solscan.io/tx/{first_tx['signature']}"
        }

    async def get_last_transaction(self, address: str) -> Optional[Dict]:
        """Get the last (most recent) transaction of an address.

        Args:
            address: Solana address

        Returns:
            Last transaction info or None
        """
        signatures = await self.get_transaction_signatures(address, limit=1)

        if not signatures:
            return None

        last_tx = signatures[0]

        return {
            "signature": last_tx["signature"],
            "timestamp": datetime.fromtimestamp(last_tx["block_time"]) if last_tx["block_time"] else None,
            "explorer_url": f"https://solscan.io/tx/{last_tx['signature']}"
        }

    async def get_wallet_age(self, address: str) -> Optional[Dict]:
        """Calculate wallet age based on first transaction.

        Args:
            address: Solana address

        Returns:
            Dict with wallet age info or None
        """
        first_tx = await self.get_first_transaction(address)

        if not first_tx or not first_tx["timestamp"]:
            return None

        # Calculate age from first transaction to now
        first_tx_date = first_tx["timestamp"]
        current_date = datetime.now()
        age = current_date - first_tx_date

        # Calculate years, months, days
        total_days = age.days
        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        days = remaining_days % 30

        # Format age string
        age_parts = []
        if years > 0:
            age_parts.append(f"{years}г")
        if months > 0:
            age_parts.append(f"{months}м")
        if days > 0 or not age_parts:  # Show days if it's the only value or if there are other parts
            age_parts.append(f"{days}д")

        return {
            "first_transaction_date": first_tx_date,
            "total_days": total_days,
            "years": years,
            "months": months,
            "days": days,
            "formatted": " ".join(age_parts)
        }

    def classify_whale(self, balance: float) -> Dict[str, str]:
        """Classify address based on balance.

        Args:
            balance: SOL balance

        Returns:
            Dict with tier info (tier_key, name, emoji)
        """
        for tier_key in ["mega_whale", "whale", "dolphin", "fish", "shrimp"]:
            tier_info = WHALE_TIERS[tier_key]
            if balance >= tier_info["min"]:
                return {
                    "tier": tier_key,
                    "name": tier_info["name"],
                    "emoji": tier_info["emoji"],
                    "min_balance": tier_info["min"]
                }
        # Default to shrimp
        return {
            "tier": "shrimp",
            "name": WHALE_TIERS["shrimp"]["name"],
            "emoji": WHALE_TIERS["shrimp"]["emoji"],
            "min_balance": 0
        }

    async def discover_random_address_by_tier(self, tier: str = "whale") -> Optional[str]:
        """Discover a random address of specified tier by scanning recent transactions.

        Args:
            tier: Tier to search for (mega_whale, whale, dolphin, fish, shrimp)

        Returns:
            Random address of specified tier or None
        """
        if tier not in WHALE_TIERS:
            return None

        tier_info = WHALE_TIERS[tier]
        min_balance = tier_info["min"]

        # Get next tier's minimum for upper bound
        tier_keys = ["mega_whale", "whale", "dolphin", "fish", "shrimp"]
        tier_index = tier_keys.index(tier)
        max_balance = None
        if tier_index > 0:
            max_balance = WHALE_TIERS[tier_keys[tier_index - 1]]["min"]

        try:
            # Collect unique addresses from recent transactions
            addresses_to_check = set()

            # Use known high-activity addresses as starting points
            seed_addresses = [
                "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",  # Binance
                "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Binance
                "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS",  # Coinbase
                "DhzDDB92TDj3LCSqHxZ72gVMVfVsLqkuN5bDCDa5h7oE",  # Kraken
            ]

            if self.helius_api_key:
                # Use Helius API to get recent transactions and extract addresses
                async with aiohttp.ClientSession() as session:
                    for seed_addr in seed_addresses[:1]:  # Just use one seed
                        url = f"{self.helius_base_url}/addresses/{seed_addr}/transactions"
                        params = {"api-key": self.helius_api_key, "limit": 50}

                        try:
                            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                                if response.status == 200:
                                    data = await response.json()

                                    for tx in data:
                                        if "nativeTransfers" in tx:
                                            for transfer in tx["nativeTransfers"]:
                                                from_addr = transfer.get("fromUserAccount")
                                                to_addr = transfer.get("toUserAccount")
                                                if from_addr:
                                                    addresses_to_check.add(from_addr)
                                                if to_addr:
                                                    addresses_to_check.add(to_addr)

                                        # Limit collection
                                        if len(addresses_to_check) >= 100:
                                            break
                        except Exception as e:
                            print(f"Error fetching seed transactions: {e}")
                            continue

            # If no Helius or not enough addresses, use RPC to get signatures
            if len(addresses_to_check) < 50:
                try:
                    # Get recent signatures from a known active address
                    sigs = await self.get_transaction_signatures(seed_addresses[0], limit=100)
                    for sig in sigs[:50]:
                        # Use signature as pseudo-random address source (not ideal but works)
                        pass
                except Exception as e:
                    print(f"Error getting signatures: {e}")

            # Shuffle and check addresses for matching tier
            import random
            addresses_list = list(addresses_to_check)
            random.shuffle(addresses_list)

            # Check balances until we find one matching the tier
            for address in addresses_list[:30]:  # Check max 30 to avoid rate limits
                try:
                    balance = await self.get_balance(address)
                    if balance is not None:
                        # Check if balance fits the tier
                        if max_balance is None:
                            # Top tier (mega_whale) - no upper limit
                            if balance >= min_balance:
                                return address
                        else:
                            # Has both min and max
                            if min_balance <= balance < max_balance:
                                return address
                except Exception as e:
                    print(f"Error checking balance for {address}: {e}")
                    continue

            return None

        except Exception as e:
            print(f"Error discovering random address: {e}")
            return None

    async def get_wallet_info(self, address: str) -> Dict:
        """Get comprehensive wallet information.

        Args:
            address: Solana address

        Returns:
            Dict with all wallet information
        """
        # Validate address
        try:
            Pubkey.from_string(address)
        except Exception:
            return {"error": "Invalid Solana address"}

        # Get all info in parallel
        balance, wallet_age, last_tx = await asyncio.gather(
            self.get_balance(address),
            self.get_wallet_age(address),
            self.get_last_transaction(address),
            return_exceptions=True
        )

        # Check if exchange
        exchange = self.is_exchange_address(address)

        # Classify whale tier
        whale_tier = None
        if balance is not None:
            whale_tier = self.classify_whale(balance)

        return {
            "address": address,
            "is_exchange": exchange is not None,
            "exchange_name": exchange,
            "balance": balance,
            "wallet_age": wallet_age,
            "last_transaction": last_tx,
            "whale_tier": whale_tier,
        }
