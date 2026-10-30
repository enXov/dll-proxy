#!/usr/bin/env python3
"""
DLL Export Extractor for dll-proxy

Extracts function exports from a Windows DLL and generates C/C++ header files
with export forwarding directives. By default, the source DLL is pulled
directly from the **local Windows system files** (System32) - the exact same
location the proxy forwards to at runtime (GLOBALROOT\\SystemRoot\\System32).

Supports TWO forwarding methods:
  - Linker forwarding (default): MSVC pragma directives (simple, fast)
  - Runtime forwarding (--runtime): LoadLibrary + GetProcAddress + ASM thunks
    Required for complex applications and game engines.

Usage:
    python extract_exports.py winmm.dll      # from the system files (System32)
    python extract_exports.py <path>/to/dll  # from an explicit DLL file
    python extract_exports.py winmm.dll --runtime  # also generate runtime files

Requirements:
    - pefile (pip install pefile)
    - Run on Windows for system file sourcing (any OS works with explicit paths)
"""

import os
import re
import sys
import argparse
from pathlib import Path

try:
    import pefile
except ImportError:
    print("Error: pefile module not found!")
    print("Install it with: pip install pefile")
    sys.exit(1)


def extract_exports(dll_path):
    """
    Extract all exports from a DLL file.
    
    Args:
        dll_path: Path to the DLL file
        
    Returns:
        List of tuples: (function_name, ordinal)
    """
    if not os.path.exists(dll_path):
        print(f"Error: File '{dll_path}' not found!")
        return None
    
    try:
        pe = pefile.PE(dll_path)
        
        # Reject non-x64 DLLs early (project is x64-only). This also catches
        # 32-bit-Python-on-x64-Windows cases where System32 resolves to
        # SysWOW64 through WOW64 file-system redirection.
        machine = pe.FILE_HEADER.Machine
        if machine != 0x8664:  # IMAGE_FILE_MACHINE_AMD64
            print(f"Error: '{dll_path}' is not an x64 (AMD64) DLL "
                  f"(machine type 0x{machine:04x})! This project targets x64 only.")
            return None
        
        if not hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
            print(f"Error: '{dll_path}' has no export directory!")
            return None
        
        exports = []
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            # Get function name (decode bytes to string if needed)
            # Include ordinal-only exports (where exp.name is None)
            if exp.name:
                func_name = exp.name.decode('utf-8') if isinstance(exp.name, bytes) else exp.name
            else:
                func_name = None  # Ordinal-only export
            ordinal = exp.ordinal
            exports.append((func_name, ordinal))
        
        # Sort by ordinal for consistent output
        exports.sort(key=lambda x: x[1])
        
        return exports
    
    except pefile.PEFormatError as e:
        print(f"Error: '{dll_path}' is not a valid PE file!")
        print(f"Details: {e}")
        return None
    except Exception as e:
        print(f"Error processing '{dll_path}': {e}")
        return None


