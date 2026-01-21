"""Optimized Solscan screenshot utility with browser reuse."""

import asyncio
import os
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright
import time


class OptimizedScreenshotService:
    """Optimized screenshot service that reuses browser instances."""

    def __init__(self):
        """Initialize screenshot service."""
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.screenshot_dir = Path("screenshots")
        self.screenshot_dir.mkdir(exist_ok=True)
        self._lock = asyncio.Lock()  # Prevent race conditions
        self._initialized = False

    async def start(self):
        """Start Playwright and browser instance (call once at bot startup)."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            print("🌐 Starting Playwright browser...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',  # Use /tmp instead of /dev/shm
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',  # Important for stability
                ]
            )
            self._initialized = True
            print("✅ Playwright browser started and ready")

    async def stop(self):
        """Stop browser and Playwright (call at bot shutdown)."""
        if self.browser:
            await self.browser.close()
            self.browser = None

        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

        self._initialized = False
        print("✅ Playwright browser stopped")

    async def take_overview_screenshot(self, address: str) -> Optional[str]:
        """Take screenshot of Solscan Overview section (optimized).

        Args:
            address: Solana wallet address

        Returns:
            Path to screenshot file or None if failed
        """
        if not self._initialized:
            await self.start()

        try:
            # Create isolated browser context (lightweight)
            async with self._lock:
                context: BrowserContext = await self.browser.new_context(
                    viewport={'width': 600, 'height': 1000}
                )

            page = await context.new_page()

            try:
                # Navigate to Solscan account page
                url = f"https://solscan.io/account/{address}"
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait for Overview section to load
                await page.wait_for_selector('text=Total Value', timeout=15000)

                # Give it a moment for all data to populate
                await asyncio.sleep(2)

                # Find the Overview element
                total_value_locator = page.locator('text=Total Value').first

                # Get the parent div that contains the whole Overview card
                parent_levels = [2, 3, 4, 5, 6]
                overview_box = None

                for level in parent_levels:
                    try:
                        parent_locator = total_value_locator.locator(f'xpath=ancestor::div[{level}]')
                        box = await parent_locator.bounding_box()
                        if box and box['height'] > 150 and box['height'] < 600:
                            overview_box = box
                            break
                    except:
                        continue

                # Save screenshot
                screenshot_path = self.screenshot_dir / f"{address[:8]}_{int(time.time())}.png"

                if overview_box:
                    padding = 15
                    await page.screenshot(
                        path=str(screenshot_path),
                        clip={
                            'x': max(0, overview_box['x'] - padding),
                            'y': max(0, overview_box['y'] - padding),
                            'width': overview_box['width'] + (padding * 2),
                            'height': overview_box['height'] + (padding * 2)
                        }
                    )
                else:
                    # Fallback
                    for level in [4, 5, 3, 6]:
                        try:
                            parent_locator = total_value_locator.locator(f'xpath=ancestor::div[{level}]')
                            box = await parent_locator.bounding_box()
                            if box:
                                await page.screenshot(
                                    path=str(screenshot_path),
                                    clip={
                                        'x': max(0, box['x'] - 15),
                                        'y': max(0, box['y'] - 15),
                                        'width': box['width'] + 30,
                                        'height': box['height'] + 30
                                    }
                                )
                                break
                        except:
                            continue

                return str(screenshot_path)

            finally:
                # Always close page and context
                await page.close()
                await context.close()

        except Exception as e:
            print(f"❌ Error taking screenshot: {e}")
            return None

    async def take_transaction_screenshot(self, signature: str) -> Optional[str]:
        """Take screenshot of transaction details (optimized).

        Args:
            signature: Transaction signature

        Returns:
            Path to screenshot file or None if failed
        """
        if not self._initialized:
            await self.start()

        try:
            # Create isolated browser context
            async with self._lock:
                context: BrowserContext = await self.browser.new_context(
                    viewport={'width': 800, 'height': 1200}
                )

            page = await context.new_page()

            try:
                # Navigate to Solscan transaction page
                url = f"https://solscan.io/tx/{signature}"
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait for transaction details to load
                await page.wait_for_selector('text=Legacy Mode', timeout=15000)

                # Give it a moment
                await asyncio.sleep(2)

                # Find the transaction instruction block
                try:
                    instruction_locator = page.locator('text=Legacy Mode').first
                except:
                    try:
                        instruction_locator = page.locator('text=TransferChecked').first
                    except:
                        instruction_locator = page.locator('text=Transfer').first

                # Find container
                parent_levels = [3, 4, 5, 6, 7, 8]
                instruction_box = None

                for level in parent_levels:
                    try:
                        parent_locator = instruction_locator.locator(f'xpath=ancestor::div[{level}]')
                        box = await parent_locator.bounding_box()
                        if box and box['height'] > 100 and box['height'] < 800 and box['width'] > 300:
                            instruction_box = box
                            break
                    except:
                        continue

                # Save screenshot
                screenshot_path = self.screenshot_dir / f"tx_{signature[:16]}_{int(time.time())}.png"

                if instruction_box:
                    padding = 15
                    await page.screenshot(
                        path=str(screenshot_path),
                        clip={
                            'x': max(0, instruction_box['x'] - padding),
                            'y': max(0, instruction_box['y'] - padding),
                            'width': instruction_box['width'] + (padding * 2),
                            'height': instruction_box['height'] + (padding * 2)
                        }
                    )
                else:
                    await page.screenshot(path=str(screenshot_path), full_page=False)

                return str(screenshot_path)

            finally:
                await page.close()
                await context.close()

        except Exception as e:
            print(f"❌ Error taking transaction screenshot: {e}")
            return None

    async def cleanup_old_screenshots(self, max_age_seconds: int = 3600):
        """Remove old screenshot files.

        Args:
            max_age_seconds: Maximum age in seconds (default 1 hour)
        """
        current_time = time.time()

        for screenshot_file in self.screenshot_dir.glob("*.png"):
            file_age = current_time - screenshot_file.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    screenshot_file.unlink()
                except:
                    pass

    async def health_check(self) -> bool:
        """Check if browser is healthy.

        Returns:
            True if healthy
        """
        try:
            if not self._initialized or not self.browser:
                return False

            # Try to create a simple page
            context = await self.browser.new_context()
            page = await context.new_page()
            await page.goto("about:blank")
            await page.close()
            await context.close()
            return True

        except Exception as e:
            print(f"❌ Browser health check failed: {e}")
            return False


# Global instance
_screenshot_service: Optional[OptimizedScreenshotService] = None


async def get_screenshot_service() -> OptimizedScreenshotService:
    """Get or create screenshot service instance.

    Returns:
        OptimizedScreenshotService instance
    """
    global _screenshot_service
    if _screenshot_service is None:
        _screenshot_service = OptimizedScreenshotService()
    return _screenshot_service


async def take_solscan_screenshot(address: str) -> Optional[str]:
    """Take screenshot of Solscan overview for address.

    Args:
        address: Solana wallet address

    Returns:
        Path to screenshot file or None if failed
    """
    service = await get_screenshot_service()
    return await service.take_overview_screenshot(address)


async def take_transaction_screenshot(signature: str) -> Optional[str]:
    """Take screenshot of transaction details from Solscan.

    Args:
        signature: Transaction signature

    Returns:
        Path to screenshot file or None if failed
    """
    service = await get_screenshot_service()
    return await service.take_transaction_screenshot(signature)
