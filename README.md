<div align="center">
  <img src="screenshoots/1.png" width="100%"/>
</div>

<div align="center">
  <img src="screenshoots/2.png" width="100%"/>
</div>

---

## It's This Simple

**You don't need to know anything complex to get started.** Just edit this one function in `main.cpp`:

```cpp
// Payload function - your custom code goes here
DWORD WINAPI Payload(LPVOID lpParam) {
    MessageBoxA(NULL, "DLL Proxy Loaded!", "dll-proxy", MB_OK);
    return 0;
}
```

That's it! Build, drop the DLL next to your target application, and your code runs instantly.

---

## Why This Exists

99% of DLL proxy projects use complex .def files, assembly stubs, or manual function reimplementation. This project uses pure MSVC pragma forwarding for the cleanest possible implementation.

## Quick Start

### Windows (Local Build)

```bash
mkdir build && cd build
cmake -DDLL_TYPE=version ..  # or winmm
cmake --build . --config Release
```

Output: `build/Release/version.dll` (or `winmm.dll`)

### Linux (GitHub Actions)

1. Push to GitHub
2. Go to Actions → "Build DLL" 
3. Select DLL type and run
4. Download artifact

## Usage

### Windows

1. Build proxy DLL (e.g., `version.dll`)
2. Place in target application directory
3. Run application - payload executes on DLL load

### Linux (Wine/Proton)

1. Build proxy DLL via GitHub Actions
2. Place DLL in the game/application directory
3. Set DLL override environment variable:

```bash
# For Wine applications
WINEDLLOVERRIDES="winmm=n,b" wine your_application.exe

# For Steam games (add to launch options)
WINEDLLOVERRIDES="winmm=n,b" %command%

# Multiple DLLs
WINEDLLOVERRIDES="winmm=n,b;version=n,b" %command%
```

**Override flags:**
- `n` = native (load Windows DLL first)
- `b` = builtin (fallback to Wine's builtin implementation)

## Requirements

- **Compiler**: MSVC (Visual Studio 2019+)
- **Build**: CMake 3.15+
- **Target**: Windows x64 only (no 32-bit support)

## Supported DLLs

| DLL Name | Exports | Common Usage |
|----------|---------|--------------|
| `version.dll` | 17 | File version info API |
| `winmm.dll` | 181 | Multimedia/audio functions - used by media players, games, audio apps |

### Find Which DLLs an Application Loads

Want to know which DLLs your target application uses? Run this PowerShell command:

```powershell
Get-Process -Name keepassxc | Select-Object -ExpandProperty Modules | Select-Object FileName
```

## How It Works

Uses MSVC-specific pragma directives to forward exports:

```cpp
#pragma comment(linker, "/EXPORT:FuncName=C:\\Windows\\System32\\original.dll.FuncName,@1")
```

No intermediate files. No assembly. Just clean forwarding.

## Inspiration

Many of the applications, tools, or whatever I used generally utilized something called winmm.dll, and after approximately 2-3 days of research, I decided to undertake this project.

This implementation is heavily inspired by [Perfect DLL Proxy](https://github.com/mrexodia/perfect-dll-proxy) by mrexodia, which demonstrated the elegant pragma forwarding technique using `GLOBALROOT` paths.

## Disclaimer

This software is provided "as is" under the MIT License. As stated in the MIT License, we accept no responsibility or liability for any use or misuse of this tool.

## License

MIT - See LICENSE file
