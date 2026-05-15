"""Headless-Chromium screen recordings of the three demo scenarios.

This script is the auto-generated counterpart to the manual recording
recipe in RECORDING_GUIDE.md. It drives Playwright + Chromium to capture
the live AXON dashboard while each scenario fires; the output is three
WebM files in demos/recordings/.

Prerequisites:
  - The full stack must be up (`make demo SCENARIO=fire_ignition` brings
    it up; or run `infra/scripts/up.sh`-style manually per the runbook).
  - The Vite dev server must be serving the dashboard at
    http://localhost:5173.

Each scenario gets its own Playwright `BrowserContext` with
`record_video_dir` set, which captures every frame of the page until
the context closes. The orchestrator script for that scenario runs in
parallel; when it finishes we wait a few seconds for the dashboard to
settle, close the context, and the .webm is flushed to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDINGS_DIR = Path(__file__).parent
DASHBOARD_URL = "http://localhost:5173"
INCIDENT_URL_TMPL = "http://localhost:5173/incidents/{trigger_id}"

# A handful of seconds of pre-roll (lets the dashboard fully paint, shows
# the steady-state service grid) + post-roll (audit rows finish landing).
PRE_ROLL_S = 3.0
POST_ROLL_S = 6.0


async def _run_scenario_subprocess(name: str) -> int:
    """Run `uv run python -m demos.scenarios.<name>` from the repo root."""
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "python", "-m", f"demos.scenarios.{name}",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        logger.error("scenario {} failed (rc={}): {}",
                     name, proc.returncode, stdout.decode()[-2000:])
    return proc.returncode or 0


async def _record_one(
    pw_browser, scenario: str, viewport: tuple[int, int], out_name: str,
) -> Path | None:
    """Run one scenario with the dashboard recorded under a fresh context."""
    width, height = viewport
    tmp_dir = RECORDINGS_DIR / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    context = await pw_browser.new_context(
        viewport={"width": width, "height": height},
        record_video_dir=str(tmp_dir),
        record_video_size={"width": width, "height": height},
    )
    page = await context.new_page()
    await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=20_000)
    logger.info("record: dashboard loaded for {}", scenario)
    # Pre-roll — let the steady-state dashboard render before the trigger fires.
    await page.wait_for_timeout(int(PRE_ROLL_S * 1000))

    started = time.monotonic()
    rc = await _run_scenario_subprocess(scenario)
    elapsed = time.monotonic() - started
    logger.info("record: scenario {} finished in {:.1f}s (rc={})", scenario, elapsed, rc)

    # Post-roll — keep recording while the last audit rows land + the
    # slice chart settles back from preempt.
    await page.wait_for_timeout(int(POST_ROLL_S * 1000))

    # Closing the context flushes the video; the file landing on disk
    # gets a Playwright-generated UUID name, which we then rename.
    video = page.video
    await context.close()
    if video is None:
        logger.error("record: no video object for {}", scenario)
        return None
    src = await video.path()
    out_path = RECORDINGS_DIR / out_name
    if out_path.exists():
        out_path.unlink()
    shutil.move(src, out_path)
    logger.info("record: wrote {}", out_path)
    return out_path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="*",
                        default=["medical_emergency", "fire_ignition", "wifi_vs_5g"])
    parser.add_argument("--width",  type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for scen in args.scenarios:
                path = await _record_one(
                    browser, scen,
                    viewport=(args.width, args.height),
                    out_name=f"{scen}.webm",
                )
                if path is not None:
                    written.append(path)
                # gap so fusion's 10s cooldown is clear by the next scenario
                await asyncio.sleep(12.0)
        finally:
            await browser.close()

    # Tidy up the playwright tmp dir if empty
    tmp_dir = RECORDINGS_DIR / "_tmp"
    if tmp_dir.exists() and not any(tmp_dir.iterdir()):
        tmp_dir.rmdir()

    print("\nRecordings:")
    for p in written:
        size_kb = p.stat().st_size / 1024
        print(f"  {p}  ({size_kb:.0f} KB)")
    if len(written) != len(args.scenarios):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
