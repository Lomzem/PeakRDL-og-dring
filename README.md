# PeakRDL OG Decoder Ring

This PeakRDL exporter makes a C decoder-ring header from SystemRDL.

## Install

Add the exporter to your project:

```sh
uv add git+ssh://git@github.com/Lomzem/PeakRDL-og-dring.git
```

## Command Line

Run the exporter in your project:

```sh
uv run peakrdl og-dring input.rdl -o output.h
```

Run the exporter without installation:

```sh
uv run --with git+ssh://git@github.com/Lomzem/PeakRDL-og-dring.git \
  peakrdl og-dring input.rdl -o output.h
```

Options:

- `--guard-prefix NAME`: Sets the include guard. If you do not set it, the exporter uses the output file name.
- `--include HEADER`: Sets the header that has `ParamComp`. The default is `param_comm_services.h`.

## Python API

```python
from peakrdl_og_dring import export_file

export_file("input.rdl", "output.h", guard_prefix="MY_DEVICE")
```

## Output

The header has these items:

- `enum Registers`: One `REG_<REGISTER>` item for each register.
- `enum Parameters`: One `<REGISTER>_<FIELD>` item for each field.
- `ParamTable`: One `{register, mask, shift}` entry for each parameter.
- One C enum for each encoded field.

## Limits

- Register addresses and enum values must be in the range `0` to `2147483647`.
- Register arrays are not supported.
- If two names are the same after conversion, the export stops with an error.

## Test

```sh
uv run --with pytest pytest -q
```
