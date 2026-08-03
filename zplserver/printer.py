import asyncio
import codecs
import logging
import re
import socket
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from enum import Enum

from zplserver import events, zpllib
from zplserver.render import RenderError, render_zpl

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
_logger = logging.getLogger("zplserver")

READ_SIZE = 1024
# A client that opens a format and never closes it, or that sends something we
# cannot make sense of, must not be able to grow the buffer without bound.
MAX_BUFFER = 8 * 1024 * 1024
FORMAT_START = "^XA"
FORMAT_END = "^XZ"
# "! U1 getvar ...", with or without the space after the bang.
CONTROL_PREFIX = re.compile(r"^!\s*(?:U1\s+)?")
SEPARATORS = "\r\n\t\x00 "


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class MessageKind(Enum):
    CONTROL = "control"  # a "! U1 ..." line, which expects a reply
    IMMEDIATE = "immediate"  # a "~" command sent outside a format
    FORMAT = "format"  # a complete "^XA ... ^XZ" label


@dataclass
class Message:
    kind: MessageKind
    payload: str


def _next_command(text: str, start: int = 0) -> int | None:
    """Index of the next command prefix at or after *start*, if there is one."""
    found = [
        index
        for index in (text.find("^", start), text.find("~", start))
        if index != -1
    ]
    return min(found) if found else None


def _take_line(text: str) -> tuple[str | None, int]:
    """Take one newline-terminated line, or None while it is still incomplete."""
    end = text.find("\n")
    if end == -1:
        return None, 0
    return text[:end].rstrip("\r"), end + 1


def _take_immediate(text: str) -> tuple[str | None, int]:
    """Take one "~" command, which ends at a newline or where the next begins."""
    line_end = text.find("\n")
    next_command = _next_command(text, start=1)
    ends = [end for end in (line_end, next_command) if end is not None and end != -1]
    if not ends:
        # Could still be receiving this command's parameters.
        return None, 0
    end = min(ends)
    if end == line_end:
        return text[:end].rstrip("\r"), end + 1
    return text[:end].rstrip(SEPARATORS), end


def split_stream(buffer: str) -> tuple[list[Message], str]:
    """Split *buffer* into the messages that are complete.

    Returns those messages together with the bytes that are left over. A
    partially received message stays in the remainder so the next read can
    finish it, which is what makes this safe to feed arbitrary chunks: nothing
    here assumes that a read boundary is also a message boundary.
    """
    messages: list[Message] = []
    position = 0
    while position < len(buffer):
        message_start = position
        while position < len(buffer) and buffer[position] in SEPARATORS:
            position += 1
        if position >= len(buffer):
            break

        rest = buffer[position:]
        if rest.startswith("!"):
            line, consumed = _take_line(rest)
            if line is None:
                break
            messages.append(Message(MessageKind.CONTROL, line))
            position += consumed
        elif rest.startswith(FORMAT_START):
            end = rest.find(FORMAT_END, len(FORMAT_START))
            if end == -1:
                break
            end += len(FORMAT_END)
            messages.append(Message(MessageKind.FORMAT, rest[:end]))
            position += end
        elif rest.startswith("~"):
            command, consumed = _take_immediate(rest)
            if command is None:
                break
            messages.append(Message(MessageKind.IMMEDIATE, command))
            position += consumed
        else:
            # Not the start of anything we recognise. Skip ahead to where the
            # next command begins so that stray bytes cannot desynchronise the
            # rest of the stream. Searching from one past the start matters: the
            # buffer may itself begin with a prefix character, either as the
            # start of a command we have not fully received ("^X") or as one we
            # do not treat as a message on its own.
            skip = _next_command(rest, start=1)
            if skip is None:
                break
            position += skip

        if position == message_start:
            # Nothing above could make progress. Wait for more data rather than
            # reconsidering the same bytes forever.
            break

    return messages, buffer[position:]


def flush_stream(buffer: str) -> tuple[list[Message], str]:
    """Split what is left when the client stops sending.

    A command with no trailing newline is only ambiguous while the connection
    is open, so at that point it can be treated as terminated.
    """
    return split_stream(buffer + "\n")


def normalise(chunk: str) -> str:
    """Map the single-byte forms of the command prefixes onto the ASCII ones."""
    return chunk.replace("\x1e", "^").replace("\x10", "~")


