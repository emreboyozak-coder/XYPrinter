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
            records.append((f"P{pcb}_B", x + 13.8, y, 0.0))
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
    assert (result[-1].core.x_mm, result[-1].core.y_mm) == (93.8, 45.0)


def test_semicolon_file_and_mil_units_are_supported(tmp_path) -> None:
    records = []
    for pcb in range(20):
        base_x_mil = pcb * 1000
        records.extend(((f"C{pcb}A", base_x_mil), (f"C{pcb}B", base_x_mil + 13.8 / 0.0254)))
    path = tmp_path / "cores.txt"
    path.write_text(
        "RefDes;Ref X (mil);Ref Y (mil)\n"
        + "\n".join(f"{name};{x};0" for name, x in reversed(records)),
        encoding="utf-8",
    )

    result = load_pick_place(path)

    assert result[0].core.x_mm == pytest.approx(0.0)
    assert result[1].core.x_mm == pytest.approx(13.8)


def test_exactly_forty_coordinate_rows_are_required(tmp_path) -> None:
    path = tmp_path / "short.csv"
    path.write_text("X,Y\n1,2\n3,4\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected 40 core coordinates, but found 2"):
        load_pick_place(path)


def test_machine_coordinates_reverse_the_cad_y_axis() -> None:
    core = PickPlaceCore("CORE1", 93.600, 18.975)

    assert machine_coordinates(core, (12.0, 30.0)) == pytest.approx((105.600, 11.025))


def test_expected_x_spacing_groups_cores_even_when_other_pcbs_are_closer(tmp_path) -> None:
    records = []
    for pcb in range(1, 21):
        base_x = (pcb - 1) * 10.0
        # Within-PCB distance is 14 mm, while a core on the neighboring PCB is
        # only 4 mm away. Nearest-neighbor grouping would therefore be wrong.
        records.append((f"CORE3_{pcb}", base_x + 13.8, 0.0))
        records.append((f"CORE1_{pcb}", base_x, 0.0))
    random.Random(7).shuffle(records)
    path = tmp_path / "designator_groups.csv"
    path.write_text(
        "Designator,Center-X(mm),Center-Y(mm)\n"
        + "\n".join(f"{name},{x},{y}" for name, x, y in records),
        encoding="utf-8",
    )

    result = load_pick_place(path)

    grouped_names = [
        {item.core.name for item in result if item.pcb_number == pcb_number}
        for pcb_number in range(1, 21)
    ]
    assert all(
        {name.rsplit("_", 1)[1] for name in names} == {next(iter(names)).rsplit("_", 1)[1]}
        for names in grouped_names
    )
    assert all(
        [item.core.name.split("_", 1)[0] for item in result if item.pcb_number == pcb_number]
        == ["CORE1", "CORE3"]
        for pcb_number in range(1, 21)
    )


def test_file_is_rejected_when_cores_cannot_form_13_8_mm_pairs(tmp_path) -> None:
    path = tmp_path / "wrong_spacing.csv"
    path.write_text(
        "Designator,Center-X(mm),Center-Y(mm)\n"
        + "\n".join(f"CORE_{index},{index * 25.0},0" for index in range(40)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="13.8"):
        load_pick_place(path)
