# Original DLLs Directory

This directory contains original Windows DLL files used for export extraction and proxy generation.

## Quick Start

### Extract Exports from a DLL

```bash
# Extract exports from version.dll (with ordinals - recommended)
python extract_exports.py version.dll

# Extract exports from all DLLs in this directory
python extract_exports.py -a

# Extract without ordinals (edge cases only - breaks ordinal-based imports)
python extract_exports.py version.dll --no-ordinals
```

The script will automatically generate a header file in `../src/exports/` ready for use with CMake.

## Requirements

Install the required Python package:

```bash
pip install pefile
```

## How to Add a New DLL

Follow these steps to add support for a new DLL:

### Step 1: Obtain the Original DLL

Copy the original Windows DLL to this directory:

```bash
# Example: Copy winmm.dll from System32
cp /mnt/c/Windows/System32/winmm.dll ./original_dlls/

# On Windows PowerShell:
# Copy-Item C:\Windows\System32\winmm.dll .\original_dlls\
```

**Common DLL Locations:**
- `C:\Windows\System32\` - 64-bit system DLLs

### Step 2: Extract Exports

Run the extraction script on your DLL:

```bash
python extract_exports.py winmm.dll
```

This will:
1. Parse the DLL and extract all exported functions
2. Auto-detect export types (regular, COM/PRIVATE, ordinal-only)
3. Generate a header file with MSVC pragma forwarding directives using GLOBALROOT paths
4. Save it to `../src/exports/winmm.h`

### Step 3: Verify Exports with objdump (Linux)

If you're on Linux, you can verify the extraction was correct using `objdump`:

```bash
# View export summary
objdump -p winmm.dll | grep -A10 "Export"

# This shows:
# - Ordinal Base: Starting ordinal number (e.g., 1 or 2)
# - Export Address Table: Total number of exports (hex)
# - Name Pointer Table: Number of named exports (hex)
# - Difference = ordinal-only exports (no name)
```

**Example output for winmm.dll:**
```
Ordinal Base                2
Export Address Table        000000b5  (181 exports)
[Name Pointer/Ordinal] Table 000000b4  (180 named)
```

This confirms: 181 total - 180 named = 1 ordinal-only export (ordinal 2)

**View specific exports:**
```bash
# Show named exports with ordinals
objdump -p winmm.dll | sed -n '/\[Ordinal\/Name Pointer\]/,/^$/p' | head -20
```

**Key things to verify:**
- ✅ Export count matches what extract_exports.py reported
- ✅ Ordinal base is correct (DLLs can start at any ordinal, not just 1)
- ✅ Named exports + ordinal-only exports = total exports
- ✅ No missing ordinals in the range (gaps are normal)

### Step 4: Verify Generated Header

Check the generated header file:

```bash
cat ../src/exports/winmm.h
```

You should see macro-based exports with GLOBALROOT paths:

```cpp
// Original DLL path (GLOBALROOT for maximum compatibility)
#define ORIGINAL_DLL "\\\\.\\GLOBALROOT\\SystemRoot\\System32\\winmm.dll"

// Export forwarding macros
#define MAKE_EXPORT(name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",@" #ordinal))

// Regular exports
MAKE_EXPORT(PlaySoundA, 1)
MAKE_EXPORT(PlaySoundW, 2)
// ... more exports
```

### Step 5: Update CMakeLists.txt

Add support for your new DLL in `../CMakeLists.txt`:

```cmake
elseif(DLL_TYPE STREQUAL "winmm")
    set(EXPORT_HEADER "exports/winmm.h")
    set(OUTPUT_NAME "winmm")
```

### Step 6: Build and Test

Build your proxy DLL:

```bash
cd ..
mkdir build && cd build
cmake -DDLL_TYPE=winmm ..
cmake --build . --config Release
```

Output: `build/Release/winmm.dll`

### Step 7: Test the Proxy

1. Find an application that uses your target DLL
2. Place your proxy DLL in the application directory
3. Run the application and verify:
   - Your payload executes (e.g., MessageBox appears)
   - Application functions normally

## Usage Examples

### List Available DLLs

```bash
python extract_exports.py --list
```

### Extract Single DLL

```bash
python extract_exports.py version.dll
```

### Extract All DLLs

```bash
python extract_exports.py -a
```

### Quiet Mode

```bash
python extract_exports.py version.dll -q
```

### Custom Output Directory

```bash
python extract_exports.py version.dll -o /custom/path/
```

### Without Ordinals (Edge Cases Only)

```bash
# Not recommended - breaks programs that import by ordinal number
python extract_exports.py version.dll --no-ordinals
```

**When to use `--no-ordinals`:**
- DLL version mismatches between Windows versions
- Debugging import issues
- **Warning:** This breaks programs that import functions by ordinal number!

## Script Options

```
Usage: extract_exports.py [OPTIONS] [DLL_FILE]

Arguments:
  DLL_FILE              DLL filename to process (e.g., version.dll)

Options:
  -a, --all             Process all DLL files in directory
  -o, --output DIR      Custom output directory for headers
  -q, --quiet           Suppress detailed output
  --list                List all available DLL files
  --no-ordinals         Disable ordinals (not recommended, breaks ordinal-based imports)
  -h, --help            Show help message
