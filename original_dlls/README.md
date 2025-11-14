# Original DLLs Directory

This directory contains original Windows DLL files used for export extraction and proxy generation.

## Quick Start

### Extract Exports from a DLL

```bash
# Extract exports from version.dll
python extract_exports.py version.dll

# Extract exports from all DLLs in this directory
python extract_exports.py -a
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
- `C:\Windows\SysWOW64\` - 32-bit system DLLs (on 64-bit Windows)

### Step 2: Extract Exports

Run the extraction script on your DLL:

```bash
python extract_exports.py winmm.dll
```

This will:
1. Parse the DLL and extract all exported functions
2. Generate a header file with MSVC pragma forwarding directives
3. Save it to `../src/exports/winmm.h`

### Step 3: Verify Generated Header

Check the generated header file:

```bash
cat ../src/exports/winmm.h
```

You should see pragma directives like:

```cpp
#pragma comment(linker, "/EXPORT:FunctionName=C:\\Windows\\System32\\winmm.dll.FunctionName,@1")
```

### Step 4: Update CMakeLists.txt

Add support for your new DLL in `../CMakeLists.txt`:

```cmake
elseif(DLL_TYPE STREQUAL "winmm")
    set(EXPORT_HEADER "exports/winmm.h")
    set(OUTPUT_NAME "winmm")
```

### Step 5: Build and Test

Build your proxy DLL:

```bash
cd ..
mkdir build && cd build
cmake -DDLL_TYPE=winmm ..
cmake --build . --config Release
```

Output: `build/Release/winmm.dll`

### Step 6: Test the Proxy

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

## Common Target DLLs

Here are commonly hijackable Windows DLLs for research:

| DLL Name | Description | Common Usage |
|----------|-------------|--------------|
| `version.dll` | File version info API | Many applications |
| `winmm.dll` | Windows Multimedia API | Games, audio apps |
| `winhttp.dll` | HTTP services | Network applications |
| `wininet.dll` | Internet API | Web browsers, downloaders |
| `xinput1_3.dll` | Xbox controller input | Games |
| `d3d9.dll` | Direct3D 9 | Games |
| `d3d11.dll` | Direct3D 11 | Modern games |
| `dwmapi.dll` | Desktop Window Manager | GUI applications |

## Script Options

```
Usage: extract_exports.py [OPTIONS] [DLL_FILE]

Arguments:
  DLL_FILE              DLL filename to process (e.g., version.dll)

Options:
  -a, --all            Process all DLL files in directory
  -o, --output DIR     Custom output directory for headers
  -q, --quiet          Suppress detailed output
  --list               List all available DLL files
  -h, --help           Show help message
```

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

1. **File header** with metadata
2. **Export count** and original DLL path
3. **Pragma directives** for each export
4. **Header guards** to prevent multiple inclusion

Example output structure:

```cpp
#pragma once
/*
 * Auto-generated export forwarding header for version.dll
 * Total Exports: 17
 * Original DLL Path: C:\Windows\System32\version.dll
 */

#ifndef VERSION_EXPORTS_H
#define VERSION_EXPORTS_H

#pragma comment(linker, "/EXPORT:GetFileVersionInfoA=C:\\Windows\\System32\\version.dll.GetFileVersionInfoA,@1")
#pragma comment(linker, "/EXPORT:GetFileVersionInfoByHandle=C:\\Windows\\System32\\version.dll.GetFileVersionInfoByHandle,@2")
// ... more exports ...

#endif // VERSION_EXPORTS_H
```

## Advanced Usage

### Custom Original DLL Path

If you need to forward to a DLL at a custom location, edit the generated header's pragma directives:

```cpp
// Instead of:
#pragma comment(linker, "/EXPORT:FuncName=C:\\Windows\\System32\\dll.dll.FuncName,@1")

// Use:
#pragma comment(linker, "/EXPORT:FuncName=C:\\Custom\\Path\\dll.dll.FuncName,@1")
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

## Security Considerations

⚠️ **Important:**

- Only use DLL files from trusted sources
- Verify DLL integrity before extraction
- This tool is for research and educational purposes
- Respect software licenses and terms of service

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

