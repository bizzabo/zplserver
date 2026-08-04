import argparse
import asyncio
import logging

from bizzabo_zpl.printer import DPI, Printer
from bizzabo_zpl.server import run_server

DEFAULT_UI_PORT = 8082


def int_range(param_name: str, min_value: int, max_value: int):
    def parser(arg: str):
        try:
            value = int(arg)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{param_name} must be a valid number")
        if value < min_value or value > max_value:
            raise argparse.ArgumentTypeError(
                f"must be within [{min_value}, {max_value}]"
            )
        return value

    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Virtual ZPL label printer")
    parser.add_argument(
        "--width",
        help="Width of the label (inches)",
        default=4,
        type=int_range("width", 1, 15),
    )
    parser.add_argument(
        "--height",
        help="Height of the label (inches)",
        default=3,
        type=int_range("height", 2, 12),
    )
    parser.add_argument(
        "-p",
        "--port",
        help="port for the server to run",
        default=9100,
        type=int_range("port", 1, 65535),
    )
    parser.add_argument(
        "-d",
        "--dpi",
        help="DPI resolution (default: %(default)s)",
        default=DPI.DPI_300,
        type=DPI,
        choices=list(DPI),
    )
    parser.add_argument(
        "--headless",
        help="Log to the terminal instead of serving the web interface",
        action="store_true",
    )
    parser.add_argument(
        "--no-open-labels",
        help="With --headless, do not open rendered labels in the image viewer",
        action="store_true",
    )
    parser.add_argument(
        "--ui-port",
        help=f"port for the web interface (default: {DEFAULT_UI_PORT})",
        default=DEFAULT_UI_PORT,
        type=int_range("ui-port", 1, 65535),
    )
    parser.add_argument(
        "--no-browser",
        help="Serve the web interface without opening a browser",
        action="store_true",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Show all ZPL printer commands",
        action="store_true",
    )
    return parser


def run():
    parser = build_parser()
    args = parser.parse_args()

    # Silently ignoring a flag wastes more of someone's time than refusing it.
    if args.no_open_labels and not args.headless:
        parser.error("--no-open-labels only applies with --headless")

    if args.verbose:
        logging.getLogger("bizzabo-zpl").setLevel(logging.DEBUG)

    printer = Printer(
        label_width=args.width,
        label_height=args.height,
        dpi=args.dpi,
        port=args.port,
    )

    if args.headless:
        asyncio.run(run_server(printer, open_labels=not args.no_open_labels))
        return

    # Imported here rather than at the top so the headless path does not pay for
    # loading the web stack.
    from bizzabo_zpl.ui import run_ui

    asyncio.run(
        run_ui(printer, ui_port=args.ui_port, open_browser=not args.no_browser)
    )