class DPI(Enum):
    DPI_203 = "203"
    DPI_300 = "300"

    def __str__(self) -> str:
        return self.value


class Printer:
    def __init__(
        self,
        label_width: int,
        label_height: int,
        dpi: DPI,
        port: int,
        bus: events.EventBus | None = None,
    ) -> None:
        self.label_width = label_width
        self.label_height = label_height
        self.dpi = dpi
        self.port = port
        self.bus = bus or events.EventBus()
        self.vars: dict[str, str] = {
            "appl.name": "V74.20.22Z",
            "device.host_identification": socket.gethostname(),
            "head.resolution.in_dpi": self.dpi.value,
            "ezpl.media_type": "gap/notch",
        }
        self.connection_number = 1

    @property
    def dpmm(self):
        return 8 if self.dpi is DPI.DPI_203 else 12

    def handle_command(self, message: str) -> str:
        body = CONTROL_PREFIX.sub("", message.strip(), count=1)
        parts = body.split(maxsplit=1)
        if not parts:
            return ""

        command = parts[0]
        remainder = parts[1] if len(parts) > 1 else ""
        if command in {"setvar", "do"}:
            arguments = remainder.split(maxsplit=1)
            attribute = arguments[0] if arguments else ""
            value = arguments[1] if len(arguments) > 1 else ""
        else:
            attribute, value = remainder, ""

        attribute, value = attribute.strip(' "'), value.strip(' "')
        if command == "getvar":
            return self.vars.get(attribute, "")
        if command == "setvar":
            self.vars[attribute] = value

        # unhandled command
        return value or ""

    async def handle_message(
        self, message: Message, writer: StreamWriter, connection: int
    ) -> None:
        if message.kind is MessageKind.CONTROL:
            response = self.handle_command(message.payload)
            writer.write(f"{response}\r\n".encode())
            await writer.drain()
            self.bus.publish(
                events.ControlHandled(connection, message.payload, response)
            )
            return

        described = [str(command) for command in zpllib.parse_zpl(message.payload)]

        if message.kind is MessageKind.IMMEDIATE:
            self.bus.publish(
                events.ImmediateReceived(connection, message.payload, described)
            )
            return

        self.bus.publish(events.LabelReceived(connection, message.payload, described))

        # Rendering talks to a web service over a blocking socket, so it has to
        # stay off the event loop or one client would stall every other.
        try:
            png = await asyncio.to_thread(
                render_zpl,
                message.payload,
                self.label_width,
                self.label_height,
                0,
                self.dpmm,
            )
        except RenderError as exc:
            self.bus.publish(events.RenderFailed(connection, message.payload, str(exc)))
        else:
            self.bus.publish(
                events.LabelRendered(connection, message.payload, png, described)
            )

    async def handle_connection(self, reader: StreamReader, writer: StreamWriter):
        connection = self.connection_number
        self.connection_number += 1
        peer = writer.get_extra_info("peername")
        self.bus.publish(
            events.ConnectionOpened(connection, f"{peer[0]}:{peer[1]}" if peer else "?")
        )

        # Decoding incrementally, because a multi-byte character can straddle
        # two reads.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        reason = ""
        try:
            while not reader.at_eof():
                chunk = await reader.read(READ_SIZE)
                buffer += normalise(decoder.decode(chunk, final=not chunk))
                messages, buffer = split_stream(buffer)
                for message in messages:
                    await self.handle_message(message, writer, connection)

                if len(buffer) > MAX_BUFFER:
                    self.bus.publish(
                        events.StreamDiscarded(
                            connection, len(buffer), "no complete command"
                        )
                    )
                    buffer = ""

            messages, buffer = flush_stream(buffer)
            for message in messages:
                await self.handle_message(message, writer, connection)
            if buffer.strip(SEPARATORS):
                self.bus.publish(
                    events.StreamDiscarded(connection, len(buffer), "incomplete")
                )
        except (ConnectionResetError, BrokenPipeError):
            reason = "reset by peer"
        except Exception as e:
            reason = f"error: {e}"
            _logger.error(f"Unhandled exception while handling tcp message: {e}")
            if _logger.level == logging.DEBUG:
                _logger.exception("traceback")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass
            self.bus.publish(events.ConnectionClosed(connection, reason))