def resolve_dll_source(arg):
    """
    Resolve the user's DLL input to an actual file path.

    Accepts:
      1. An existing file path (absolute or relative) - used as-is.
      2. A system DLL file name ("winmm.dll") - resolved against the local
         Windows system files via GLOBALROOT\\SystemRoot, the same location
         the proxy forwards to at runtime.

    Returns a Path, or None on failure (with the reason printed).
    """
    # 1. As given (CWD-relative or absolute)
    candidate = Path(arg)
    if candidate.is_file():
        return str(candidate)

    # 2. Next to the script (convenient for manual runs with local copies)
    script_local = Path(__file__).parent / arg
    if script_local.is_file():
        return str(script_local)

    # 3. Windows system files (via the NT path). GLOBALROOT\SystemRoot
    #    resolves regardless of the installation drive (C:, D:, ...) and
    #    matches the path used by linker-method export forwarding.
    #    NOTE: built as plain strings; pathlib mangles device prefixes
    #    like \\.\GLOBALROOT (drops the SystemRoot component).
    name = os.path.basename(str(arg).replace('\\', '/')).lower()
    if not name.endswith('.dll'):
        print(f"Error: '{name}' does not end with '.dll'. "
              "Pass the system DLL file name, e.g. 'winmm.dll'.")
        return None
    stem = name[:-len('.dll')]
    if not re.fullmatch(r'[A-Za-z0-9_]+', stem):
        print(f"Error: '{name}' is an invalid DLL file name "
              "(letters, digits, underscore only).")
        return None

    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    system_path = (r'\\.\GLOBALROOT\SystemRoot\System32' + '\\' + name)
    if os.path.isfile(system_path):
        return system_path

    # Safety net: plain Win32 path (e.g. C:\Windows\System32\name.dll)
    win32_path = os.path.join(system_root, 'System32', name)
    if os.path.isfile(win32_path):
        return win32_path

    print(f"Error: Could not resolve '{arg}' to a DLL file.")
    print("Tried:")
    print(f"  - {candidate}          (as given)")
    print(f"  - {script_local}  (next to the script)")
    print(f"  - {system_path}  (Windows system files)")
    print("\nNote: system file sourcing requires running on Windows "
          "(GitHub Actions or a local Windows machine).")
    return None


