# PeakRDL OG Decoder Ring

PeakRDL exporter for generating OG decoder-ring C headers from SystemRDL.

## Install

From Git:

```sh
uv add git+ssh://git@github.com/Lomzem/PeakRDL-og-dring.git
# or
pip install git+ssh://git@github.com/Lomzem/PeakRDL-og-dring.git
```

Clone for development:

```sh
git clone git@github.com:Lomzem/PeakRDL-og-dring.git
cd PeakRDL-og-dring
uv sync --extra test
```

Remote:

```sh
git remote -v
# origin  git@github.com:Lomzem/PeakRDL-og-dring.git (fetch)
# origin  git@github.com:Lomzem/PeakRDL-og-dring.git (push)
```

Local setup:

```sh
uv sync --extra test
```

## Command Line

```sh
uv run peakrdl og-dring path/to/input.rdl -o path/to/output.h \
  --guard-prefix MY_DEVICE_PARAM_DRING
```

Options:

- `--guard-prefix NAME`: controls the generated include guard.
- `--include HEADER`: header that provides `ParamComp`; defaults to `param_comm_services.h`.

## Python API

Export directly from an RDL file:

```python
from peakrdl_og_dring import export_file

export_file(
    "path/to/input.rdl",
    "path/to/output.h",
    guard_prefix="MY_DEVICE_PARAM_DRING",
)
```

Export from an already-elaborated SystemRDL node:

```python
from peakrdl_og_dring import OgDringExporter

OgDringExporter().export(top_node, "path/to/output.h")
```

## Output

The generated header contains:

- `enum Registers`
- `enum Parameters`
- `static const ParamComp ParamTable[PARAM_COUNT]`
- C enums for SystemRDL encoded field values

Each `ParamTable` entry maps a parameter to `{register, mask, shift}`.

RDL-derived identifiers are sanitized and converted to uppercase. Register
enumerators use `REG_<REGISTER>`, and parameter enumerators always use
`<REGISTER>_<FIELD>`. Each parameter has a same-line `address`, `mask`, and
`shift` comment in hexadecimal. The `doc_group` property creates section
comments in both `enum Registers` and `enum Parameters`. Group text is kept on
one safe C comment line: whitespace is collapsed and backslashes are shown as
`\x5C`. The line-splicing trigraph `??/` is neutralized as `?? /`.

Each encoded field gets its own enum based on its use site, even when fields
use enum types with the same name. Its tag is `<REGISTER>_<FIELD>_E`, and its
members are `<REGISTER>_<FIELD>_<RDL_VARIANT>`. A comment before the enum starts
with the exact associated `<REGISTER>_<FIELD>` parameter identifier. It also
gives the source `<register>.<field>` use. Generated register, parameter,
enum-tag, and enum-member collisions are reported after identifier sanitization.

Encoded values must be in the supported C `int` range from `0` through
`2147483647`. SystemRDL compiler enum values are nonnegative. The exporter
rejects an encoded member outside this range instead of generating an invalid C
enumerator.

Register addresses use the same `0` through `2147483647` range. Register arrays
are not supported; use scalar registers in the flat production address map.
Generated masks must fit in an unsigned 64-bit C integer constant, from `0`
through `0xFFFFFFFFFFFFFFFF`.

The `param_include` API option accepts non-empty header names made from letters,
digits, `/`, `.`, `_`, and `-`.

These naming changes are a breaking change to the generated C API.

## Test

```sh
uv run pytest -q
```
