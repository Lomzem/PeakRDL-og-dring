import re
from pathlib import Path

import pytest
from systemrdl.compiler import RDLCompiler

from peakrdl_og_dring import export_file
from peakrdl_og_dring.exporter import (
    OgDringExporter,
    generated_identifier,
    make_guard,
    normalize_comment_text,
)

def compile_rdl(tmp_path: Path, text: str):
    path = tmp_path / "input.rdl"
    path.write_text(text, encoding="utf-8")
    rdlc = RDLCompiler()
    rdlc.compile_file(str(path))
    return rdlc.elaborate()


def export_text(tmp_path: Path, text: str, *, guard_prefix: str = "TEST_HEADER") -> str:
    output = tmp_path / "out.h"
    OgDringExporter().export(
        compile_rdl(tmp_path, text),
        output,
        guard_prefix=guard_prefix,
    )
    return output.read_text(encoding="utf-8")


def test_register_parameter_and_table_output(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg {
                field {} high_bits[7:4];
                field {} low_bits[1:0];
            } system_control_genlock @ 0x05;
        };
        """,
    )

    assert "\tREG_SYSTEM_CONTROL_GENLOCK = 0x05," in out
    assert (
        "\tSYSTEM_CONTROL_GENLOCK_HIGH_BITS, // address: 0x05, mask: 0xF0, shift: 0x04"
        in out
    )
    assert (
        "\tSYSTEM_CONTROL_GENLOCK_LOW_BITS, // address: 0x05, mask: 0x03, shift: 0x00"
        in out
    )
    assert "\tPARAM_COUNT\n" in out
    assert "static const ParamComp ParamTable[PARAM_COUNT] =" in out
    assert "\t{REG_SYSTEM_CONTROL_GENLOCK, 0xF0, 0x04}," in out
    assert "\t{REG_SYSTEM_CONTROL_GENLOCK, 0x03, 0x00}," in out
    assert "kLastParam" not in out
    assert "// SYSTEM_CONTROL_GENLOCK_HIGH_BITS" not in out


def test_register_address_accepts_supported_int_boundaries(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[0:0]; } first @ 0x00;
            reg { field {} value[0:0]; } last @ 0x7FFFFFFF;
        };
        """,
    )

    assert "\tREG_FIRST = 0x00," in out
    assert "\tREG_LAST = 0x7FFFFFFF," in out


def test_register_address_above_supported_int_range_preserves_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[0:0]; } too_far @ 0x80000000;
        };
        """,
    )

    with pytest.raises(
        ValueError,
        match=(
            r"address for register too_far is 2147483648; "
            r"supported C enum range is 0\.\.2147483647"
        ),
    ):
        OgDringExporter().export(root, output)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_register_array_is_rejected_before_address_access(tmp_path: Path) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg item_t { field {} value[0:0]; };
            item_t items[2] @ 0x00 += 0x01;
        };
        """,
    )

    with pytest.raises(
        ValueError,
        match=r"register arrays are not supported: register items",
    ):
        OgDringExporter().export(root, output)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_doc_groups_are_kept_for_registers_and_parameters(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        property doc_group {
            type = string;
            component = reg;
        };
        addrmap top {
            default regwidth = 8;
            reg {
                doc_group = "System Control";
                field {} select[3:0];
            } control @ 0x05;
        };
        """,
    )

    assert out.count("\t// System Control") == 2
    registers, remainder = out.split("enum Parameters", 1)
    parameters, table = remainder.split("static const ParamComp", 1)
    assert "\t// System Control" in registers
    assert "\t// System Control" in parameters
    assert "\t// System Control" not in table
    assert "\t{REG_CONTROL, 0x0F, 0x00}," in table


def test_doc_group_is_safe_single_line_comment(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        r'''
        property doc_group {
            type = string;
            component = reg;
        };
        addrmap top {
            default regwidth = 8;
            reg {
                doc_group = "First
                    second\\path";
                field {} value[0:0];
            } control @ 0x00;
        };
        ''',
    )

    comment = "\t// First second" + r"\x5Cpath"
    assert out.count(comment) == 2
    assert all(not line.endswith("\\") for line in out.splitlines())


def test_doc_group_trailing_backslash_has_safe_visible_text() -> None:
    normalized = normalize_comment_text("Trailing\\")

    assert normalized == r"Trailing\x5C"
    assert normalized[-1] == "C"


def test_doc_group_line_splicing_trigraph_is_neutralized(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        property doc_group {
            type = string;
            component = reg;
        };
        addrmap top {
            default regwidth = 8;
            reg {
                doc_group = "Question??/";
                field {} value[0:0];
            } control @ 0x00;
        };
        """,
    )

    assert out.count("\t// Question?? /") == 2
    assert "??/" not in out


