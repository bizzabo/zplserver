# zplserver

A virtual label printer for your desktop.

`zplserver` listens on a TCP port and behaves like a networked thermal label
printer that speaks ZPL. Point an application at it instead of at real hardware
and every label it tries to print is rendered to an image and opened on your
screen, while the ZPL stream itself is decoded and logged command by command.

## Why this exists

This tool was built to work with the Bizzabo Onsite Command iOS application,
which prints attendee badges at events. Testing that path normally means having
a physical label printer on the same network, which is rarely true while
developing. `zplserver` stands in for one, and is useful for three things:

- **Debugging network connectivity with printers.** Because it logs every
  connection and every command it receives, you can tell whether an app is
  reaching the printer at all, what it is sending, and where a handshake stops.
- **Running label tests without a printer.** You see the rendered badge on
  screen instead of waiting on hardware and consuming stock, which makes
  iterating on a label layout much faster.
- **Integration testing when printers are unavailable.** Bizzabo uses it
  internally for exactly that, so the printing path can be exercised without
  hardware in the loop.

Nothing about it is specific to that application, though. Any client that speaks
ZPL over a TCP socket will work.

## What it does

- Accepts connections on port `9100`, the convention for raw network printing.
- Renders each completed label format (`^XA` … `^XZ`) to an image and opens it
  in your default image viewer.
- Decodes the ZPL stream into named commands with their parameters, so you can
  see exactly what your application emitted.
- Answers the control commands (`! U1 getvar`, `! U1 setvar`, `! U1 do`) that
  applications use to interrogate a printer, retaining variables that get set.
- Handles many clients at once, and does not assume that one network read
  contains exactly one message, so labels split across packets or batched
  together in a single write are both handled correctly.

## Requirements

Python 3.12 or newer. No third-party runtime dependencies.

## Install

With Poetry:

```sh
poetry install
```

A Conda environment matching the development setup is also provided:

```sh
conda env create -f environment.yml
conda activate zplserver
```

## Usage

```sh
zplserver
```

Or without installing the entry point:

```sh
python -m zplserver
```

The server prints the address it is listening on. Configure your application to
print to that host and port, then print a label.

### Options

| Option | Default | Description |
| --- | --- | --- |
| `--width` | `4` | Label width in inches. |
| `--height` | `3` | Label height in inches, between 2 and 12. |
| `-p`, `--port` | `9100` | TCP port to listen on. |
| `-d`, `--dpi` | `300` | Print resolution, either `203` or `300`. |
| `-v`, `--verbose` | off | Log every decoded ZPL command, not just label boundaries. |

## How labels are rendered

`zplserver` does not rasterize ZPL itself. Rendering is delegated to
[Labelary](https://labelary.com/), a public web service that turns a label
format into an image. Each completed format is posted there over HTTPS, and the
PNG that comes back is written to a temporary file and opened.

This means **label content leaves your machine.** Labels printed through
`zplserver` should be test data. Do not point it at a production workload or
print labels containing personal or otherwise sensitive information.

## Network exposure

The server binds to all interfaces so that a phone or tablet elsewhere on your
network can reach it, which is the point. It performs no authentication and is
meant for a trusted local network. Do not expose it to the internet.

## Disclaimer

ZPL is a printer control language originally developed by Zebra Technologies
Corporation. This project is an independent, unofficial tool. It is not
affiliated with, authorized by, endorsed by, or sponsored by Zebra Technologies
Corporation, and it is neither a Zebra product nor a substitute for one. Any
trademarks referenced here are the property of their respective owners and are
used only to describe what this software is compatible with.

`zplserver` emulates a subset of the language for development and debugging
purposes. It is not a complete or certified implementation, and its output is an
approximation of what real hardware would produce.

## License

MIT
