from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


class ProtocolError(ValueError):
    """Raised when a command line is malformed."""


@dataclass(frozen=True)
class Command:
    id: int
    command: str
    params: Dict[str, float | int | str] = field(default_factory=dict)


def _parse_value(raw: str) -> float | int | str:
    if raw == "":
        raise ProtocolError("Empty parameter value")
    if raw.upper() in {"TRUE", "FALSE"}:
        return raw.upper() == "TRUE"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError as exc:
        return raw


def parse_command(line: str) -> Command:
    text = line.strip()
    if not text or not text.startswith("$"):
        raise ProtocolError("Command must begin with '$'")

    if "CMD=" not in text:
        raise ProtocolError("Command missing CMD=")

    payload = text[1:]
    parts = payload.split()
    if len(parts) < 2:
        raise ProtocolError("Command requires ID and CMD")

    id_part = parts[0]
    if not id_part.startswith("ID="):
        raise ProtocolError("First token must be ID=<n>")

    command_part = parts[1]
    if not command_part.startswith("CMD="):
        raise ProtocolError("Second token must be CMD=<COMMAND>")

    try:
        command_id = int(id_part.split("=", 1)[1])
    except ValueError as exc:
        raise ProtocolError("Command ID must be an integer") from exc

    params: Dict[str, float | int | str] = {}
    for token in parts[2:]:
        if "=" not in token:
            raise ProtocolError(f"Malformed parameter: {token}")
        key, value = token.split("=", 1)
        params[key.upper()] = _parse_value(value)

    command_name = command_part.split("=", 1)[1].upper()
    return Command(id=command_id, command=command_name, params=params)


def format_command(command: str, command_id: int, **params: float | int | str) -> str:
    tokens = [f"$ID={command_id} CMD={command.upper()}"]
    for key, value in params.items():
        tokens.append(f"{key.upper()}={value}")
    return " ".join(tokens)