```

## Export Types

The script automatically detects and handles three types of exports:

### 1. Regular Exports (Most Common)
Named functions with ordinals:
```cpp
MAKE_EXPORT(GetFileVersionInfoA, 1)
// Generates: /EXPORT:GetFileVersionInfoA=...dll.GetFileVersionInfoA,@1
```

### 2. COM/PRIVATE Exports
COM functions with PRIVATE flag (not in import library):
```cpp
MAKE_EXPORT_PRIVATE(DllGetClassObject, 5)
// Generates: /EXPORT:DllGetClassObject=...dll.DllGetClassObject,@5,PRIVATE
```

**Auto-detected COM functions:**
- `DllCanUnloadNow`
- `DllGetClassObject`
- `DllInstall`
- `DllRegisterServer`
- `DllUnregisterServer`

### 3. Ordinal-Only Exports
Exports with no name, only ordinal number:
```cpp
MAKE_EXPORT_ORDINAL(__proxy123, 123)
// Generates: /EXPORT:__proxy123=...dll.#123,@123,NONAME
```

Common in: `ws2_32.dll`, `kernel32.dll` (legacy exports)

## Troubleshooting

### "pefile module not found"

Install the required package:

```bash
pip install pefile
```

### "File not found"

Ensure the DLL file is in the `original_dlls/` directory:

```bash
ls *.dll
```

### "No export directory"

The DLL might not export any functions. Verify with:

```bash
# On Windows with Visual Studio installed
dumpbin /exports your_dll.dll

# Or use Dependencies.exe (modern alternative)
```

### "Not a valid PE file"

Ensure you copied a valid Windows DLL file (not a shortcut or corrupted file).

## Output Format

The generated header includes:

1. **File header** with metadata (export count, ordinal status, DLL path)
2. **GLOBALROOT path definition** for maximum compatibility
3. **Three export macros** (MAKE_EXPORT, MAKE_EXPORT_PRIVATE, MAKE_EXPORT_ORDINAL)
4. **Categorized exports** (regular, COM/PRIVATE, ordinal-only)
5. **Header guards** to prevent multiple inclusion

Example output structure:

```cpp
#pragma once
/*
 * Auto-generated export forwarding header for version.dll
 * Generated by extract_exports.py
 * Inspired by Perfect DLL Proxy (https://github.com/mrexodia/perfect-dll-proxy)
 * 
 * Total Exports: 17 (with ordinals)
 * Original DLL Path: \\.\GLOBALROOT\SystemRoot\System32\version.dll
 * Architecture: x64 only
 */

#ifndef VERSION_EXPORTS_H
#define VERSION_EXPORTS_H

// Original DLL path (GLOBALROOT for maximum compatibility)
#define ORIGINAL_DLL "\\\\.\\GLOBALROOT\\SystemRoot\\System32\\version.dll"

// Export forwarding macros (like Perfect DLL Proxy)

// Regular export: Named function with ordinal
#define MAKE_EXPORT(name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",@" #ordinal))

// COM export: Named function with PRIVATE flag (not in import library)
#define MAKE_EXPORT_PRIVATE(name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",@" #ordinal ",PRIVATE"))

// Ordinal-only export: No name, only ordinal number with NONAME flag
#define MAKE_EXPORT_ORDINAL(proxy_name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #proxy_name "=" ORIGINAL_DLL ".#" #ordinal ",@" #ordinal ",NONAME"))

// Regular exports
MAKE_EXPORT(GetFileVersionInfoA, 1)
MAKE_EXPORT(GetFileVersionInfoByHandle, 2)
// ... more exports ...

#endif // VERSION_EXPORTS_H
```

## Advanced Usage

### Why GLOBALROOT Paths?

The script uses GLOBALROOT paths instead of traditional `C:\Windows\System32\`:

```cpp
// Traditional path (less compatible)
C:\\Windows\\System32\\version.dll

// GLOBALROOT path (maximum compatibility)
\\\\.\\GLOBALROOT\\SystemRoot\\System32\\version.dll
```

**Benefits:**
- Works regardless of Windows installation directory
- NT kernel-level path resolution
- More robust across different Windows configurations
- Inspired by Perfect DLL Proxy

### Why Ordinals Matter

Programs can import DLL functions in two ways:

**By name (most common):**
```cpp
GetProcAddress(hDll, "GetFileVersionInfoA");  // Uses function name
```

**By ordinal (less common, but exists):**
```cpp
GetProcAddress(hDll, MAKEINTRESOURCE(1));  // Uses ordinal number
```

**With ordinals (`@1`):** ✅ Works with both import methods  
**Without ordinals:** ❌ Breaks programs that import by ordinal

**When to disable ordinals:**
- DLL version mismatches between Windows versions
- Debugging import issues
- **99% of the time, keep ordinals enabled!**

### Custom Original DLL Path

If you need to forward to a DLL at a custom location, edit the generated header's `ORIGINAL_DLL` definition:

```cpp
// Instead of:
#define ORIGINAL_DLL "\\\\.\\GLOBALROOT\\SystemRoot\\System32\\version.dll"

// Use:
#define ORIGINAL_DLL "C:\\Custom\\Path\\version.dll"
```

### Handling DLL Name Conflicts

If you have multiple versions of a DLL, rename them:

```bash
# Rename for clarity
mv version.dll version_win10.dll
mv version.dll version_win11.dll
```

Then extract separately:

```bash
python extract_exports.py version_win10.dll
python extract_exports.py version_win11.dll
```

## Integration with dll-proxy Workflow

This directory is part of the complete dll-proxy workflow:

```
1. Add DLL to original_dlls/
2. Run extract_exports.py
3. Header generated in src/exports/
4. Update CMakeLists.txt
5. Build with cmake -DDLL_TYPE=<name>
6. Test proxy DLL
```

## References

- [Perfect DLL Proxy](https://github.com/mrexodia/perfect-dll-proxy) - Pragma forwarding technique
- [pefile Documentation](https://github.com/erocarrera/pefile) - Python PE parser
- [Microsoft PE Format](https://docs.microsoft.com/en-us/windows/win32/debug/pe-format) - Official documentation

## Contributing

If you add support for new DLLs:

1. Test thoroughly with real applications
2. Document any quirks or special handling
3. Update this README with your findings
4. Share your results!

