"""Address monitoring system for real-time transaction notifications."""

import asyncio
from datetime import datetime
from typing import Callable
from ..solana.client import SolanaClient
from ..database.db import Database
from ..utils.screenshot import take_transaction_screenshot


class AddressMonitor:
    """Monitor Solana addresses for new transactions."""

    def __init__(
        self,
        solana_client: SolanaClient,
        database: Database,
        notification_callback: Callable,
        interval: int = 10
    ):
        """Initialize address monitor.

        Args:
            solana_client: Solana blockchain client
            database: Database instance
            notification_callback: Async function to call when new transaction detected
            interval: Monitoring interval in seconds
        """
        self.solana_client = solana_client
        self.database = database
        self.notification_callback = notification_callback
        self.interval = interval
        self.running = False
        self._task = None

    async def start(self):
        """Start monitoring addresses."""
        if self.running:
            return

        self.running = True
        self._task = asyncio.create_task(self._monitor_loop())
        print(f"Address monitor started (interval: {self.interval}s)")

    async def stop(self):
        """Stop monitoring addresses."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("Address monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                await self._check_all_addresses()
            except Exception as e:
                print(f"Error in monitor loop: {e}")

            # Wait for next iteration
            await asyncio.sleep(self.interval)

    async def _check_all_addresses(self):
        """Check all tracked addresses for new transactions."""
        # Get all tracked addresses
        tracked = await self.database.get_all_tracked_addresses()

        if not tracked:
            return

        # Check each address
        for record in tracked:
            try:
                await self._check_address(record)
            except Exception as e:
                print(f"Error checking address {record['address']}: {e}")

    async def _check_address(self, record: dict):
        """Check a single address for new transactions.

        Args:
            record: Database record with address info
        """
        address = record['address']
        last_known_sig = record['last_signature']

        # Get latest transaction
        last_tx = await self.solana_client.get_last_transaction(address)

        if not last_tx:
            return

        current_sig = last_tx['signature']

        # If this is first check, just store signature
        if not last_known_sig:
            await self.database.update_last_signature(record['id'], current_sig)
            return

        # Check if there's a new transaction
        if current_sig != last_known_sig:
            # Get all new transactions
            signatures = await self.solana_client.get_transaction_signatures(
                address,
                limit=100
            )

            # Find new transactions (those after last_known_sig)
            new_transactions = []
            for sig in signatures:
                if sig['signature'] == last_known_sig:
                    break
                new_transactions.append(sig)

            # Update last known signature
            await self.database.update_last_signature(record['id'], current_sig)

            # Send notifications for new transactions (in reverse order - oldest first)
            for tx in reversed(new_transactions):
                await self._send_notification(record, tx)

    async def _send_notification(self, record: dict, transaction: dict):
        """Send notification about new transaction.

        Args:
            record: Database record with address info
            transaction: Transaction data
        """
        user_id = record['user_id']
        address = record['address']
        nickname = record['nickname']
        group_name = record.get('group_name')

        # Check if user has notifications enabled
        settings = await self.database.get_user_settings(user_id)
        if not settings.get('notifications_enabled', 1):
            return

        # Check if bot is active for this user
        if not settings.get('bot_active', 1):
            print(f"⏸️  Bot is paused for user {user_id}, skipping notification")
            return

        # Check if address has notifications enabled
        if not record.get('notifications_enabled', 1):
            return

        # Format transaction time
        tx_time = datetime.fromtimestamp(transaction['block_time']) if transaction['block_time'] else None
        time_str = tx_time.strftime('%d.%m.%Y %H:%M:%S') if tx_time else 'Неизвестно'

        # Create explorer URLs
        address_url = f"https://solscan.io/account/{address}"
        tx_url = f"https://solscan.io/tx/{transaction['signature']}"

        # Get transaction details for SOL amount
        tx_details = await self.solana_client.get_transaction_details(transaction['signature'])

        # Format SOL amount with better logging
        amount_str = ""
        if tx_details:
            print(f"📊 Transaction details for {transaction['signature'][:16]}: {tx_details}")
            sol_amount = tx_details.get('sol_amount')
            if sol_amount is not None and sol_amount > 0:
                amount_str = f"💰 <b>Сумма:</b> {sol_amount:.4f} SOL\n"
                print(f"✅ SOL amount found: {sol_amount:.4f}")
            else:
                print(f"⚠️  SOL amount not found or zero")
        else:
            print(f"❌ Could not get transaction details")

        # Format wallet name with hyperlink to Solscan
        wallet_display = nickname if nickname else f"{address[:8]}...{address[-6:]}"

        # Add group info if available
        group_str = ""
        if group_name:
            group_str = f"📁 <b>Группа:</b> {group_name}\n"

        # Format message
        message = (
            f"🔔 <b>Новая транзакция!</b>\n\n"
            f"📍 <b>Кошелёк:</b> {wallet_display}\n"
            f"{group_str}"
            f"🔗 <a href='{address_url}'>{address}</a>\n\n"
            f"{amount_str}"
            f"📅 <b>Дата и время:</b> {time_str}\n"
            f"🔍 <a href='{tx_url}'>Посмотреть транзакцию</a>"
        )

        # Take transaction screenshot
        screenshot_path = None
        try:
            print(f"📸 Taking screenshot of transaction {transaction['signature'][:16]}...")
            screenshot_path = await take_transaction_screenshot(transaction['signature'])
            if screenshot_path:
                print(f"✅ Screenshot saved: {screenshot_path}")
            else:
                print(f"⚠️  Screenshot failed, sending text only")
        except Exception as e:
            print(f"❌ Error taking transaction screenshot: {e}")

        # Call notification callback with screenshot
        try:
            await self.notification_callback(user_id, message, screenshot_path)
        except Exception as e:
            print(f"Error sending notification to user {user_id}: {e}")

    async def check_address_now(self, user_id: int, address: str) -> bool:
        """Manually check an address for new transactions.

        Args:
            user_id: Telegram user ID
            address: Solana address to check

        Returns:
            True if check was successful
        """
        try:
            tracked = await self.database.get_all_tracked_addresses()
            record = next(
                (r for r in tracked if r['user_id'] == user_id and r['address'] == address),
                None
            )

            if not record:
                return False

            await self._check_address(record)
            return True
        except Exception as e:
            print(f"Error in manual check: {e}")
            return False
