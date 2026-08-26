import random

import pytest

from marker.pick_place import PickPlaceCore, load_pick_place, machine_coordinates


def test_unordered_cores_are_paired_and_sorted_into_twenty_pcbs(tmp_path) -> None:
    records = []
    for row in range(4):
        for column in range(5):
            pcb = row * 5 + column + 1
            x = column * 20.0
            y = row * 15.0
            records.append((f"P{pcb}_B", x + 2.0, y, 0.0))
            records.append((f"P{pcb}_A", x, y, 0.0))
    random.Random(42).shuffle(records)
    path = tmp_path / "cores.csv"
    path.write_text(
        "Designator,Mid X,Mid Y,Rotation\n"
        + "\n".join(f"{name},{x}mm,{y}mm,{rotation}" for name, x, y, rotation in records),
        encoding="utf-8",
    )

    result = load_pick_place(path)

    assert len(result) == 40
    assert [(item.pcb_number, item.core_number) for item in result] == [
        (pcb, core) for pcb in range(1, 21) for core in (1, 2)
    ]
    assert (result[0].core.x_mm, result[0].core.y_mm) == (0.0, 0.0)
    assert (result[-1].core.x_mm, result[-1].core.y_mm) == (82.0, 45.0)


def test_semicolon_file_and_mil_units_are_supported(tmp_path) -> None:
    records = []
    for pcb in range(20):
        base_x_mil = pcb * 1000
        records.extend(((f"C{pcb}A", base_x_mil), (f"C{pcb}B", base_x_mil + 100)))
    path = tmp_path / "cores.txt"
    path.write_text(
        "RefDes;Ref X (mil);Ref Y (mil)\n"
        + "\n".join(f"{name};{x};0" for name, x in reversed(records)),
        encoding="utf-8",
    )

    result = load_pick_place(path)

    assert result[0].core.x_mm == pytest.approx(0.0)
    assert result[1].core.x_mm == pytest.approx(2.54)


def test_exactly_forty_coordinate_rows_are_required(tmp_path) -> None:
    path = tmp_path / "short.csv"
    path.write_text("X,Y\n1,2\n3,4\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected 40 core coordinates, but found 2"):
        load_pick_place(path)


def test_machine_coordinates_reverse_the_cad_y_axis() -> None:
    core = PickPlaceCore("CORE1", 93.600, 18.975)

    assert machine_coordinates(core, (12.0, 30.0)) == pytest.approx((105.600, 11.025))
