from typing import TYPE_CHECKING

from peakrdl.plugins.exporter import ExporterSubcommandPlugin

from .exporter import OgDringExporter

if TYPE_CHECKING:
    import argparse
    from systemrdl.node import AddrmapNode


class Exporter(ExporterSubcommandPlugin):
    short_desc = "Generate a legacy OG decoder ring C header"
    long_desc = """
    Generate a C header containing register identifiers, parameter identifiers,
    a ParamComp table, and encoded SystemRDL enums.
    """

    def add_exporter_arguments(self, arg_group: "argparse._ActionsContainer") -> None:
        arg_group.add_argument(
            "--guard-prefix",
            default=None,
            help="Prefix to use for the generated include guard.",
        )
        arg_group.add_argument(
            "--include",
            default="param_comm_services.h",
            help="Header that provides ParamComp. [param_comm_services.h]",
        )

    def do_export(self, top_node: "AddrmapNode", options: "argparse.Namespace") -> None:
        OgDringExporter().export(
            top_node,
            path=options.output,
            guard_prefix=options.guard_prefix,
            param_include=options.include,
        )
