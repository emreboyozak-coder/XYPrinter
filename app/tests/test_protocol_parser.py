from marker.motion.protocol import Command, ProtocolError, parse_command


def test_parse_ping_command() -> None:
    cmd = parse_command("$ID=42 CMD=PING")
    assert cmd.id == 42
    assert cmd.command == "PING"
    assert cmd.params == {}


def test_parse_move_command() -> None:
    cmd = parse_command("$ID=12 CMD=MOVE X=53.400 Y=126.975 F=40.0")
    assert cmd.id == 12
    assert cmd.command == "MOVE"
    assert cmd.params["X"] == 53.4
    assert cmd.params["Y"] == 126.975
    assert cmd.params["F"] == 40.0


def test_invalid_command_rejected() -> None:
    try:
        parse_command("PING")
        raise AssertionError("Expected ProtocolError")
    except ProtocolError:
        pass


def test_invalid_id_rejected() -> None:
    try:
        parse_command("$ID= CMD=PING")
        raise AssertionError("Expected ProtocolError")
    except ProtocolError:
        pass