def generate_header(dll_name, exports, use_ordinals=True):
    """
    Generate C/C++ header file with MSVC pragma export forwarding (linker method).
    Uses GLOBALROOT path inspired by Perfect DLL Proxy for maximum compatibility.
    Uses macro-based approach for cleaner, more maintainable code.
    Handles three export types: regular, COM/PRIVATE, and ordinal-only.
    
    Args:
        dll_name: Name of the DLL (e.g., "version.dll")
        exports: List of tuples (function_name, ordinal)
        use_ordinals: Include ordinals in exports (default: True, recommended)
    
    Returns:
        String containing the header file content
    """
    base_name = dll_name.replace('.dll', '').upper()
    
    # Use GLOBALROOT path (inspired by Perfect DLL Proxy)
    # This is more robust than C:\Windows as it works regardless of Windows installation directory
    original_path = f"\\\\\\\\.\\\\GLOBALROOT\\\\SystemRoot\\\\System32\\\\{dll_name}"
    path_display = f"\\\\.\\GLOBALROOT\\SystemRoot\\System32\\{dll_name}"
    
    # COM functions that need PRIVATE flag (like Perfect DLL Proxy)
    com_functions = {
        'DllCanUnloadNow',
        'DllGetClassObject', 
        'DllInstall',
        'DllRegisterServer',
        'DllUnregisterServer'
    }
    
    # Categorize exports
    regular_exports = []
    private_exports = []
    ordinal_only_exports = []
    
    for func_name, ordinal in exports:
        if func_name is None:
            # Ordinal-only export (no name)
            ordinal_only_exports.append(ordinal)
        elif func_name in com_functions:
            # COM export needs PRIVATE flag
            private_exports.append((func_name, ordinal))
        else:
            # Regular named export
            regular_exports.append((func_name, ordinal))
    
    # Count export types
    ordinal_status = "with ordinals" if use_ordinals else "without ordinals"
    export_summary = f"Total Exports: {len(exports)} ({ordinal_status})"
    if private_exports:
        export_summary += f" - {len(regular_exports)} regular, {len(private_exports)} COM/PRIVATE"
        if ordinal_only_exports:
            export_summary += f", {len(ordinal_only_exports)} ordinal-only"
    elif ordinal_only_exports:
        export_summary += f" - {len(regular_exports)} regular, {len(ordinal_only_exports)} ordinal-only"
    
    header = f"""#pragma once
/*
 * Auto-generated export forwarding header for {dll_name}
 * Generated by extract_exports.py
 * Inspired by Perfect DLL Proxy (https://github.com/mrexodia/perfect-dll-proxy)
 * 
 * {export_summary}
 * Original DLL Path: {path_display}
 * Architecture: x64 only
 * 
 * Usage:
 *   #include "exports/{dll_name.replace('.dll', '')}.h"
 * 
 * This header uses MSVC #pragma directives to forward all exports
 * to the original system DLL without manual function implementation.
 * 
 * The GLOBALROOT path ensures compatibility regardless of Windows
 * installation directory and works at the NT kernel level.
 */

#ifndef {base_name}_EXPORTS_H
#define {base_name}_EXPORTS_H

// Original DLL path (GLOBALROOT for maximum compatibility)
#define ORIGINAL_DLL "{original_path}"

// Export forwarding macros (like Perfect DLL Proxy)

"""
    
    # Add appropriate macros based on use_ordinals setting
    if use_ordinals:
        header += """// Regular export: Named function with ordinal
#define MAKE_EXPORT(name, ordinal) \\
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",@" #ordinal))

// COM export: Named function with PRIVATE flag (not in import library)
#define MAKE_EXPORT_PRIVATE(name, ordinal) \\
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",@" #ordinal ",PRIVATE"))

// Ordinal-only export: No name, only ordinal number with NONAME flag
#define MAKE_EXPORT_ORDINAL(proxy_name, ordinal) \\
    __pragma(comment(linker, "/EXPORT:" #proxy_name "=" ORIGINAL_DLL ".#" #ordinal ",@" #ordinal ",NONAME"))

"""
    else:
        header += """// Regular export: Named function without ordinal (auto-assigned by linker)
#define MAKE_EXPORT(name, ordinal) \\
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name))

// COM export: Named function with PRIVATE flag, no ordinal
#define MAKE_EXPORT_PRIVATE(name, ordinal) \\
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL "." #name ",PRIVATE"))

// Ordinal-only export: Cannot be used without ordinals - skipped
#define MAKE_EXPORT_ORDINAL(proxy_name, ordinal) \\
    /* Ordinal-only exports require ordinals - this export is skipped */

"""
    
    # Add regular exports
    if regular_exports:
        header += "// Regular exports\n"
        for func_name, ordinal in regular_exports:
            header += f'MAKE_EXPORT({func_name}, {ordinal})\n'
    
    # Add COM/PRIVATE exports
    if private_exports:
        header += "\n// COM exports (PRIVATE flag)\n"
        for func_name, ordinal in private_exports:
            header += f'MAKE_EXPORT_PRIVATE({func_name}, {ordinal})\n'
    
    # Add ordinal-only exports
    if ordinal_only_exports:
        header += "\n// Ordinal-only exports (NONAME flag)\n"
        for ordinal in ordinal_only_exports:
            header += f'MAKE_EXPORT_ORDINAL(__proxy{ordinal}, {ordinal})\n'
    
    header += f"""
#endif // {base_name}_EXPORTS_H
"""
    
    return header


