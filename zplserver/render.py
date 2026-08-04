"""Turning ZPL into an image, and showing one.

These are deliberately separate. Rendering produces bytes and is what every
front end needs; opening a viewer is a side effect only the terminal wants.
"""

import asyncio
import logging
import os
import platform
import subprocess
import tempfile

import aiohttp

_logger = logging.getLogger("zplserver")

RENDER_URL = "https://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{width}x{height}/{index}/"
# Without a bound, an unresponsive service holds a label forever.
RENDER_TIMEOUT_SECONDS = 30
# The service answers 415 for application/octet-stream, which is what aiohttp
# would otherwise send for a raw body.
RENDER_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


class RenderError(Exception):
    """A label could not be rendered."""


async def render_zpl(
    zpl: str, width: float = 4, height: float = 3, index: int = 0, dpmm: int = 12
) -> bytes:
    """Render *zpl* to PNG bytes, raising RenderError if that is not possible."""
    url = RENDER_URL.format(dpmm=dpmm, width=width, height=height, index=index)
    timeout = aiohttp.ClientTimeout(total=RENDER_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, data=zpl.encode(), headers=RENDER_HEADERS
            ) as response:
                body = await response.read()
                if response.status != 200:
                    detail = body.decode(errors="replace").strip()
                    raise RenderError(f"HTTP {response.status}: {detail}")
                return body
    except asyncio.TimeoutError as exc:
        raise RenderError(
            f"the rendering service did not answer within {RENDER_TIMEOUT_SECONDS}s"
        ) from exc
    except aiohttp.ClientError as exc:
        raise RenderError(f"could not reach the rendering service: {exc}") from exc


def write_temporary_png(png: bytes) -> str:
    with tempfile.NamedTemporaryFile(
        prefix="zplserver-label-", suffix=".png", delete=False
    ) as file:
        file.write(png)
        return file.name


def open_image(png: bytes) -> None:
    """Write *png* somewhere durable and open it in the platform image viewer.

    Blocking, and it spawns a process: call it from a thread.
    """
    path = write_temporary_png(png)
    system = platform.system()

    if system == "Windows":
        # "start" is a shell builtin rather than an executable, so it cannot be
        # spawned directly.
        startfile = getattr(os, "startfile", None)
        if startfile is not None:
            startfile(path)
            return

    opener = {"Darwin": "open", "Linux": "xdg-open"}.get(system)
    if opener is None:
        _logger.error("Cannot open label image, unsupported platform %s", system)
        _logger.info("Label image written to %s", path)
        return

    try:
        subprocess.run([opener, path], check=False)
    except OSError as exc:
        _logger.error("Could not open %s: %s", path, exc)
