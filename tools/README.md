# Tools

Export extraction utilities for dll-proxy. Since exports are now extracted
at **build time** (see below), the repository does not contain any original
Windows DLL files or generated headers.

## How the build uses this

When you run CMake, the following happens automatically:

```
1. cmake -B build -DDLL_TYPE=winmm.dll [toolchain flags - see the repo README]
2. CMake runs:  python tools/extract_exports.py winmm.dll -o build/exports
   (source: the build machine's own System32 via GLOBALROOT\SystemRoot,
   or DLL_SOURCE on Linux cross-builds)
3. Generated files are published under fixed names in build/exports/
   (proxy_exports.h for MSVC, proxy_exports.def for MinGW-w64)
4. main.cpp is built; the linker applies the forwarding
   (MSVC pragmas inside the header, or the .def on the link line)
5. Output: winmm.dll
```

Because the DLL name is just a string, **adding a new DLL type requires zero
code changes**. Any x64 DLL installed in System32 works, e.g.:
`version.dll`, `winmm.dll`, `winhttp.dll`, `wininet.dll`, `wintrust.dll`,
`xinput1_3.dll`, ...

**Where the generated files land:** the CMake build directory
(`build/exports/`), never the source tree. They are regenerated on every
configure and the build directory can be deleted freely.

## Manual usage

The same script can be run by hand (useful for debugging or pre-checking):

```bash
pip install -r requirements.txt

# From the build machine's system files (System32 -> GLOBALROOT\SystemRoot)
python tools/extract_exports.py winmm.dll

# Also generate runtime forwarding files (.h + .asm)
python tools/extract_exports.py winmm.dll --runtime

# Generate a GNU ld .def file for MinGW-w64 cross builds (instead of the
# MSVC pragma header). Same GLOBALROOT path, same forwarders.
python tools/extract_exports.py winmm.dll --def

# From an explicit DLL file (any location - works on any OS)
python tools/extract_exports.py X:\copy\of\version.dll --def
```

This prints the export summary and writes the generated files to the
requested output directory.

## Script options

```
Usage: extract_exports.py [OPTIONS] [DLL]

Arguments:
  DLL                   System DLL file name (e.g. winmm.dll -> system files)
                        or an explicit DLL file path

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

- **System32 sourcing requires a Windows machine**; explicit file paths
  work anywhere (Linux cross-builds pass `DLL_SOURCE` to CMake).
- x64 only: non-x64 DLLs are rejected with a clear error (this also catches
  32-bit Python resolving System32 to SysWOW64).
- Ordinals are preserved automatically, including ordinal-only (NONAME)
  exports and non-1 ordinal bases (e.g. winmm.dll starts at ordinal 2).
- Overall exports are read from the DLL used as source (the build machine's
  system files on Windows, or `DLL_SOURCE` elsewhere) - builds always reflect
  the export surface of whatever source was used.

## References

- [Perfect DLL Proxy](https://github.com/mrexodia/perfect-dll-proxy) - Pragma forwarding technique
- [pefile Documentation](https://github.com/erocarrera/pefile) - Python PE parser
- [Microsoft PE Format](https://docs.microsoft.com/en-us/windows/win32/debug/pe-format) - Official documentation
