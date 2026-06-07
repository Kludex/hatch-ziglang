from __future__ import annotations

from hatchling.plugin import hookimpl

from hatch_zig.plugin import ZigBuildHook


@hookimpl
def hatch_register_build_hook() -> type[ZigBuildHook]:
    return ZigBuildHook
