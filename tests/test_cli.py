"""Argument parsing.

Several of these guard against options that looked configurable and were not, or
that advertised values argparse would then reject.
"""

import pytest

from zplserver.app import DEFAULT_UI_PORT, build_parser, int_range
from zplserver.printer import DPI


@pytest.fixture
def parser():
    return build_parser()


def parse(parser, *args):
    return parser.parse_args(list(args))


class TestIntRange:
    def test_accepts_the_bounds(self):
        check = int_range("thing", 2, 12)
        assert check("2") == 2
        assert check("12") == 12

    @pytest.mark.parametrize("value", ["1", "13", "0", "-4"])
    def test_rejects_out_of_range(self, value):
        with pytest.raises(Exception, match=r"\[2, 12\]"):
            int_range("thing", 2, 12)(value)

    @pytest.mark.parametrize("value", ["", "abc", "4.5", "0x10"])
    def test_rejects_non_numbers(self, value):
        with pytest.raises(Exception, match="valid number"):
            int_range("thing", 2, 12)(value)

    def test_names_the_parameter_it_was_given(self):
        """All three options once passed "width", so errors named the wrong one."""
        with pytest.raises(Exception, match="height"):
            int_range("height", 2, 12)("abc")


class TestDefaults:
    def test_defaults(self, parser):
        args = parse(parser)
        assert args.width == 4
        assert args.height == 3
        assert args.port == 9100
        assert args.dpi is DPI.DPI_300
        assert args.ui_port == DEFAULT_UI_PORT
        assert args.verbose is False

    def test_the_ui_port_default(self, parser):
        assert parse(parser).ui_port == 8082

    def test_run_ui_agrees_with_the_parser_default(self):
        """Two definitions of the same default drift apart otherwise."""
        import inspect

        from zplserver.ui.web import run_ui

        signature = inspect.signature(run_ui)
        assert signature.parameters["ui_port"].default == DEFAULT_UI_PORT

    def test_the_web_interface_is_the_default(self):
        """Bare `zplserver` serves the interface; --headless opts out."""
        assert parse(build_parser()).headless is False
        assert parse(build_parser(), "--headless").headless is True


class TestPort:
    def test_an_explicit_default_port_is_accepted(self, parser):
        """--port was validated against the height range, so -p 9100 failed."""
        assert parse(parser, "-p", "9100").port == 9100

    @pytest.mark.parametrize("port", ["1", "80", "8080", "9100", "65535"])
    def test_accepts_the_usable_range(self, parser, port):
        assert parse(parser, "--port", port).port == int(port)

    @pytest.mark.parametrize("port", ["0", "65536", "99999"])
    def test_rejects_impossible_ports(self, parser, port):
        with pytest.raises(SystemExit):
            parse(parser, "--port", port)


class TestGeometry:
    @pytest.mark.parametrize("width", ["1", "4", "6", "15"])
    def test_width_is_configurable(self, parser, width):
        """int_range("width", 4, 4) allowed only 4 while looking adjustable."""
        assert parse(parser, "--width", width).width == int(width)

    @pytest.mark.parametrize("width", ["0", "16"])
    def test_width_bounds(self, parser, width):
        with pytest.raises(SystemExit):
            parse(parser, "--width", width)

    @pytest.mark.parametrize("height", ["2", "3", "6", "12"])
    def test_height_is_configurable(self, parser, height):
        assert parse(parser, "--height", height).height == int(height)

    @pytest.mark.parametrize("height", ["1", "13"])
    def test_height_bounds(self, parser, height):
        with pytest.raises(SystemExit):
            parse(parser, "--height", height)


class TestDpi:
    @pytest.mark.parametrize("dpi", ["203", "300"])
    def test_accepts_the_bare_values(self, parser, dpi):
        assert parse(parser, "-d", dpi).dpi is DPI(dpi)

    def test_help_advertises_values_that_parse(self, parser):
        """--help showed {DPI.DPI_203,DPI.DPI_300}, neither of which was accepted."""
        help_text = parser.format_help()
        assert "{203,300}" in help_text
        assert "DPI_203" not in help_text

    def test_help_shows_the_default(self, parser):
        assert "default: 300" in parser.format_help()

    @pytest.mark.parametrize("dpi", ["600", "DPI_203", "203dpi", ""])
    def test_rejects_anything_else(self, parser, dpi):
        with pytest.raises(SystemExit):
            parse(parser, "-d", dpi)