def test_doc_group_restarts_after_ungrouped_register(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        property doc_group {
            type = string;
            component = reg;
        };
        addrmap top {
            default regwidth = 8;
            reg { doc_group = "Shared"; field {} value[0:0]; } first @ 0x00;
            reg { field {} value[0:0]; } middle @ 0x01;
            reg { doc_group = "Shared"; field {} value[0:0]; } last @ 0x02;
        };
        """,
    )

    registers, remainder = out.split("enum Parameters", 1)
    parameters = remainder.split("static const ParamComp", 1)[0]
    assert registers.count("\t// Shared") == 2
    assert parameters.count("\t// Shared") == 2
    assert (
        "\t// Shared\n"
        "\tREG_FIRST = 0x00,\n\n"
        "\tREG_MIDDLE = 0x01,\n\n"
        "\t// Shared\n"
        "\tREG_LAST = 0x02,"
        in registers
    )
    assert (
        "\t// Shared\n"
        "\tFIRST_VALUE, // address: 0x00, mask: 0x01, shift: 0x00\n\n"
        "\tMIDDLE_VALUE, // address: 0x01, mask: 0x01, shift: 0x00\n\n"
        "\t// Shared\n"
        "\tLAST_VALUE, // address: 0x02, mask: 0x01, shift: 0x00"
        in parameters
    )


def test_64_bit_mask_is_supported(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        addrmap top {
            default regwidth = 64;
            reg { field {} value[63:0]; } wide @ 0x00;
        };
        """,
    )

    assert (
        "\tWIDE_VALUE, // address: 0x00, mask: 0xFFFFFFFFFFFFFFFF, shift: 0x00"
        in out
    )
    assert "\t{REG_WIDE, 0xFFFFFFFFFFFFFFFF, 0x00}," in out


def test_65_bit_mask_is_rejected_without_changing_output(tmp_path: Path) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 128;
            reg { field {} value[64:0]; } wide @ 0x00;
        };
        """,
    )

    with pytest.raises(
        ValueError,
        match=(
            r"mask for field wide\.value is 0x1FFFFFFFFFFFFFFFF; "
            r"supported maximum is 0xFFFFFFFFFFFFFFFF"
        ),
    ):
        OgDringExporter().export(root, output)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_encoded_enum_is_named_for_field_use(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        enum mode_e {
            disabled = 0;
            Enabled = 3;
        };
        addrmap top {
            default regwidth = 8;
            reg {
                field { encode = mode_e; } genlock_select[7:4];
            } system_control @ 0x05;
        };
        """,
    )

    assert (
        "// Parameter SYSTEM_CONTROL_GENLOCK_SELECT "
        "(system_control.genlock_select)\nenum SYSTEM_CONTROL_GENLOCK_SELECT_E"
        in out
    )
    assert "\tSYSTEM_CONTROL_GENLOCK_SELECT_DISABLED = 0x00," in out
    assert "\tSYSTEM_CONTROL_GENLOCK_SELECT_ENABLED = 0x03," in out
    assert "enum mode_e" not in out


def test_encoded_enum_accepts_supported_int_boundaries(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        enum limits_e {
            MINIMUM = 0;
            MAXIMUM = 2147483647;
        };
        addrmap top {
            default regwidth = 32;
            reg {
                field { encode = limits_e; } value[30:0];
            } limits @ 0x00;
        };
        """,
    )

    assert "\tLIMITS_VALUE_MINIMUM = 0x00," in out
    assert "\tLIMITS_VALUE_MAXIMUM = 0x7FFFFFFF," in out


def test_encoded_enum_rejects_value_above_supported_int_range(tmp_path: Path) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        enum limits_e { TOO_LARGE = 2147483648; };
        addrmap top {
            default regwidth = 32;
            reg {
                field { encode = limits_e; } value[31:0];
            } limits @ 0x00;
        };
        """,
    )

    with pytest.raises(
        ValueError,
        match=(
            r"limits\.value member TOO_LARGE is 2147483648; "
            r"supported C enum range is 0\.\.2147483647"
        ),
    ):
        OgDringExporter().export(root, output)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_same_enum_identifier_with_different_definitions_generates_each_use(
    tmp_path: Path,
) -> None:
    out = export_text(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg {
                enum mode_e { OFF = 0; ON = 1; };
                field { encode = mode_e; } mode[0:0];
            } first @ 0x00;
            reg {
                enum mode_e { LOW = 0; HIGH = 3; };
                field { encode = mode_e; } mode[1:0];
            } second @ 0x01;
        };
        """,
    )

    assert "enum FIRST_MODE_E" in out
    assert "\tFIRST_MODE_ON = 0x01," in out
    assert "enum SECOND_MODE_E" in out
    assert "\tSECOND_MODE_HIGH = 0x03," in out
    assert out.index("enum FIRST_MODE_E") < out.index("enum SECOND_MODE_E")


def test_generated_sections_do_not_align_columns(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        enum values_e { A = 0; LONG_VALUE = 1; };
        addrmap top {
            default regwidth = 8;
            reg { field { encode = values_e; } x[0:0]; } short @ 0x00;
            reg { field {} longer_field[7:0]; } a_much_longer_register @ 0x01;
        };
        """,
    )

    generated_lines = [
        line
        for line in out.splitlines()
        if line.startswith("\t") and not line.lstrip().startswith("//")
    ]
    assert not any(re.search(r"\S {2,}=", line) for line in generated_lines)
    assert not any(re.search(r"},\s+//", line) for line in generated_lines)