def generate_runtime_header(dll_name, exports):
    """
    Generate runtime forwarding header file.
    Uses LoadLibrary + GetProcAddress for export resolution.
    Requires companion .asm file with jump thunks.
    
    This method is compatible with ALL applications including complex game engines.
    
    Args:
        dll_name: Name of the DLL (e.g., "winmm.dll")
        exports: List of tuples (function_name, ordinal)
    
    Returns:
        String containing the runtime header file content
    """
    base_name = dll_name.replace('.dll', '').upper()
    short_name = dll_name.replace('.dll', '')
    
    # COM functions that need PRIVATE flag
    com_functions = {
        'DllCanUnloadNow', 'DllGetClassObject', 'DllInstall',
        'DllRegisterServer', 'DllUnregisterServer'
    }
    
    # Categorize exports
    regular_exports = []
    private_exports = []
    ordinal_only_exports = []
    
    for func_name, ordinal in exports:
        if func_name is None:
            ordinal_only_exports.append(ordinal)
        elif func_name in com_functions:
            private_exports.append((func_name, ordinal))
        else:
            regular_exports.append((func_name, ordinal))
    
    all_named = regular_exports + private_exports
    total = len(all_named) + len(ordinal_only_exports)
    
    # --- Build header ---
    header = f"""#pragma once
/*
 * Auto-generated RUNTIME export forwarding header for {dll_name}
 * Generated by extract_exports.py (runtime mode)
 *
 * Total Exports: {total} ({len(all_named)} named + {len(ordinal_only_exports)} ordinal-only)
 * Method: Runtime forwarding (LoadLibrary + GetProcAddress + ASM thunks)
 * Architecture: x64 only
 *
 * This approach is compatible with ALL applications including complex game engines.
 * Unlike linker forwarding, exports are resolved at runtime under our
 * control, avoiding PE loader conflicts with complex game engines.
 *
 * Requires: {short_name}_runtime.asm (jump thunks)
 */

#ifndef {base_name}_RUNTIME_H
#define {base_name}_RUNTIME_H

#include <windows.h>
#include <stdio.h>

// ============================================================
// Function pointer storage (referenced by ASM thunks)
// ============================================================
extern "C" {{
"""
    
    # Function pointer declarations
    for func_name, ordinal in all_named:
        header += f"    FARPROC orig_{func_name} = NULL;\n"
    
    for ordinal in ordinal_only_exports:
        header += f"    FARPROC orig___proxy_ord{ordinal} = NULL;\n"
    
    header += "}\n\n"
    
    # Export pragmas
    header += "// ============================================================\n"
    header += "// Export pragmas (map original names to ASM thunks)\n"
    header += "// ============================================================\n"
    
    for func_name, ordinal in all_named:
        private_flag = ",PRIVATE" if func_name in com_functions else ""
        header += f'#pragma comment(linker, "/EXPORT:{func_name}=__proxy_{func_name},@{ordinal}{private_flag}")\n'
    
    for ordinal in ordinal_only_exports:
        header += f'#pragma comment(linker, "/EXPORT:__proxy_ord{ordinal}=__proxy_ord{ordinal},@{ordinal},NONAME")\n'
    
    # LoadOriginalDLL function
    header += f"""
// ============================================================
// Load original DLL and resolve all function pointers
// Call this from DllMain(DLL_PROCESS_ATTACH)
// ============================================================
inline bool LoadOriginalDLL() {{
    // Get System32 directory dynamically (works on all Windows installs)
    char sysDir[MAX_PATH];
    GetSystemDirectoryA(sysDir, MAX_PATH);

    char dllPath[MAX_PATH];
    sprintf_s(dllPath, MAX_PATH, "%s\\\\{dll_name}", sysDir);

    HMODULE hOriginal = LoadLibraryA(dllPath);
    if (!hOriginal) {{
        return false;
    }}

    // Resolve all function pointers
"""
    
    for func_name, ordinal in all_named:
        header += f'    orig_{func_name} = GetProcAddress(hOriginal, "{func_name}");\n'
    
    for ordinal in ordinal_only_exports:
        header += f'    orig___proxy_ord{ordinal} = GetProcAddress(hOriginal, MAKEINTRESOURCEA({ordinal}));\n'
    
    header += f"""
    return true;
}}

#endif // {base_name}_RUNTIME_H
"""
    
    return header


