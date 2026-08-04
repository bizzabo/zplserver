"""The command table and the stream parser.

Most of these are regressions: each one failed at some point and produced
plausible-looking but wrong output rather than an error, which is why they are
worth pinning down.
"""

import pytest

from bizzabo_zpl.zpllib import command_map, parse_zpl, pattern


def commands(zpl):
    return [command.command for command in parse_zpl(zpl)]


def only(zpl):
    parsed = parse_zpl(zpl)
    assert len(parsed) == 1, [command.command for command in parsed]
    return parsed[0]


class TestCommandTable:
    def test_every_entry_has_a_format_and_description(self):
        for name, schema in command_map.items():
            assert set(schema) == {"format", "description"}, name
            assert schema["description"], name

    def test_no_description_names_the_vendor(self):
        # The descriptions are original wording and must stay that way.
        forbidden = ("zebra", "zebranet", "intellifont")
        for name, schema in command_map.items():
            lowered = schema["description"].lower()
            for word in forbidden:
                assert word not in lowered, f"{name}: {schema['description']}"

    def test_alternation_is_longest_first(self):
        """A command that is a prefix of another must not shadow it.

        Regex alternation is ordered, so building the pattern in dictionary order
        let "^A" win over "^A@".
        """
        alternatives = pattern.pattern.split("|")
        lengths = [len(alt.replace("\\", "")) for alt in alternatives]
        assert lengths == sorted(lengths, reverse=True)

    def test_every_command_matches_itself(self):
        for name in command_map:
            match = pattern.match(name)
            assert match is not None and match.group() == name, name


class TestParsing:
    def test_a_at_is_not_shadowed_by_a(self):
        parsed = only("^A@N,40,40,E:FONT.TTF")
        assert parsed.command == "^A@"
        assert parsed.parameters["o"] == "N"
        assert parsed.parameters["d:f.x"] == "E:FONT.TTF"

    def test_plain_a_still_parses(self):
        assert only("^A0N,40,40").command == "^A"

    def test_last_character_is_not_dropped(self):
        """`end = len(zpl) - 1` truncated the final parameter."""
        assert only("^FDHello").parameters["a"] == "Hello"

    def test_trailing_command_with_no_parameters(self):
        assert commands("^XA^XZ") == ["^XA", "^XZ"]
        assert parse_zpl("^XA^XZ")[-1].parameters == {}

    def test_comma_inside_the_final_parameter_survives(self):
        """Splitting on every comma truncated "^FDLast, First" to "Last"."""
        parsed = parse_zpl("^XA^FDLast, First^FS^XZ")
        assert parsed[1].parameters["a"] == "Last, First"

    def test_declared_parameters_still_split(self):
        parsed = only("^FO50,60,2")
        assert parsed.parameters == {"x": "50", "y": "60", "z": "2"}

    def test_missing_trailing_parameters_are_absent(self):
        assert only("^FO50,60").parameters == {"x": "50", "y": "60"}

    def test_newlines_between_commands_are_not_parameters(self):
        parsed = parse_zpl("^XA\r\n^FDHi^FS\r\n^XZ")
        assert commands("^XA\r\n^FDHi^FS\r\n^XZ") == ["^XA", "^FD", "^FS", "^XZ"]
        assert parsed[1].parameters["a"] == "Hi"

    def test_unknown_text_is_ignored(self):
        assert commands("hello ^XA world ^XZ") == ["^XA", "^XZ"]

    def test_empty_input(self):
        assert parse_zpl("") == []

    def test_realistic_label(self):
        zpl = (
            "^XA^LH0,0^FO50,50^A0N,40,40^FDHello^FS"
            "^BY2^FO50,120^BCN,80,Y,N,N^FD12345^FS^XZ"
        )
        assert commands(zpl) == [
            "^XA", "^LH", "^FO", "^A", "^FD", "^FS",
            "^BY", "^FO", "^BC", "^FD", "^FS", "^XZ",
        ]

    @pytest.mark.parametrize("data", ["", "x", "a,b,c,d,e", "Ünïcodé", "50%"])
    def test_field_data_round_trips(self, data):
        parsed = parse_zpl(f"^XA^FD{data}^FS^XZ")
        field = next(c for c in parsed if c.command == "^FD")
        assert field.parameters.get("a", "") == data

    def test_str_hides_binary_payloads(self):
        rendered = str(only("~DGR:IMG.GRF,8,1,DEADBEEF"))
        assert "data=[data]" in rendered
        assert "DEADBEEF" not in rendered
