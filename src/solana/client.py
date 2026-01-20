"""Solana blockchain client for wallet information retrieval."""

import asyncio
import os
import random
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
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
        self.whale_addresses_file = Path("data/whale_addresses.txt")

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

    async def get_token_accounts(self, address: str) -> List[Dict]:
        """Get all SPL token accounts for an address using Helius API.

        Args:
            address: Solana address

        Returns:
            List of token accounts with balances and metadata
        """
        if not self.helius_api_key:
            print("⚠️  Helius API key not configured. Token balances unavailable.")
            return []

        return await self._get_tokens_helius(address)

    async def _get_tokens_helius(self, address: str) -> List[Dict]:
        """Get tokens using Helius RPC API.

        Args:
            address: Solana address

        Returns:
            List of tokens with metadata
        """
        try:
            # Use Helius RPC endpoint with getTokenAccountsByOwner
            url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

            # Standard Solana RPC method to get token accounts
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    address,
                    {
                        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                    },
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status != 200:
                        print(f"❌ Helius RPC error: {response.status}")
                        response_text = await response.text()
                        print(f"Response: {response_text[:200]}")
                        return []

                    data = await response.json()

                    # Check for RPC errors
                    if 'error' in data:
                        print(f"❌ RPC Error: {data['error']}")
                        return []

                    tokens = []

                    # Parse token accounts
                    accounts = data.get('result', {}).get('value', [])
                    print(f"📊 Helius returned {len(accounts)} token accounts")

                    for account in accounts:
                        try:
                            parsed = account.get('account', {}).get('data', {}).get('parsed', {})
                            info = parsed.get('info', {})
                            token_amount = info.get('tokenAmount', {})

                            ui_amount = token_amount.get('uiAmount')
                            decimals = token_amount.get('decimals', 0)
                            mint = info.get('mint')

                            if ui_amount and float(ui_amount) > 0 and mint:
                                tokens.append({
                                    'mint': mint,
                                    'amount': float(ui_amount),
                                    'decimals': decimals,
                                    'symbol': None,  # Will be fetched separately if needed
                                    'name': None
                                })
                        except Exception as e:
                            print(f"⚠️  Error parsing token account: {e}")
                            continue

                    print(f"✅ Helius RPC: Found {len(tokens)} tokens with balance > 0")

                    # If we found tokens, try to enrich with metadata
                    if tokens:
                        tokens = await self._enrich_token_metadata(tokens)

                    return tokens

        except Exception as e:
            print(f"❌ Error getting tokens from Helius RPC: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _enrich_token_metadata(self, tokens: List[Dict]) -> List[Dict]:
        """Enrich tokens with metadata from Helius.

        Args:
            tokens: List of tokens with mint addresses

        Returns:
            List of tokens with metadata
        """
        try:
            # Get metadata for multiple tokens at once
            mint_addresses = [token['mint'] for token in tokens[:20]]  # Limit to first 20

            url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

            payload = {
                "jsonrpc": "2.0",
                "id": "metadata-batch",
                "method": "getAsset",
                "params": {
                    "id": mint_addresses[0] if mint_addresses else ""
                }
            }

            # For now, just return tokens as-is without metadata
            # Metadata enrichment can be added later if needed
            return tokens

        except Exception as e:
            print(f"⚠️  Could not enrich metadata: {e}")
            return tokens

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
            "explorer_url": f"https://solscan.io/tx/{last_tx['signature']}",
            "block_time": last_tx["block_time"]
        }

    async def get_transaction_details(self, signature: str) -> Optional[Dict]:
        """Get detailed transaction information including SOL amount transferred.

        Args:
            signature: Transaction signature

        Returns:
            Dict with transaction details or None if error
        """
        try:
            sig = Signature.from_string(signature)
            response = await self.client.get_transaction(
                sig,
                encoding="jsonParsed",
                max_supported_transaction_version=0,
                commitment=Confirmed
            )

            if not response.value:
                return None

            tx = response.value

            # Extract SOL transfer amount from pre and post balances
            sol_amount = None
            if hasattr(tx, 'meta') and tx.meta:
                pre_balances = tx.meta.pre_balances
                post_balances = tx.meta.post_balances

                # Find the largest balance change (excluding fee account)
                max_change = 0
                if len(pre_balances) == len(post_balances):
                    for i in range(len(pre_balances)):
                        balance_change = abs(post_balances[i] - pre_balances[i])
                        if balance_change > max_change:
                            max_change = balance_change

                    # Convert lamports to SOL
                    if max_change > 0:
                        sol_amount = max_change / 1_000_000_000

                # If no amount found, try to extract from fee (for small transactions)
                if sol_amount is None or sol_amount < 0.000001:
                    if hasattr(tx.meta, 'fee') and tx.meta.fee:
                        # At least show the transaction fee
                        sol_amount = tx.meta.fee / 1_000_000_000

            return {
                "signature": signature,
                "sol_amount": sol_amount,
                "slot": tx.slot if hasattr(tx, 'slot') else None,
                "block_time": tx.block_time if hasattr(tx, 'block_time') else None
            }

        except Exception as e:
            print(f"Error getting transaction details for {signature}: {e}")
            import traceback
            traceback.print_exc()
            return None

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

    async def discover_whale_address(self, min_balance_usd: float = 100000) -> Optional[str]:
        """Get random address from the whale addresses list.

        Reads addresses from data/whale_addresses.txt and returns a random one.
        Not all addresses are guaranteed to be whales.

        Args:
            min_balance_usd: Minimum balance in USD (not used, kept for compatibility)

        Returns:
            Random address from the list or None if file not found
        """
        try:
            if not self.whale_addresses_file.exists():
                print(f"❌ Whale addresses file not found: {self.whale_addresses_file}")
                return None

            # Read addresses from file
            addresses = []
            with open(self.whale_addresses_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        addresses.append(line)

            if not addresses:
                print(f"⚠️  No addresses found in {self.whale_addresses_file}")
                return None

            # Return random address
            selected = random.choice(addresses)
            print(f"✅ Selected random address from {len(addresses)} available: {selected}")
            return selected

        except Exception as e:
            print(f"❌ Error reading whale addresses: {e}")
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
        balance, wallet_age, last_tx, tokens = await asyncio.gather(
            self.get_balance(address),
            self.get_wallet_age(address),
            self.get_last_transaction(address),
            self.get_token_accounts(address),
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
            "tokens": tokens if isinstance(tokens, list) else [],
            "wallet_age": wallet_age,
            "last_transaction": last_tx,
            "whale_tier": whale_tier,
        }
