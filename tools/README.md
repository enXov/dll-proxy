# Tools

Export extraction utilities for dll-proxy. Since exports are now extracted
at **build time** (see below), the repository does not contain any original
Windows DLL files or generated headers.

## How the build uses this

When you run CMake, the following happens automatically:

```
1. cmake -B build -DDLL_TYPE=winmm.dll -DPROXY_METHOD=linker
2. CMake runs:  python tools/extract_exports.py winmm.dll -o build/exports
   (source: the build machine's own System32, located via GLOBALROOT\SystemRoot)
3. Generated headers are published as build/exports/proxy_exports*.h
4. main.cpp includes them; the MSVC linker applies the pragma forwarding
5. Output: build/Release/winmm.dll
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

# From an explicit DLL file (any location - works on any OS)
python tools/extract_exports.py X:\copy\of\version.dll --runtime
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
  --runtime             Also generate runtime forwarding files (.h + .asm)
  --no-ordinals         Disable ordinals (breaks ordinal-based imports)
  -h, --help            Show help message
```

## Generated output

The script generates files named after the DLL itself (e.g. `winmm`):
- `winmm.h` - linker forwarding header (MSVC pragma forwarding via GLOBALROOT path)
- `winmm_runtime.h` - LoadLibrary + GetProcAddress function pointer resolution
- `winmm_runtime.asm` - MASM x64 jump thunks for every exported function

Only the linker header is needed for `-DPROXY_METHOD=linker` (default);
all three are generated for `-DPROXY_METHOD=runtime`.

## Notes

- **System32 sourcing requires Windows** (GitHub Actions runner or local
  Windows machine). Explicit file paths work anywhere.
- x64 only: non-x64 DLLs are rejected with a clear error (this also catches
  32-bit Python resolving System32 to SysWOW64).
- Ordinals are preserved automatically, including ordinal-only (NONAME)
  exports and non-1 ordinal bases (e.g. winmm.dll starts at ordinal 2).
- Overall exports are read from the *build machine's* system files: builds
  on a Windows runner use pristine Microsoft binaries, while building on a
  custom-release ISO machine bakes in exactly that ISO's export surface.

## References

- [Perfect DLL Proxy](https://github.com/mrexodia/perfect-dll-proxy) - Pragma forwarding technique
- [pefile Documentation](https://github.com/erocarrera/pefile) - Python PE parser
- [Microsoft PE Format](https://docs.microsoft.com/en-us/windows/win32/debug/pe-format) - Official documentation
