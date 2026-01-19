"""Solscan screenshot utility using Playwright."""

import asyncio
import os
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page


class SolscanScreenshot:
    """Handle taking screenshots from Solscan."""

    def __init__(self):
        """Initialize screenshot utility."""
        self.browser: Optional[Browser] = None
        self.screenshot_dir = Path("screenshots")
        self.screenshot_dir.mkdir(exist_ok=True)

    async def init_browser(self):
        """Initialize browser instance."""
        if not self.browser:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )

    async def close_browser(self):
        """Close browser instance."""
        if self.browser:
            await self.browser.close()
            self.browser = None

    async def take_overview_screenshot(self, address: str) -> Optional[str]:
        """Take screenshot of Solscan Overview section for an address.

        Args:
            address: Solana wallet address

        Returns:
            Path to screenshot file or None if failed
        """
        try:
            await self.init_browser()

            # Create new page
            page = await self.browser.new_page(
                viewport={'width': 600, 'height': 800}
            )

            # Navigate to Solscan account page
            url = f"https://solscan.io/account/{address}"
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for Overview section to load
            await page.wait_for_selector('text=Total Value', timeout=15000)

            # Give it a moment for all data to populate
            await asyncio.sleep(3)

            # Find the Overview card by looking for the parent container
            # that contains both "Overview" and "Total Value"
            # Use XPath for more reliable element finding
            overview_element = page.locator('xpath=//div[contains(., "Overview") and contains(., "Total Value")][1]')

            # Check if element exists, if not try alternative selectors
            try:
                await overview_element.wait_for(timeout=5000)
            except:
                # Fallback: Find by bounding box - look for container with specific height/structure
                try:
                    overview_element = page.locator('text=Total Value').locator('..').locator('..')
                except:
                    # Last resort: just capture the area containing Total Value
                    overview_element = page.locator('text=Total Value').locator('..')

            # Save screenshot
            screenshot_path = self.screenshot_dir / f"{address[:8]}.png"

            # Take screenshot of the overview element
            await overview_element.screenshot(path=str(screenshot_path), timeout=10000)

            await page.close()

            return str(screenshot_path)

        except Exception as e:
            print(f"❌ Error taking screenshot: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def cleanup_old_screenshots(self, max_age_seconds: int = 3600):
        """Remove old screenshot files.

        Args:
            max_age_seconds: Maximum age of screenshots to keep (default 1 hour)
        """
        import time
        current_time = time.time()

        for screenshot_file in self.screenshot_dir.glob("*.png"):
            file_age = current_time - screenshot_file.stat().st_mtime
            if file_age > max_age_seconds:
                screenshot_file.unlink()
                print(f"🗑️ Deleted old screenshot: {screenshot_file.name}")


# Global instance
_screenshot_manager: Optional[SolscanScreenshot] = None


async def get_screenshot_manager() -> SolscanScreenshot:
    """Get or create screenshot manager instance.

    Returns:
        SolscanScreenshot instance
    """
    global _screenshot_manager
    if _screenshot_manager is None:
        _screenshot_manager = SolscanScreenshot()
    return _screenshot_manager


async def take_solscan_screenshot(address: str) -> Optional[str]:
    """Take screenshot of Solscan overview for address.

    Args:
        address: Solana wallet address

    Returns:
        Path to screenshot file or None if failed
    """
    manager = await get_screenshot_manager()
    return await manager.take_overview_screenshot(address)
