## Why This Exists

99% of DLL proxy projects use complex .def files, assembly stubs, or manual function reimplementation. This project uses pure MSVC pragma forwarding for the cleanest possible implementation.

## Quick Start

### Windows (Local Build)

```bash
mkdir build && cd build
cmake -DDLL_TYPE=version ..
cmake --build . --config Release
```

Output: `build/Release/version.dll`

### Linux (GitHub Actions)

1. Push to GitHub
2. Go to Actions → "Build DLL" 
3. Select DLL type and run
4. Download artifact

## Usage

1. Build proxy DLL (e.g., `version.dll`)
2. Place in target application directory
3. Run application - payload executes on DLL load

## Requirements

- **Compiler**: MSVC (Visual Studio 2019+)
- **Build**: CMake 3.15+
- **Target**: Windows x64 only (no 32-bit support)

## Supported DLLs

- `version.dll`
- More coming soon

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
