"""Turning ZPL into an image, and showing one.

These are deliberately separate. Rendering produces bytes and is what every
front end needs; opening a viewer is a side effect only the command line wants.
"""

import logging
import os
import platform
import subprocess
import tempfile
import urllib.error
import urllib.request

_logger = logging.getLogger("zplserver")

RENDER_URL = "https://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{width}x{height}/{index}/"


class RenderError(Exception):
    """A label could not be rendered."""


def render_zpl(
    zpl: str, width: float = 4, height: float = 3, index: int = 0, dpmm: int = 12
) -> bytes:
    """Render *zpl* to PNG bytes, raising RenderError if that is not possible.

    Blocking: run it in a thread when called from the event loop.
    """
    url = RENDER_URL.format(dpmm=dpmm, width=width, height=height, index=index)
    try:
        with urllib.request.urlopen(url, data=zpl.encode()) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()
        raise RenderError(f"HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise RenderError(f"could not reach the rendering service: {exc}") from exc


def write_temporary_png(png: bytes) -> str:
    with tempfile.NamedTemporaryFile(
        prefix="zplserver-label-", suffix=".png", delete=False
    ) as file:
        file.write(png)
        return file.name


def open_image(png: bytes) -> None:
    """Write *png* somewhere durable and open it in the platform image viewer."""
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
