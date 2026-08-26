"""Import and organize unordered PCB-core coordinates from Pick and Place files."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path


EXPECTED_CORE_COUNT = 40
EXPECTED_PAIR_X_DISTANCE_MM = 13.8
PAIR_X_TOLERANCE_MM = 0.5
PAIR_Y_TOLERANCE_MM = 0.5


@dataclass(frozen=True)
class PickPlaceCore:
    name: str
    x_mm: float
    y_mm: float
    rotation_deg: float = 0.0


@dataclass(frozen=True)
class NumberedCore:
    pcb_number: int
    core_number: int
    core: PickPlaceCore


def machine_coordinates(core: PickPlaceCore, origin: tuple[float, float]) -> tuple[float, float]:
    """Map CAD coordinates to the machine, whose Y axis runs opposite to CAD Y."""
    return origin[0] + core.x_mm, origin[1] - core.y_mm


def _normalized_header(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {_normalized_header(header): header for header in headers}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for candidate in candidates:
        for normalized_header, original_header in normalized.items():
            if normalized_header in (f"{candidate}mm", f"{candidate}mil"):
                return original_header
    return None


def _parse_number(raw: str, *, header: str) -> float:
    text = raw.strip().casefold().replace(" ", "")
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if match is None:
        raise ValueError(f"Invalid coordinate value: {raw!r}")
    value = float(match.group(0).replace(",", "."))
    unit_text = f"{header} {text}".casefold()
    if "mil" in unit_text and "mm" not in unit_text:
        value *= 0.0254
    return value


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The Pick and Place file encoding could not be read")


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = _read_text(path)
    meaningful_lines = [line for line in text.splitlines() if line.strip()]
    if not meaningful_lines:
        raise ValueError("The Pick and Place file is empty")
    sample = "\n".join(meaningful_lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in meaningful_lines[0] else csv.excel
    reader = csv.DictReader(meaningful_lines, dialect=dialect)
    headers = [header.strip() for header in (reader.fieldnames or []) if header]
    if not headers:
        raise ValueError("The Pick and Place file has no header row")
    rows = [
        {str(key).strip(): str(value or "").strip() for key, value in row.items() if key is not None}
        for row in reader
    ]
    return headers, rows


def load_pick_place(path: str | Path, *, expected_core_count: int = EXPECTED_CORE_COUNT) -> list[NumberedCore]:
    """Load unordered core coordinates, pair nearest neighbors, and number the panel."""
    source = Path(path)
    headers, rows = _rows(source)
    x_column = _find_column(headers, ("midx", "centerx", "centrex", "refx", "posx", "positionx", "x"))
    y_column = _find_column(headers, ("midy", "centery", "centrey", "refy", "posy", "positiony", "y"))
    if x_column is None or y_column is None:
        raise ValueError(f"X/Y columns were not found. Available columns: {', '.join(headers)}")
    name_column = _find_column(headers, ("designator", "refdes", "reference", "name", "coreid", "id"))
    rotation_column = _find_column(headers, ("rotation", "rotationdeg", "angle", "rot"))

    cores: list[PickPlaceCore] = []
    for row_number, row in enumerate(rows, start=2):
        if not row.get(x_column, "").strip() or not row.get(y_column, "").strip():
            continue
        try:
            x_mm = _parse_number(row[x_column], header=x_column)
            y_mm = _parse_number(row[y_column], header=y_column)
            rotation = _parse_number(row[rotation_column], header=rotation_column) if rotation_column and row.get(rotation_column) else 0.0
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        name = row.get(name_column, "").strip() if name_column else ""
        cores.append(PickPlaceCore(name or f"CORE_{len(cores) + 1}", x_mm, y_mm, rotation))

    if len(cores) != expected_core_count:
        raise ValueError(f"Expected {expected_core_count} core coordinates, but found {len(cores)}")
    return _number_cores(cores)


def _number_cores(cores: list[PickPlaceCore]) -> list[NumberedCore]:
    pairs = _pair_cores_by_spacing(cores)

    def midpoint(pair: tuple[PickPlaceCore, PickPlaceCore]) -> tuple[float, float]:
        return ((pair[0].x_mm + pair[1].x_mm) / 2.0, (pair[0].y_mm + pair[1].y_mm) / 2.0)

    pair_distances = [math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm) for a, b in pairs]
    row_tolerance = max(0.25, sorted(pair_distances)[len(pair_distances) // 2] * 0.25)
    ordered_pairs = sorted(pairs, key=lambda pair: midpoint(pair)[1])
    rows: list[list[tuple[PickPlaceCore, PickPlaceCore]]] = []
    for pair in ordered_pairs:
        pair_y = midpoint(pair)[1]
        if not rows or abs(pair_y - sum(midpoint(item)[1] for item in rows[-1]) / len(rows[-1])) > row_tolerance:
            rows.append([pair])
        else:
            rows[-1].append(pair)

    numbered: list[NumberedCore] = []
    pcb_number = 1
    for row in rows:
        for pair in sorted(row, key=lambda item: midpoint(item)[0]):
            def core_order(core: PickPlaceCore) -> tuple[int, float, float]:
                match = re.match(r"core(\d+)(?:_|$)", core.name.strip(), flags=re.IGNORECASE)
                return (int(match.group(1)) if match else 999999, core.x_mm, core.y_mm)

            ordered_cores = sorted(pair, key=core_order)
            for core_number, core in enumerate(ordered_cores, start=1):
                numbered.append(NumberedCore(pcb_number, core_number, core))
            pcb_number += 1
    return numbered


def _pair_cores_by_spacing(cores: list[PickPlaceCore]) -> list[tuple[PickPlaceCore, PickPlaceCore]]:
    """Find a complete pairing where every PCB has the configured X spacing."""
    candidates: dict[int, list[int]] = {}
    for index, core in enumerate(cores):
        matches = []
        for other_index, other in enumerate(cores):
            if index == other_index:
                continue
            x_error = abs(abs(core.x_mm - other.x_mm) - EXPECTED_PAIR_X_DISTANCE_MM)
            y_error = abs(core.y_mm - other.y_mm)
            if x_error <= PAIR_X_TOLERANCE_MM and y_error <= PAIR_Y_TOLERANCE_MM:
                matches.append(other_index)
        candidates[index] = sorted(
            matches,
            key=lambda other_index: (
                abs(abs(core.x_mm - cores[other_index].x_mm) - EXPECTED_PAIR_X_DISTANCE_MM),
                abs(core.y_mm - cores[other_index].y_mm),
            ),
        )

    def solve(remaining: frozenset[int]) -> list[tuple[int, int]] | None:
        if not remaining:
            return []
        first = min(
            remaining,
            key=lambda index: sum(1 for candidate in candidates[index] if candidate in remaining),
        )
        for second in candidates[first]:
            if second not in remaining:
                continue
            result = solve(remaining - {first, second})
            if result is not None:
                return [(first, second), *result]
        return None

    matched_indexes = solve(frozenset(range(len(cores))))
    if matched_indexes is None:
        raise ValueError(
            f"The 40 cores could not be grouped into pairs with X spacing "
            f"{EXPECTED_PAIR_X_DISTANCE_MM:.1f} +/- {PAIR_X_TOLERANCE_MM:.1f} mm "
            f"and Y difference <= {PAIR_Y_TOLERANCE_MM:.1f} mm"
        )
    return [(cores[first], cores[second]) for first, second in matched_indexes]
