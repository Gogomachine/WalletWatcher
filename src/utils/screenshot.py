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

            # Create new page with fixed viewport
            page = await self.browser.new_page(
                viewport={'width': 600, 'height': 1000}
            )

            # Navigate to Solscan account page
            url = f"https://solscan.io/account/{address}"
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for Overview section to load
            await page.wait_for_selector('text=Total Value', timeout=15000)

            # Give it a moment for all data to populate
            await asyncio.sleep(3)

            # Find the Overview element and get its bounding box
            # Try to find the parent container of "Total Value"
            total_value_locator = page.locator('text=Total Value').first

            # Get the parent div that contains the whole Overview card
            # Navigate up the DOM tree to find the card container
            parent_levels = [2, 3, 4, 5, 6]  # Try different levels
            overview_box = None

            for level in parent_levels:
                try:
                    parent_locator = total_value_locator.locator(f'xpath=ancestor::div[{level}]')
                    box = await parent_locator.bounding_box()
                    # Accept any reasonable sized container (removed upper limit for wallets without tokens)
                    if box and box['height'] > 150 and box['height'] < 600:
                        # Found a reasonable sized container
                        overview_box = box
                        print(f"✓ Found Overview at level {level}: {box}")
                        break
                except:
                    continue

            # Save screenshot
            screenshot_path = self.screenshot_dir / f"{address[:8]}.png"

            if overview_box:
                # Take screenshot of the specific area with 15px padding on all sides (expand outward)
                padding = 15
                await page.screenshot(
                    path=str(screenshot_path),
                    clip={
                        'x': max(0, overview_box['x'] - padding),  # Don't go negative
                        'y': max(0, overview_box['y'] - padding),
                        'width': overview_box['width'] + (padding * 2),
                        'height': overview_box['height'] + (padding * 2)
                    }
                )
            else:
                # Fallback: try to find any parent with the Overview content
                print("⚠ Could not find bounding box with size constraints, trying fallback")
                # Try level 4 first (most common), then others
                for level in [4, 5, 3, 6]:
                    try:
                        parent_locator = total_value_locator.locator(f'xpath=ancestor::div[{level}]')
                        box = await parent_locator.bounding_box()
                        if box:
                            print(f"✓ Fallback: using level {level} with box: {box}")
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
                    except Exception as e:
                        print(f"Fallback level {level} failed: {e}")
                        continue

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
