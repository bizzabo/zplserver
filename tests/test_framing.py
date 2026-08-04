"""split_stream: dividing the byte stream into messages.

Its contract is the thing to hold onto: never emit a partial message, always
leave a partial one in the returned tail, and always make forward progress. The
last of those is not a nicety — a version that could consume nothing spun forever
and hung the server on a single byte.
"""

import pytest

from zplserver.printer import (
    MessageKind,
    flush_stream,
    normalise,
    split_stream,
)

LABEL = "^XA^FO50,50^FDHi^FS^XZ"
OTHER = "^XA^FO10,10^FDBye^FS^XZ"
CONTROL = '! U1 getvar "appl.name"'


def kinds(messages):
    return [(m.kind, m.payload) for m in messages]


def feed(chunks):
    """Push *chunks* through the splitter in order, as reads would arrive."""
    buffer = ""
    collected = []
    for chunk in chunks:
        buffer += chunk
        messages, buffer = split_stream(buffer)
        collected += messages
    return collected, buffer


class TestWholeMessages:
    def test_single_label(self):
        assert kinds(split_stream(LABEL)[0]) == [(MessageKind.FORMAT, LABEL)]

    def test_single_label_consumes_everything(self):
        assert split_stream(LABEL)[1] == ""

    def test_two_labels_in_one_buffer(self):
        """One write containing two labels used to render only the first."""
        messages, tail = split_stream(LABEL + OTHER)
        assert kinds(messages) == [
            (MessageKind.FORMAT, LABEL),
            (MessageKind.FORMAT, OTHER),
        ]
        assert tail == ""

    def test_label_not_at_the_end_of_the_buffer(self):
        """A label whose ^XZ was not the last thing read never rendered."""
        messages, tail = split_stream(LABEL + "\r\n")
        assert kinds(messages) == [(MessageKind.FORMAT, LABEL)]
        assert tail == ""

    def test_control_line(self):
        messages, tail = split_stream(CONTROL + "\r\n")
        assert kinds(messages) == [(MessageKind.CONTROL, CONTROL)]
        assert tail == ""

    def test_control_and_label_in_one_buffer(self):
        """A control line sharing a read with a label was misclassified."""
        messages, _ = split_stream(CONTROL + "\r\n" + LABEL)
        assert kinds(messages) == [
            (MessageKind.CONTROL, CONTROL),
            (MessageKind.FORMAT, LABEL),
        ]

    def test_immediate_command(self):
        assert kinds(split_stream("~HS\r\n")[0]) == [(MessageKind.IMMEDIATE, "~HS")]

    def test_immediate_followed_by_a_label(self):
        messages, _ = split_stream("~HS" + LABEL)
        assert kinds(messages) == [
            (MessageKind.IMMEDIATE, "~HS"),
            (MessageKind.FORMAT, LABEL),
        ]


class TestPartialMessages:
    def test_incomplete_label_is_held(self):
        messages, tail = split_stream("^XA^FDstuck")
        assert messages == []
        assert tail == "^XA^FDstuck"

    def test_incomplete_control_line_is_held(self):
        messages, tail = split_stream(CONTROL)
        assert messages == []
        assert tail == CONTROL

    def test_flush_completes_an_unterminated_control_line(self):
        messages, _ = flush_stream(CONTROL)
        assert kinds(messages) == [(MessageKind.CONTROL, CONTROL)]

    def test_flush_does_not_invent_a_label(self):
        messages, tail = flush_stream("^XA^FDnever finished")
        assert messages == []
        assert tail.strip()

    @pytest.mark.parametrize("cut", range(1, len(LABEL)))
    def test_reassembled_at_every_split_point(self, cut):
        collected, tail = feed([LABEL[:cut], LABEL[cut:]])
        assert kinds(collected) == [(MessageKind.FORMAT, LABEL)]
        assert tail == ""

    def test_byte_at_a_time(self):
        collected, tail = feed(list(LABEL + OTHER))
        assert kinds(collected) == [
            (MessageKind.FORMAT, LABEL),
            (MessageKind.FORMAT, OTHER),
        ]
        assert tail == ""

    def test_control_split_across_reads(self):
        collected, _ = feed([CONTROL[:8], CONTROL[8:], "\r\n"])
        assert kinds(collected) == [(MessageKind.CONTROL, CONTROL)]

    def test_label_larger_than_one_read(self):
        big = "^XA^FX" + ("p" * 5000) + "^FS^FDx^FS^XZ"
        collected, tail = feed([big[i : i + 1024] for i in range(0, len(big), 1024)])
        assert kinds(collected) == [(MessageKind.FORMAT, big)]
        assert tail == ""


class TestForwardProgress:
    """Every one of these hangs the server if the progress guarantee breaks."""

    def test_bare_caret_does_not_spin(self):
        """_next_command from index 0 returns 0 here, consuming nothing."""
        assert split_stream("^") == ([], "^")

    def test_bare_tilde_does_not_spin(self):
        assert split_stream("~") == ([], "~")

    def test_partial_format_start_is_held(self):
        assert split_stream("^X") == ([], "^X")

    def test_caret_command_that_is_not_a_format_start(self):
        assert split_stream("^FO50,50") == ([], "^FO50,50")

    def test_resynchronises_onto_a_later_label(self):
        messages, tail = split_stream("^FO50,50" + LABEL)
        assert kinds(messages) == [(MessageKind.FORMAT, LABEL)]
        assert tail == ""

    @pytest.mark.parametrize(
        "junk",
        ["", " ", "\r\n", "\x00", "garbage", "^", "~", "^^", "~~", "^X", "^XA", "!"],
    )
    def test_returns_without_looping(self, junk):
        """If any of these loops, the test run hangs rather than failing."""
        messages, tail = split_stream(junk)
        assert isinstance(messages, list)
        assert len(tail) <= len(junk)

    def test_junk_before_a_label_is_dropped(self):
        messages, _ = split_stream("garbage" + LABEL)
        assert kinds(messages) == [(MessageKind.FORMAT, LABEL)]

    def test_junk_alone_yields_nothing(self):
        assert split_stream("garbage")[0] == []

    def test_separators_between_messages_are_consumed(self):
        messages, tail = split_stream(f"\r\n\t {LABEL}\r\n\r\n{OTHER}  ")
        assert len(messages) == 2
        assert tail == ""


class TestNormalise:
    def test_record_separator_becomes_a_caret(self):
        assert normalise("\x1eXA\x1eXZ") == "^XA^XZ"

    def test_data_link_escape_becomes_a_tilde(self):
        assert normalise("\x10HS") == "~HS"

    def test_leaves_ordinary_text_alone(self):
        assert normalise(LABEL) == LABEL

    def test_control_characters_frame_a_real_label(self):
        messages, _ = split_stream(normalise("\x1eXA\x1eFDHi\x1eFS\x1eXZ"))
        assert kinds(messages) == [(MessageKind.FORMAT, "^XA^FDHi^FS^XZ")]
