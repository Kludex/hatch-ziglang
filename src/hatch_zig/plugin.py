from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# cibuildwheel builds every macOS wheel on the arm64 runner and asks for a
# specific arch through ARCHFLAGS; translate it into a Zig cross-compile target
# so the produced `.so` matches the wheel tag delocate enforces.
_MACOS_ZIG_ARCH = {"arm64": "aarch64-macos", "x86_64": "x86_64-macos"}


def _zig_target_args() -> list[str]:
    archflags = os.environ.get("ARCHFLAGS", "")
    arches = archflags.split()[1::2]  # "-arch x86_64 -arch arm64" -> ["x86_64", "arm64"]
    if len(arches) != 1 or sys.platform != "darwin":
        return []
    arch = _MACOS_ZIG_ARCH.get(arches[0])
    if not arch:
        return []
    # Pin the binary's minimum macOS to MACOSX_DEPLOYMENT_TARGET (set by
    # cibuildwheel) so the wheel tag and the `.so`'s required OS version agree
    # and delocate accepts the repaired wheel.
    min_version = os.environ.get("MACOSX_DEPLOYMENT_TARGET")
    target = f"{arch}.{min_version}" if min_version else arch
    return [f"-Dtarget={target}"]


def _zig_command() -> list[str]:
    """Resolve how to invoke Zig: a `zig` on PATH, else the `ziglang` pip package.

    The pip fallback (`python -m ziglang`) works identically on the host and inside
    cibuildwheel's manylinux containers, where a host-installed `zig` isn't visible.
    """
    if shutil.which("zig"):
        return ["zig"]
    try:
        import ziglang  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Zig toolchain not found: install Zig and put it on PATH, or `pip install ziglang`."
        ) from None
    return [sys.executable, "-m", "ziglang"]


class ZigBuildHook(BuildHookInterface[Any]):
    """Compile a Zig extension against the building interpreter during the wheel build.

    This makes `uv build` / `pip wheel` / cibuildwheel produce a correct, platform-tagged
    wheel with no out-of-band step: the `.so` is built here, against `sys.executable`, and
    `build.zig` installs it into `<package>/` as `_<package><EXT_SUFFIX>`.

    Configured in `[tool.hatch.build.targets.wheel.hooks.zig]`:

        package   the import package directory; the artifact is `<package>/_<package><EXT_SUFFIX>`
        optimize  Zig `-Doptimize` mode (default ReleaseFast); overridable via HATCH_ZIG_BUILD_MODE

    `build.zig` receives the interpreter paths through `HATCH_ZIG_PYTHON_INCLUDE` and
    `HATCH_ZIG_EXT_SUFFIX`.
    """

    PLUGIN_NAME = "zig"

    @property
    def _package(self) -> str:
        package = self.config.get("package")
        if not package:
            raise ValueError("hatch-zig requires `package` in [tool.hatch.build.targets.wheel.hooks.zig]")
        return str(package)

    @property
    def _optimize(self) -> str:
        return os.environ.get("HATCH_ZIG_BUILD_MODE", str(self.config.get("optimize", "ReleaseFast")))

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        include = sysconfig.get_path("platinclude")
        ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
        if not include or not ext_suffix:
            raise RuntimeError("could not resolve platinclude / EXT_SUFFIX from the building interpreter")

        env = {**os.environ, "HATCH_ZIG_PYTHON_INCLUDE": include, "HATCH_ZIG_EXT_SUFFIX": ext_suffix}
        subprocess.run(
            [*_zig_command(), "build", f"-Doptimize={self._optimize}", *_zig_target_args()],
            cwd=root,
            env=env,
            check=True,
        )

        artifact = f"{self._package}/_{self._package}{ext_suffix}"
        if not (root / artifact).exists():
            raise RuntimeError(f"zig build did not produce {artifact}")

        # Tag the wheel for this interpreter + platform rather than py3-none-any.
        build_data["pure_python"] = False
        build_data["infer_tag"] = True
        build_data["artifacts"].append(artifact)

    def clean(self, versions: list[str]) -> None:
        root = Path(self.root)
        for suffix in ("so", "pyd"):
            for path in root.glob(f"{self._package}/_{self._package}*.{suffix}"):
                path.unlink()
        print(f"removed compiled extensions; building Zig core via {sys.executable}", file=sys.stderr)
