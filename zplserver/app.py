import argparse
import asyncio
import logging

from zplserver.printer import DPI, Printer
from zplserver.server import run_server

DEFAULT_UI_PORT = 8080


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
        "--ui",
        help="Serve the web interface instead of logging to the terminal",
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
        help="Do not open a browser when the web interface starts",
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
    if args.verbose:
        logging.getLogger("zplserver").setLevel(logging.DEBUG)

    printer = Printer(
        label_width=args.width,
        label_height=args.height,
        dpi=args.dpi,
        port=args.port,
    )

    if args.ui:
        # Imported lazily: the web interface has dependencies the command line
        # deliberately does not.
        try:
            from zplserver.ui import run_ui
        except ImportError as exc:
            parser.error(
                f"--ui needs the ui extra ({exc}). "
                "Install it with: pip install 'zplserver[ui]'"
            )
            return
        asyncio.run(
            run_ui(
                printer,
                ui_port=args.ui_port,
                open_browser=not args.no_browser,
            )
        )
        return

    asyncio.run(run_server(printer))
