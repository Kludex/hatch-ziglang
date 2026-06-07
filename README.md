# hatch-ziglang

A [Hatch](https://hatch.pypa.io/) build hook that compiles a [Zig](https://ziglang.org/) extension
into the wheel, against the building interpreter, with no out-of-band step.

`uv build` / `pip wheel` / cibuildwheel produce a correct, platform-tagged wheel: the `.so` is built
during the wheel build against `sys.executable`, and your `build.zig` installs it into the package as
`_<package><EXT_SUFFIX>`.

## Usage

Add the build requirement and configure the hook in `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling", "hatch-ziglang", "ziglang==0.16.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel.hooks.zig]
package = "yourpkg"
optimize = "ReleaseFast"  # optional; Zig -Doptimize mode (default ReleaseFast)
```

| key        | required | description                                                                |
| ---------- | -------- | -------------------------------------------------------------------------- |
| `package`  | yes      | the import package directory; artifact is `<package>/_<package><EXT_SUFFIX>` |
| `optimize` | no       | Zig `-Doptimize` mode (default `ReleaseFast`)                               |

`HATCH_ZIG_BUILD_MODE` overrides `optimize` at build time.

## What `build.zig` receives

The hook runs `zig build -Doptimize=<mode> [-Dtarget=...]` and passes the interpreter paths through
two environment variables your `build.zig` reads:

- `HATCH_ZIG_PYTHON_INCLUDE` - the building interpreter's `platinclude`
- `HATCH_ZIG_EXT_SUFFIX` - the building interpreter's `EXT_SUFFIX` (e.g. `.cpython-312-darwin.so`)

On Windows it also passes the import library so the `.pyd` can link `pythonXY.lib`:

- `HATCH_ZIG_PYTHON_LIBDIR` - the `libs` directory under `sys.base_prefix`
- `HATCH_ZIG_PYTHON_LIB` - the bare lib name (e.g. `python314`, `python314t` for free-threaded)

On macOS under cibuildwheel, the hook reads `ARCHFLAGS` and `MACOSX_DEPLOYMENT_TARGET` to emit a
matching `-Dtarget=<arch>-macos[.<min>]`, so the compiled `.so` and the wheel tag agree and delocate
accepts the repaired wheel.

Zig is resolved from a `zig` on `PATH`, falling back to the `ziglang` pip package (`python -m ziglang`),
which works inside cibuildwheel's manylinux containers.
