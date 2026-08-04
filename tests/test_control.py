"""The "! U1 ..." control commands, and printer configuration."""

import pytest

from zplserver.printer import DPI, Printer


@pytest.fixture
def p(printer):
    return printer


class TestGetvar:
    def test_known_attribute(self, p):
        assert p.handle_command('! U1 getvar "appl.name"') == "V74.20.22Z"

    def test_unknown_attribute_is_empty(self, p):
        assert p.handle_command('! U1 getvar "nope.nope"') == ""

    def test_without_quotes(self, p):
        assert p.handle_command("! U1 getvar appl.name") == "V74.20.22Z"

    def test_without_a_space_after_the_bang(self, p):
        assert p.handle_command('!U1 getvar "appl.name"') == "V74.20.22Z"

    def test_with_trailing_newline(self, p):
        assert p.handle_command('! U1 getvar "appl.name"\r\n') == "V74.20.22Z"

    def test_reports_the_configured_resolution(self, p):
        assert p.handle_command('! U1 getvar "head.resolution.in_dpi"') == "300"

    def test_reports_a_host_name(self, p):
        assert p.handle_command('! U1 getvar "device.host_identification"')


class TestSetvar:
    def test_sets_then_reads_back(self, p):
        p.handle_command('! U1 setvar "media.darkness" "20"')
        assert p.handle_command('! U1 getvar "media.darkness"') == "20"

    def test_returns_the_value_set(self, p):
        assert p.handle_command('! U1 setvar "media.darkness" "20"') == "20"

    def test_empty_value(self, p):
        assert p.handle_command('! U1 setvar "x" ""') == ""
        assert p.handle_command('! U1 getvar "x"') == ""

    def test_missing_value_does_not_raise(self, p):
        """This used to raise ValueError and kill the connection."""
        assert p.handle_command('! U1 setvar "y"') == ""

    def test_attribute_beginning_with_the_prefix_characters(self, p):
        """lstrip("! U1 ") took a character set, eating any leading !, space, U, 1."""
        p.handle_command('! U1 setvar "U1.thing" "7"')
        assert p.handle_command('! U1 getvar "U1.thing"') == "7"

    @pytest.mark.parametrize("attribute", ["U1", "1U1", "U1.U1", "11"])
    def test_attribute_made_only_of_prefix_characters(self, p, attribute):
        p.handle_command(f'! U1 setvar "{attribute}" "9"')
        assert p.handle_command(f'! U1 getvar "{attribute}"') == "9"


class TestMalformed:
    """None of these may raise: an exception here closes the connection."""

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "!",
            "! ",
            "! U1",
            "! U1 ",
            "! U1 getvar",
            "! U1 setvar",
            "! U1 do",
            "! U1 unknowncommand",
            "! U1 unknowncommand attribute value",
            '! U1 getvar ""',
            "garbage",
        ],
    )
    def test_does_not_raise(self, p, message):
        assert isinstance(p.handle_command(message), str)

    def test_do_command_is_accepted(self, p):
        assert isinstance(p.handle_command('! U1 do "device.reset" ""'), str)


class TestConfiguration:
    @pytest.mark.parametrize(
        ("dpi", "dpmm"), [(DPI.DPI_203, 8), (DPI.DPI_300, 12)]
    )
    def test_dpmm_follows_dpi(self, dpi, dpmm):
        assert Printer(4, 3, dpi, 0).dpmm == dpmm

    @pytest.mark.parametrize("dpi", list(DPI))
    def test_getvar_agrees_with_the_configured_dpi(self, dpi):
        p = Printer(4, 3, dpi, 0)
        assert p.handle_command('! U1 getvar "head.resolution.in_dpi"') == dpi.value

    def test_dpi_renders_as_a_bare_value(self):
        """argparse formats choices with str(), so this is what --help shows."""
        assert str(DPI.DPI_203) == "203"
        assert [str(d) for d in DPI] == ["203", "300"]

    def test_dpi_accepts_the_values_help_advertises(self):
        for shown in (str(d) for d in DPI):
            assert DPI(shown) in list(DPI)

    def test_firmware_string_names_no_vendor(self):
        appl = Printer(4, 3, DPI.DPI_300, 0).vars["appl.name"]
        assert "zebra" not in appl.lower()
