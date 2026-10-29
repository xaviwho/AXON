"""Headless Chromium screen-recorder, designed to run inside the official
Playwright Python Docker image.

Records the AXON Console at $DASHBOARD_URL for $DURATION_S seconds and
saves a WebM to $OUTPUT_FILE. The host orchestrator triggers the
scenario while this recorder is running.

Why a separate file from record_demos.py: that script depends on `uv`
and the project's own deps to fire scenarios; this one is intentionally
zero-deps-beyond-playwright so it runs cleanly inside the upstream
Playwright image.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

from playwright.async_api import async_playwright

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:5173")
DURATION_S = float(os.environ.get("DURATION_S", "60"))
OUTPUT_FILE = Path(os.environ.get("OUTPUT_FILE", "/recordings/dashboard.webm"))
WIDTH = int(os.environ.get("WIDTH", "1600"))
HEIGHT = int(os.environ.get("HEIGHT", "900"))


async def main() -> int:
    tmp = Path("/tmp/pw-record")
    tmp.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(tmp),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = await context.new_page()
        try:
            await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=20_000)
        except Exception as exc:    # noqa: BLE001
            print(f"could not load {DASHBOARD_URL}: {exc}", file=sys.stderr)
            return 2
        print(f"recording {DASHBOARD_URL} for {DURATION_S}s -> {OUTPUT_FILE}", flush=True)
        await page.wait_for_timeout(int(DURATION_S * 1000))

        video = page.video
        await context.close()
        await browser.close()
        if video is None:
            print("no video produced", file=sys.stderr)
            return 3
        src = await video.path()
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if OUTPUT_FILE.exists():
            OUTPUT_FILE.unlink()
        shutil.move(src, OUTPUT_FILE)
        size_kb = OUTPUT_FILE.stat().st_size / 1024
        print(f"wrote {OUTPUT_FILE} ({size_kb:.0f} KB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