@pytest.mark.parametrize(
    ("rdl", "symbol"),
    [
        (
            """
            addrmap top {
                default regwidth = 8;
                reg { field {} value[0:0]; } status @ 0x00;
                reg { field {} value[0:0]; } STATUS @ 0x01;
            };
            """,
            "REG_STATUS",
        ),
        (
            """
            addrmap top {
                default regwidth = 8;
                reg { field {} b_c[0:0]; } a @ 0x00;
                reg { field {} c[0:0]; } a_b @ 0x01;
            };
            """,
            "A_B_C",
        ),
        (
            """
            addrmap top {
                default regwidth = 8;
                reg { field {} count[0:0]; } param @ 0x00;
            };
            """,
            "PARAM_COUNT",
        ),
        (
            """
            enum values_e { low = 0; LOW = 1; };
            addrmap top {
                default regwidth = 8;
                reg { field { encode = values_e; } value[0:0]; } control @ 0x00;
            };
            """,
            "CONTROL_VALUE_LOW",
        ),
    ],
)
def test_generated_symbol_collisions_are_rejected(
    tmp_path: Path, rdl: str, symbol: str
) -> None:
    with pytest.raises(ValueError, match=rf"collision for '{symbol}'"):
        export_text(tmp_path, rdl)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("_", "RDL"),
        ("__foo", "FOO"),
        ("_Upper", "UPPER"),
        ("123value", "RDL_123VALUE"),
    ],
)
def test_generated_identifier_avoids_reserved_c_forms(
    source: str, expected: str
) -> None:
    assert generated_identifier(source) == expected
    assert not expected.startswith("__")
    assert not re.match(r"_[A-Z]", expected)


def test_safe_sanitization_applies_to_all_rdl_components(tmp_path: Path) -> None:
    out = export_text(
        tmp_path,
        """
        enum values_e { _ = 0; };
        addrmap top {
            default regwidth = 8;
            reg {
                field { encode = values_e; } _Upper[0:0];
            } __foo @ 0x00;
        };
        """,
    )

    assert "\tREG_FOO = 0x00," in out
    assert "\tFOO_UPPER," in out
    assert "enum FOO_UPPER_E" in out
    assert "\tFOO_UPPER_RDL = 0x00," in out


def test_safe_sanitization_collisions_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"collision for 'REG_FOO'"):
        export_text(
            tmp_path,
            """
            addrmap top {
                default regwidth = 8;
                reg { field {} value[0:0]; } __foo @ 0x00;
                reg { field {} value[0:0]; } foo @ 0x01;
            };
            """,
        )


def test_empty_model_is_rejected_without_writing_output(tmp_path: Path) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            mem {
                memwidth = 8;
                mementries = 1;
            } external storage;
        };
        """,
    )

    with pytest.raises(ValueError, match="model contains no registers"):
        OgDringExporter().export(root, output)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_guard_prefix_sanitization() -> None:
    assert make_guard("demo device param dring") == "DEMO_DEVICE_PARAM_DRING_H_"


def test_guard_from_header_filename() -> None:
    assert make_guard("demo_param_dring.h") == "DEMO_PARAM_DRING_H_"


def test_default_guard_uses_output_filename(tmp_path: Path) -> None:
    output_path = tmp_path / "demo_param_dring.h"
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[0:0]; } status @ 0x00;
        };
        """,
    )

    OgDringExporter().export(root, output_path)

    out = output_path.read_text(encoding="utf-8")
    assert "#ifndef DEMO_PARAM_DRING_H_\n" in out
    assert "_H_H_" not in out


@pytest.mark.parametrize("param_include", ["", 'bad\"name.h', "bad\rname.h", "bad\nname.h", r"dir\name.h"])
def test_invalid_param_include_preserves_output(
    tmp_path: Path, param_include: str
) -> None:
    output = tmp_path / "out.h"
    output.write_text("unchanged", encoding="utf-8")
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[0:0]; } status @ 0x00;
        };
        """,
    )

    with pytest.raises(ValueError, match="param_include must be a non-empty header name"):
        OgDringExporter().export(root, output, param_include=param_include)

    assert output.read_text(encoding="utf-8") == "unchanged"


def test_relative_param_include_is_supported(tmp_path: Path) -> None:
    output = tmp_path / "out.h"
    root = compile_rdl(
        tmp_path,
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[0:0]; } status @ 0x00;
        };
        """,
    )

    OgDringExporter().export(root, output, param_include="../api/param-services_v2.h")

    assert '#include "../api/param-services_v2.h"' in output.read_text(encoding="utf-8")


def test_export_file_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.rdl"
    output_path = tmp_path / "out.h"
    input_path.write_text(
        """
        addrmap top {
            default regwidth = 8;
            reg { field {} value[7:0]; } status_reg @ 0x12;
        };
        """,
        encoding="utf-8",
    )

    export_file(input_path, output_path, guard_prefix="PY_API")

    out = output_path.read_text(encoding="utf-8")
    assert "#ifndef PY_API_H_" in out
    assert "{REG_STATUS_REG, 0xFF, 0x00}" in out

