from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from systemrdl.compiler import RDLCompiler
from systemrdl.node import AddrmapNode, RegNode, RootNode


C_ENUM_VALUE_MIN = 0
C_ENUM_VALUE_MAX = (1 << 31) - 1
UINT64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class Register:
    c_name: str
    source_name: str
    address: int
    group: str | None


@dataclass(frozen=True)
class Parameter:
    c_name: str
    reg_name: str
    source_reg_name: str
    source_field_name: str
    address: int
    mask: int
    shift: int
    group: str | None


@dataclass(frozen=True)
class EncodedEnum:
    c_name: str
    parameter_name: str
    source_reg_name: str
    source_field_name: str
    members: tuple[tuple[str, int], ...]


class OgDringExporter:
    def export(
        self,
        node: RootNode | AddrmapNode,
        path: str | Path,
        *,
        guard_prefix: str | None = None,
        param_include: str = "param_comm_services.h",
    ) -> None:
        validate_param_include(param_include)
        top_node = node.top if isinstance(node, RootNode) else node
        output_path = Path(path)
        guard = make_guard(guard_prefix or output_path.name)

        registers, parameters, enums = collect_model(top_node)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            render_header(
                guard=guard,
                param_include=param_include,
                registers=registers,
                parameters=parameters,
                enums=enums,
            ),
            encoding="utf-8",
        )


def export_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    guard_prefix: str | None = None,
    param_include: str = "param_comm_services.h",
) -> None:
    rdlc = RDLCompiler()
    rdlc.compile_file(str(input_path))
    root = rdlc.elaborate()
    OgDringExporter().export(
        root,
        output_path,
        guard_prefix=guard_prefix,
        param_include=param_include,
    )


def collect_model(top_node: AddrmapNode) -> tuple[list[Register], list[Parameter], list[EncodedEnum]]:
    registers: list[Register] = []
    parameters: list[Parameter] = []
    enums: list[EncodedEnum] = []

    for reg in iter_registers(top_node):
        if reg.array_dimensions:
            raise ValueError(
                f"register arrays are not supported: register {reg.inst_name}"
            )
        reg_identifier = generated_identifier(reg.inst_name)
        reg_c_name = f"REG_{reg_identifier}"
        address = int(reg.absolute_address)
        if not C_ENUM_VALUE_MIN <= address <= C_ENUM_VALUE_MAX:
            raise ValueError(
                f"address for register {reg.inst_name} is {address}; supported C enum "
                f"range is {C_ENUM_VALUE_MIN}..{C_ENUM_VALUE_MAX}"
            )
        group = get_optional_property(reg, "doc_group")
        registers.append(Register(reg_c_name, reg.inst_name, address, group))

        for field in reg.fields():
            field_identifier = generated_identifier(field.inst_name)
            field_c_name = f"{reg_identifier}_{field_identifier}"
            mask = ((1 << field.width) - 1) << field.low
            if mask > UINT64_MAX:
                raise ValueError(
                    f"mask for field {reg.inst_name}.{field.inst_name} is "
                    f"{format_hex(mask)}; supported maximum is {format_hex(UINT64_MAX)}"
                )
            parameters.append(
                Parameter(
                    field_c_name,
                    reg_c_name,
                    reg.inst_name,
                    field.inst_name,
                    address,
                    mask,
                    field.low,
                    group,
                )
            )

            encoded = field.get_property("encode")
            if encoded is not None:
                enum_prefix = f"{reg_identifier}_{field_identifier}"
                members = []
                for member_name, member in encoded.members.items():
                    value = int(member.value)
                    if not C_ENUM_VALUE_MIN <= value <= C_ENUM_VALUE_MAX:
                        raise ValueError(
                            f"encoded value for {reg.inst_name}.{field.inst_name} member "
                            f"{member_name} is {value}; supported C enum range is "
                            f"{C_ENUM_VALUE_MIN}..{C_ENUM_VALUE_MAX}"
                        )
                    members.append(
                        (f"{enum_prefix}_{generated_identifier(member_name)}", value)
                    )
                enums.append(
                    EncodedEnum(
                        f"{enum_prefix}_E",
                        field_c_name,
                        reg.inst_name,
                        field.inst_name,
                        tuple(members),
                    )
                )

    if not registers:
        raise ValueError("cannot generate decoder ring: model contains no registers")
    if not parameters:
        raise ValueError("cannot generate decoder ring: model contains no register fields")
    validate_generated_symbols(registers, parameters, enums)
    return registers, parameters, enums