def generate_runtime_asm(dll_name, exports):
    """
    Generate MASM x64 assembly file with jump thunks for runtime forwarding.
    Each thunk is a simple indirect JMP through a function pointer.
    
    Args:
        dll_name: Name of the DLL (e.g., "winmm.dll")
        exports: List of tuples (function_name, ordinal)
    
    Returns:
        String containing the ASM file content
    """
    short_name = dll_name.replace('.dll', '')
    
    # COM functions
    com_functions = {
        'DllCanUnloadNow', 'DllGetClassObject', 'DllInstall',
        'DllRegisterServer', 'DllUnregisterServer'
    }
    
    # Categorize exports
    regular_exports = []
    private_exports = []
    ordinal_only_exports = []
    
    for func_name, ordinal in exports:
        if func_name is None:
            ordinal_only_exports.append(ordinal)
        elif func_name in com_functions:
            private_exports.append((func_name, ordinal))
        else:
            regular_exports.append((func_name, ordinal))
    
    all_named = regular_exports + private_exports
    total = len(all_named) + len(ordinal_only_exports)
    
    # --- Build ASM ---
    asm = f"""; Auto-generated RUNTIME forwarding thunks for {dll_name}
; Generated by extract_exports.py (runtime mode)
;
; Each function is a simple JMP through a function pointer.
; The function pointers (orig_*) are defined in {short_name}_runtime.h
; and initialized by LoadOriginalDLL() at runtime.
;
; Total thunks: {total}
; Architecture: x64 only
; Assembler: MASM (ml64.exe)

.data
"""
    
    # EXTERNDEF declarations
    for func_name, ordinal in all_named:
        asm += f"EXTERNDEF orig_{func_name} : QWORD\n"
    
    for ordinal in ordinal_only_exports:
        asm += f"EXTERNDEF orig___proxy_ord{ordinal} : QWORD\n"
    
    asm += "\n.code\n\n"
    
    # Jump thunks
    for func_name, ordinal in all_named:
        asm += f"__proxy_{func_name} PROC\n"
        asm += f"    jmp QWORD PTR [orig_{func_name}]\n"
        asm += f"__proxy_{func_name} ENDP\n\n"
    
    for ordinal in ordinal_only_exports:
        asm += f"__proxy_ord{ordinal} PROC\n"
        asm += f"    jmp QWORD PTR [orig___proxy_ord{ordinal}]\n"
        asm += f"__proxy_ord{ordinal} ENDP\n\n"
    
    asm += "END\n"
    
    return asm


def save_header(dll_name, header_content, output_dir=None):
    """
    Save generated header to file.
    
    Args:
        dll_name: Name of the DLL (e.g., "version.dll")
        header_content: Generated header content
        output_dir: Directory to save header (default: ./exports/)
    
    Returns:
        Path to saved file
    """
    if output_dir is None:
        # Default to ./exports relative to the current directory
        output_dir = Path("exports")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    header_name = dll_name.replace('.dll', '') + '.h'
    header_path = output_dir / header_name
    
    with open(header_path, 'w', encoding='utf-8') as f:
        f.write(header_content)
    
    return header_path


def save_runtime_files(dll_name, header_content, asm_content, output_dir=None):
    """
    Save generated runtime header and ASM files.
    
    Args:
        dll_name: Name of the DLL (e.g., "version.dll")
        header_content: Generated runtime header content
        asm_content: Generated ASM thunk content
        output_dir: Directory to save files (default: ./exports/)
    
    Returns:
        Tuple of (header_path, asm_path)
    """
    if output_dir is None:
        output_dir = Path("exports")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    short_name = dll_name.replace('.dll', '')
    
    header_path = output_dir / f"{short_name}_runtime.h"
    asm_path = output_dir / f"{short_name}_runtime.asm"
    
    with open(header_path, 'w', encoding='utf-8') as f:
        f.write(header_content)
    
    with open(asm_path, 'w', encoding='utf-8') as f:
        f.write(asm_content)
    
    return header_path, asm_path


def print_export_summary(dll_name, exports):
    """Print a summary of extracted exports."""
    print(f"\n{'='*60}")
    print(f"DLL: {dll_name}")
    print(f"{'='*60}")
    print(f"Total Exports: {len(exports)}")
    print(f"\nFirst 10 exports:")
    print(f"{'Ordinal':<10} {'Function Name'}")
    print(f"{'-'*60}")
    
    for func_name, ordinal in exports[:10]:
        display_name = func_name if func_name else "(ordinal-only)"
        print(f"{ordinal:<10} {display_name}")
    
    if len(exports) > 10:
        print(f"... and {len(exports) - 10} more")
    print(f"{'='*60}\n")


