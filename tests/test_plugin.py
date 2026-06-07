from __future__ import annotations

import sysconfig
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from hatch_zig.hooks import hatch_register_build_hook
from hatch_zig.plugin import ZigBuildHook, _zig_command, _zig_target_args


def make_hook(root: Path, config: dict[str, Any], target_name: str = "wheel") -> ZigBuildHook:
    return ZigBuildHook(
        str(root),
        config,
        None,
        None,
        str(root),
        target_name,
    )


def test_entry_point_registers_hook() -> None:
    assert hatch_register_build_hook() is ZigBuildHook
    assert ZigBuildHook.PLUGIN_NAME == "zig"


def test_package_required(tmp_path: Path) -> None:
    hook = make_hook(tmp_path, {})
    with pytest.raises(ValueError, match="requires `package`"):
        _ = hook._package


def test_optimize_default_and_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = make_hook(tmp_path, {"package": "foo"})
    monkeypatch.delenv("HATCH_ZIG_BUILD_MODE", raising=False)
    assert hook._optimize == "ReleaseFast"

    hook = make_hook(tmp_path, {"package": "foo", "optimize": "ReleaseSafe"})
    assert hook._optimize == "ReleaseSafe"

    monkeypatch.setenv("HATCH_ZIG_BUILD_MODE", "Debug")
    assert hook._optimize == "Debug"


def test_initialize_skips_non_wheel(tmp_path: Path) -> None:
    hook = make_hook(tmp_path, {"package": "foo"}, target_name="sdist")
    build_data: dict[str, Any] = {"artifacts": []}
    with mock.patch("hatch_zig.plugin.subprocess.run") as run:
        hook.initialize("1.0", build_data)
    run.assert_not_called()
    assert build_data == {"artifacts": []}


def test_initialize_builds_and_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    (tmp_path / "foo").mkdir()
    artifact = tmp_path / "foo" / f"_foo{ext_suffix}"
    monkeypatch.delenv("ARCHFLAGS", raising=False)

    hook = make_hook(tmp_path, {"package": "foo"})
    build_data: dict[str, Any] = {"artifacts": []}

    def fake_run(cmd: list[str], **kwargs: Any) -> None:
        artifact.write_bytes(b"")
        assert "-Doptimize=ReleaseFast" in cmd
        assert kwargs["env"]["HATCH_ZIG_PYTHON_INCLUDE"]
        assert kwargs["env"]["HATCH_ZIG_EXT_SUFFIX"] == ext_suffix

    with mock.patch("hatch_zig.plugin._zig_command", return_value=["zig"]):
        with mock.patch("hatch_zig.plugin.subprocess.run", side_effect=fake_run):
            hook.initialize("1.0", build_data)

    assert build_data["pure_python"] is False
    assert build_data["infer_tag"] is True
    assert f"foo/_foo{ext_suffix}" in build_data["artifacts"]


def test_initialize_missing_artifact(tmp_path: Path) -> None:
    hook = make_hook(tmp_path, {"package": "foo"})
    with mock.patch("hatch_zig.plugin._zig_command", return_value=["zig"]):
        with mock.patch("hatch_zig.plugin.subprocess.run"):
            with pytest.raises(RuntimeError, match="did not produce"):
                hook.initialize("1.0", {"artifacts": []})


def test_initialize_missing_interpreter_paths(tmp_path: Path) -> None:
    hook = make_hook(tmp_path, {"package": "foo"})
    with mock.patch("hatch_zig.plugin.sysconfig.get_path", return_value=None):
        with pytest.raises(RuntimeError, match="platinclude"):
            hook.initialize("1.0", {"artifacts": []})


def test_clean_removes_extensions(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    so = tmp_path / "foo" / "_foo.cpython-312-darwin.so"
    pyd = tmp_path / "foo" / "_foo.cp312-win_amd64.pyd"
    so.write_bytes(b"")
    pyd.write_bytes(b"")

    hook = make_hook(tmp_path, {"package": "foo"})
    hook.clean(["1.0"])

    assert not so.exists()
    assert not pyd.exists()


def test_zig_command_prefers_path() -> None:
    with mock.patch("hatch_zig.plugin.shutil.which", return_value="/usr/bin/zig"):
        assert _zig_command() == ["zig"]


def test_zig_command_falls_back_to_ziglang() -> None:
    with mock.patch("hatch_zig.plugin.shutil.which", return_value=None):
        with mock.patch.dict("sys.modules", {"ziglang": mock.Mock()}):
            assert _zig_command()[1:] == ["-m", "ziglang"]


def test_zig_command_missing_toolchain() -> None:
    with mock.patch("hatch_zig.plugin.shutil.which", return_value=None):
        with mock.patch.dict("sys.modules", {"ziglang": None}):
            with pytest.raises(RuntimeError, match="Zig toolchain not found"):
                _zig_command()


def test_zig_target_args_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHFLAGS", "-arch arm64")
    monkeypatch.setattr("hatch_zig.plugin.sys.platform", "linux")
    assert _zig_target_args() == []


def test_zig_target_args_no_single_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hatch_zig.plugin.sys.platform", "darwin")
    monkeypatch.setenv("ARCHFLAGS", "-arch arm64 -arch x86_64")
    assert _zig_target_args() == []


def test_zig_target_args_unknown_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hatch_zig.plugin.sys.platform", "darwin")
    monkeypatch.setenv("ARCHFLAGS", "-arch ppc64")
    assert _zig_target_args() == []


def test_zig_target_args_with_min_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hatch_zig.plugin.sys.platform", "darwin")
    monkeypatch.setenv("ARCHFLAGS", "-arch x86_64")
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "11.0")
    assert _zig_target_args() == ["-Dtarget=x86_64-macos.11.0"]


def test_zig_target_args_without_min_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hatch_zig.plugin.sys.platform", "darwin")
    monkeypatch.setenv("ARCHFLAGS", "-arch arm64")
    monkeypatch.delenv("MACOSX_DEPLOYMENT_TARGET", raising=False)
    assert _zig_target_args() == ["-Dtarget=aarch64-macos"]