def validate_generated_symbols(
    registers: list[Register],
    parameters: list[Parameter],
    enums: list[EncodedEnum],
) -> None:
    ordinary_symbols = {
        "PARAM_COUNT": "generated parameter count",
        "ParamTable": "generated parameter table",
    }
    tag_symbols = {
        "Registers": "generated register enum",
        "Parameters": "generated parameter enum",
    }

    def add(symbols: dict[str, str], name: str, source: str, namespace: str) -> None:
        previous = symbols.get(name)
        if previous is not None:
            raise ValueError(
                f"generated C {namespace} identifier collision for {name!r}: "
                f"{previous} and {source}"
            )
        symbols[name] = source

    for reg in registers:
        add(ordinary_symbols, reg.c_name, f"register {reg.source_name}", "ordinary")
    for param in parameters:
        add(
            ordinary_symbols,
            param.c_name,
            f"parameter {param.source_reg_name}.{param.source_field_name}",
            "ordinary",
        )
    for enum in enums:
        use = f"{enum.source_reg_name}.{enum.source_field_name}"
        add(tag_symbols, enum.c_name, f"encoded field {use}", "tag")
        for member_name, _ in enum.members:
            add(ordinary_symbols, member_name, f"encoded value in {use}", "ordinary")


def iter_registers(top_node: AddrmapNode) -> Iterable[RegNode]:
    for node in top_node.descendants():
        if isinstance(node, RegNode):
            yield node


def get_optional_property(node: RegNode, name: str) -> str | None:
    try:
        value = node.get_property(name)
    except LookupError:
        return None
    return normalize_comment_text(str(value)) if value else None


def normalize_comment_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value.replace("\\", r"\x5C")).strip()
    return text.replace("??/", "?? /")


def validate_param_include(value: str) -> None:
    if not value or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None:
        raise ValueError(
            "param_include must be a non-empty header name containing only "
            "letters, digits, '/', '.', '_', or '-'"
        )


def render_header(
    *,
    guard: str,
    param_include: str,
    registers: list[Register],
    parameters: list[Parameter],
    enums: list[EncodedEnum],
) -> str:
    lines: list[str] = [
        "/* Generated by peakrdl-og-dring. */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdio.h>",
        "",
        f'#include "{param_include}"',
        "",
        "",
        "enum Registers",
        "{",
    ]

    current_group: str | None = None
    for reg in registers:
        current_group = emit_group_comment(lines, current_group, reg.group)
        lines.append(f"\t{reg.c_name} = {format_hex(reg.address)},")

    lines.extend(["};", "", "enum Parameters", "{"])

    current_group = None
    for param in parameters:
        current_group = emit_group_comment(lines, current_group, param.group)
        lines.append(
            f"\t{param.c_name}, // address: {format_hex(param.address)}, "
            f"mask: {format_hex(param.mask)}, shift: {format_hex(param.shift)}"
        )
    lines.append("")
    lines.extend(["\tPARAM_COUNT", "};", "", "static const ParamComp ParamTable[PARAM_COUNT] =", "{"])

    for param in parameters:
        lines.append(f"\t{{{param.reg_name}, {format_hex(param.mask)}, {format_hex(param.shift)}}},")
    lines.extend(["};", ""])

    for enum in enums:
        lines.extend(
            [
                "",
                f"// Parameter {enum.parameter_name} "
                f"({enum.source_reg_name}.{enum.source_field_name})",
                f"enum {enum.c_name}",
                "{",
            ]
        )
        for member_name, value in enum.members:
            lines.append(f"\t{member_name} = {format_hex(value)},")
        lines.extend(["};", ""])

    lines.extend(["", f"#endif /* {guard} */", ""])
    return "\n".join(lines)


def emit_group_comment(lines: list[str], current_group: str | None, group: str | None) -> str | None:
    if group == current_group:
        return group
    if lines[-1]:
        lines.append("")
    if group:
        lines.append(f"\t// {group}")
    return group


def sanitize_identifier(value: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not ident:
        return "RDL"
    if ident[0].isdigit():
        ident = "RDL_" + ident
    return ident


def generated_identifier(value: str) -> str:
    return sanitize_identifier(value).upper()


def make_guard(value: str) -> str:
    ident = sanitize_identifier(value).upper()
    if ident.endswith("_H_"):
        return ident
    if ident.endswith("_H"):
        return ident + "_"
    return ident + "_H_"


def format_hex(value: int) -> str:
    if value <= 0xFF:
        return f"0x{value:02X}"
    return f"0x{value:X}"
