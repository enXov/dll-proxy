# Tools

Export extraction utilities for dll-proxy. Since exports are now extracted
at **build time** (see below), the repository does not contain any original
Windows DLL files or generated headers.

## How the build uses this

When you run CMake, the following happens automatically:

```
1. cmake -B build -DDLL_SOURCE=<path to the system DLL> [toolchain flags]
2. CMake runs:  python tools/extract_exports.py <the same file> -o build/exports
   (the DLL's file name is what the proxy stands in for at runtime)
3. Generated files are published under fixed names in build/exports/
   (proxy_exports.h for MSVC, proxy_exports.def for MinGW-w64)
4. main.cpp is built; the linker applies the forwarding
   (MSVC pragmas inside the header, or the .def on the link line)
5. Output: <that file name>.dll
```

Because the DLL is just a file path, **adding a new DLL type requires zero
code changes**. Any x64 DLL with an export directory works, e.g.:
`version.dll`, `winmm.dll`, `winhttp.dll`, `wininet.dll`, `wintrust.dll`,
`xinput1_3.dll`, ...

**Where the generated files land:** the CMake build directory
(`build/exports/`), never the source tree. They are regenerated on every
configure and the build directory can be deleted freely.

## Manual usage

The same script can be run by hand (useful for debugging or pre-checking):

```bash
pip install -r requirements.txt

# From an explicit DLL file (it is the target module at runtime too)
python tools/extract_exports.py C:\Windows\System32\winmm.dll

# Also generate runtime forwarding files (.h + .asm)
python tools/extract_exports.py C:\Windows\System32\winmm.dll --runtime

# Generate a GNU ld .def file for MinGW-w64 builds (instead of the
# MSVC pragma header). Same GLOBALROOT path, same forwarders.
python tools/extract_exports.py C:\Windows\System32\winmm.dll --def

# Any explicit DLL file works (any location, any OS)
python tools/extract_exports.py /path/to/copy/of/version.dll --def
```

This prints the export summary and writes the generated files to the
requested output directory.

## Script options

```
Usage: extract_exports.py [OPTIONS] [DLL]

Arguments:
  DLL                   Path to the DLL file to extract exports from

Options:
  -o, --output DIR      Output directory for generated files
  -q, --quiet           Suppress detailed output
  --runtime             Also generate runtime forwarding files
                        (.h + .asm for MSVC, .h + .def when paired with --def)
  --def                 Generate GNU ld .def output (MinGW-w64)
  --no-ordinals         Disable ordinals (breaks ordinal-based imports)
  -h, --help            Show help message
```

## Generated output

The script generates files named after the DLL itself (e.g. `winmm`):
- `winmm.h` - linker forwarding header (MSVC pragma forwarding via GLOBALROOT path)
- `winmm.def` - GNU ld forwarding file (MinGW-w64 linker method, generated with `--def`)
- `winmm_runtime.h` - LoadLibrary + GetProcAddress function pointer resolution
- `winmm_runtime.asm` - MASM x64 thunks (MSVC runtime builds)
- `winmm_runtime.def` - GNU ld thunk export mapping (MinGW-w64 runtime builds,
  generated with `--def --runtime`; the runtime header then contains native GNU
  thunks instead of being MASM-dependent)

With `--def --runtime` together, MinGW-w64 runtime builds get exactly the
runtime header + runtime def pair; no MSVC-only files are generated.

## Notes

- The source file can be any x64 DLL anywhere on disk; the proxy is named
  after it (CMake derives everything from `DLL_SOURCE`).
- x64 only: non-x64 DLLs are rejected with a clear error.
- Ordinals are preserved automatically, including ordinal-only (NONAME)
  exports and non-1 ordinal bases (e.g. winmm.dll starts at ordinal 2).
- Exports are read only from the file you pass, so builds always reflect
  exactly that file's export surface.

## References

- [Perfect DLL Proxy](https://github.com/mrexodia/perfect-dll-proxy) - Pragma forwarding technique
- [pefile Documentation](https://github.com/erocarrera/pefile) - Python PE parser
- [Microsoft PE Format](https://docs.microsoft.com/en-us/windows/win32/debug/pe-format) - Official documentation