class TestModeOptions:
    def test_headless_flag(self, parser):
        assert parse(parser, "--headless").headless is True

    def test_labels_open_by_default_in_headless_mode(self, parser):
        assert parse(parser, "--headless").no_open_labels is False

    def test_no_open_labels_flag(self, parser):
        assert parse(parser, "--headless", "--no-open-labels").no_open_labels is True

    def test_no_browser(self, parser):
        assert parse(parser, "--no-browser").no_browser is True

    def test_ui_port(self, parser):
        assert parse(parser, "--ui-port", "9999").ui_port == 9999

    def test_ui_port_is_range_checked(self, parser):
        with pytest.raises(SystemExit):
            parse(parser, "--ui-port", "0")

    def test_the_removed_ui_flag_is_gone(self, parser):
        """The interface is the default now, so --ui would be meaningless."""
        with pytest.raises(SystemExit):
            parse(parser, "--ui")

    def test_help_does_not_name_the_vendor(self, parser):
        assert "zebra" not in parser.format_help().lower()


class TestModeSelection:
    """run() dispatches on --headless; neither branch is allowed to run a server."""

    def _run(self, monkeypatch, argv):
        """Invoke run() with both servers stubbed, reporting which was chosen."""
        calls = {}

        def fake_run_server(printer, open_labels=True):
            calls["headless"] = {"open_labels": open_labels}

        def fake_run_ui(printer, ui_port=0, open_browser=True):
            calls["ui"] = {"ui_port": ui_port, "open_browser": open_browser}

        # The stubs are plain functions, so asyncio.run receives their return
        # value rather than a coroutine and simply does nothing with it.
        import zplserver.ui

        monkeypatch.setattr("sys.argv", ["zplserver"] + argv)
        monkeypatch.setattr("zplserver.app.asyncio.run", lambda result: result)
        monkeypatch.setattr("zplserver.app.run_server", fake_run_server)
        monkeypatch.setattr(zplserver.ui, "run_ui", fake_run_ui)

        from zplserver.app import run

        run()
        return calls

    def test_bare_invocation_serves_the_interface(self, monkeypatch):
        calls = self._run(monkeypatch, [])
        assert "ui" in calls and "headless" not in calls
        assert calls["ui"]["open_browser"] is True

    def test_no_browser_still_serves_the_interface(self, monkeypatch):
        calls = self._run(monkeypatch, ["--no-browser"])
        assert calls["ui"]["open_browser"] is False

    def test_ui_port_is_passed_through(self, monkeypatch):
        calls = self._run(monkeypatch, ["--ui-port", "9001"])
        assert calls["ui"]["ui_port"] == 9001

    def test_headless_runs_the_terminal_server(self, monkeypatch):
        calls = self._run(monkeypatch, ["--headless"])
        assert "headless" in calls and "ui" not in calls

    def test_headless_opens_labels_by_default(self, monkeypatch):
        calls = self._run(monkeypatch, ["--headless"])
        assert calls["headless"]["open_labels"] is True

    def test_headless_can_be_told_not_to(self, monkeypatch):
        calls = self._run(monkeypatch, ["--headless", "--no-open-labels"])
        assert calls["headless"]["open_labels"] is False

    def test_no_open_labels_without_headless_is_refused(self, monkeypatch, capsys):
        """Rather than silently ignoring it and looking like it worked."""
        monkeypatch.setattr("sys.argv", ["zplserver", "--no-open-labels"])
        from zplserver.app import run

        with pytest.raises(SystemExit):
            run()
        assert (
            "--no-open-labels only applies with --headless"
            in capsys.readouterr().err
        )