def process_dll(dll_arg, output_dir=None, verbose=True, use_ordinals=True, runtime=False):
    """
    Process a single DLL: extract exports and generate header(s).
    
    Args:
        dll_arg: DLL input - an existing file path, or a bare system DLL
                 name ("winmm" or "winmm.dll") resolved from System32
        output_dir: Custom output directory for header
        verbose: Print detailed information
        use_ordinals: Include ordinals in exports (default: True)
        runtime: Also generate runtime forwarding files (default: False)
    
    Returns:
        True if successful, False otherwise
    """
    dll_path = resolve_dll_source(dll_arg)
    if dll_path is None:
        return False
    
    dll_name = os.path.basename(str(dll_path)).lower()
    
    if verbose:
        print(f"Processing: {dll_path}")
        print(f"Proxy target at runtime: \\\\.\\GLOBALROOT\\SystemRoot\\System32\\{dll_name}")
    
    # Extract exports
    exports = extract_exports(dll_path)
    if exports is None:
        return False
    
    if len(exports) == 0:
        print(f"Warning: No exports found in '{dll_name}'")
        return False
    
    # Print summary
    if verbose:
        print_export_summary(dll_name, exports)
    
    # Generate linker forwarding header (always)
    header_content = generate_header(dll_name, exports, use_ordinals)
    header_path = save_header(dll_name, header_content, output_dir)
    
    if verbose:
        print(f"✓ Linker header generated: {header_path}")
    
    # Generate runtime forwarding files (if requested)
    if runtime:
        rt_header = generate_runtime_header(dll_name, exports)
        rt_asm = generate_runtime_asm(dll_name, exports)
        rt_header_path, rt_asm_path = save_runtime_files(
            dll_name, rt_header, rt_asm, output_dir
        )
        
        if verbose:
            print(f"✓ Runtime header generated: {rt_header_path}")
            print(f"✓ Runtime ASM generated:    {rt_asm_path}")
    
    if verbose:
        method_info = " (linker + runtime)" if runtime else ""
        print(f"✓ Ready to use in CMake with -DDLL_TYPE={dll_name.replace('.dll', '')}{method_info}\n")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Extract DLL exports and generate forwarding headers '
                    '(source defaults to the local Windows system files)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate linker forwarding header from the system files
  python extract_exports.py winmm.dll

  # Same, but also generate runtime forwarding files (.h + .asm)
  python extract_exports.py winmm.dll --runtime

  # Generate from an explicit DLL file (any location)
  python extract_exports.py X:\\copy\\of\\version.dll --runtime

  # Custom output directory
  python extract_exports.py winmm.dll -o /path/to/output

Usage from CMake (generation runs automatically at configure time):
  cmake -B build -DDLL_TYPE=winmm.dll -DPROXY_METHOD=runtime
  cmake --build build --config Release
"""
    )
    
    parser.add_argument(
        'dll_file',
        nargs='?',
        help='System DLL file name (e.g. winmm.dll -> system files) or an explicit DLL file path'
    )
    
    parser.add_argument(
        '-o', '--output',
        metavar='DIR',
        help='Output directory for generated headers (default: ./exports/)'
    )
    
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress detailed output'
    )
    
    parser.add_argument(
        '--no-ordinals',
        action='store_true',
        help='Disable ordinals in exports (not recommended, breaks ordinal-based imports)'
    )
    
    parser.add_argument(
        '--runtime',
        action='store_true',
        help='Also generate runtime forwarding files (.h + .asm) for maximum compatibility'
    )
    
    args = parser.parse_args()
    
    # Determine ordinal usage
    use_ordinals = not args.no_ordinals
    
    # Process single DLL
    if args.dll_file:
        success = process_dll(args.dll_file, args.output, verbose=not args.quiet, 
                            use_ordinals=use_ordinals, runtime=args.runtime)
        return 0 if success else 1
    
    # No arguments provided
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
