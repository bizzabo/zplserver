import argparse
import asyncio
import logging

from zplserver.printer import DPI, Printer, run_server


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


def run():
    parser = argparse.ArgumentParser(description="Virtual ZPL label printer")
    parser.add_argument(
        "--width",
        help="Width of the label (inches)",
        default=4,
        type=int_range("width", 4, 4),
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
        "-v",
        "--verbose",
        help="Show all ZPL printer commands",
        action="store_true",
    )
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger("zplserver").setLevel(logging.DEBUG)

    printer = Printer(
        label_width=args.width,
        label_height=args.height,
        dpi=args.dpi,
        port=args.port,
    )
    asyncio.run(run_server(printer))
