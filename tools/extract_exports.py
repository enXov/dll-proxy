#!/usr/bin/env python3
"""
DLL Export Extractor for dll-proxy

Extracts function exports from a Windows DLL and generates C/C++ header files
with export forwarding directives. The source is an explicit DLL file path -
that file is the only thing that determines the export set, so builds are
reproducible across machines. At runtime the proxy still targets the real
system module (GLOBALROOT\\SystemRoot\\System32\\<name>).

Supports THREE output forms:
  - Linker forwarding (default): MSVC pragma headers (simple, fast)
  - GNU ld forwarding (--def): .def forwarding file for MinGW-w64 builds
  - Runtime forwarding (--runtime): LoadLibrary + GetProcAddress + thunks

Usage:
    python extract_exports.py C:\\Windows\\System32\\winmm.dll
    python extract_exports.py /path/to/winmm.dll --runtime
    python extract_exports.py /path/to/winmm.dll --def      # GNU ld .def

Requirements:
    - pefile (pip install pefile)
    - Works on any OS (input is an explicit file path)
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
        
        # Reject non-x64 DLLs early (project is x64-only)
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
    Resolve the DLL input to an actual file path.

    The input must be an explicit DLL file path (absolute or
    CWD-relative). That file is the single source of truth for the
    export set, and its file name is what the proxy stands in for at
    runtime (System32\\<name>).

    Returns a Path, or None on failure (with the reason printed).
    """
    candidate = Path(arg)
    if candidate.is_file():
        return str(candidate)

    print(f"Error: '{arg}' is not an existing DLL file.")
    print("Pass the path to the DLL file you want to proxy.")
    return None


def forward_targets(dll_name, target_module=None):
    """
    Compute the module a proxy forwards its exports to.

    Default: the Windows system module via the GLOBALROOT NT path, which
    resolves regardless of the installation drive - the same module the
    proxy impersonates. This works for kernel/loader forwarder strings,
    not as a runtime LoadLibrary path.

    target_module: any module string a forwarder may legally reference -
    a plain module name (resolved through the loading application's
    directory first, the classic same-folder hijack) or an absolute path.
    It must NOT be the proxy's own name (that would forward to itself).

    Returns: (natural, c_escaped) - the raw string, and the same string
    with backslashes doubled for embedding in a C string literal.
    """
    if target_module:
        natural = str(target_module)
    else:
        natural = rf"\\.\GLOBALROOT\SystemRoot\System32\{dll_name}"
    return natural, natural.replace('\\', '\\\\')


def generate_header(dll_name, exports, use_ordinals=True, target_module=None):
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

    # Module the exports forward to (GLOBALROOT system path by default,
    # or a custom target such as the renamed original for private DLLs)
    original_path_c = forward_targets(dll_name, target_module)[1]
    path_display = forward_targets(dll_name, target_module)[0]
    
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
 * to the original module without manual function implementation.
 */

#ifndef {base_name}_EXPORTS_H
#define {base_name}_EXPORTS_H

// Module the exports forward to (GLOBALROOT system path by default)
#define ORIGINAL_DLL "{original_path_c}"

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


def generate_def(dll_name, exports, use_ordinals=True, target_module=None):
    """
    Generate a GNU ld .def forwarding file (for MinGW-w64 builds).

    Forwarder entries use the exact same module path as the MSVC pragma
    output. binutils ld parses .def files natively for PE targets:

      - ld/deffilep.y: export lines accept quoted names and the
        "NAME = MODULE-NAME.EXTERNAL-NAME" forwarder form
      - ld/pe-dll.c: any dotted internal name is flagged as a forwarder
        and the string is stored verbatim in the PE export table

    Quoting the path is what makes the dotted GLOBALROOT path work in
    .def files (link.exe cannot parse those; binutils can).

    Handles the same three export categories as the pragma header:
    regular (with ordinal), COM/PRIVATE, and ordinal-only (NONAME,
    forwarded by ordinal): "#N".

    Args:
        dll_name: Name of the DLL (e.g., "version.dll")
        exports: List of tuples (function_name, ordinal)
        use_ordinals: Pin ordinals on named exports (default: True)
        target_module: Module to forward to (default: GLOBALROOT system path)

    Returns:
        String containing the .def file content
    """
    com_functions = {
        'DllCanUnloadNow', 'DllGetClassObject', 'DllInstall',
        'DllRegisterServer', 'DllUnregisterServer'
    }

    # Same forward target the MSVC pragma output uses
    dllpath = forward_targets(dll_name, target_module)[0]

    lines = [
        f"; Auto-generated GNU ld forwarding file for {dll_name}",
        "; Generated by extract_exports.py (--def)",
        f"; Original DLL Path: {dllpath}",
        f'LIBRARY "{dll_name}"',
        "EXPORTS",
        "",
    ]

    for func_name, ordinal in exports:
        if func_name is None:
            # Ordinal-only export: no name at all, forward by ordinal (#N)
            line = (f'"__proxy{ordinal}" = "{dllpath}"."#{ordinal}" '
                    f"@{ordinal} NONAME")
        else:
            line = f'"{func_name}" = "{dllpath}"."{func_name}"'
            if use_ordinals:
                line += f" @{ordinal}"
            if func_name in com_functions:
                line += " PRIVATE"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def generate_runtime_header(dll_name, exports, target_module=None):
    """
    Generate runtime forwarding header file.
    Uses LoadLibrary + GetProcAddress for export resolution.

    Thunks: MSVC builds pair this header with a separate
    <name>_runtime.asm (MASM) and pragma export directives; MinGW-w64
    builds use the GNU naked stubs inside this header plus a generated
    <name>_runtime.def export mapping.

    This method resolves exports at runtime, under our own control,
    instead of leaving it to the PE loader.
    
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
 * Method: Runtime forwarding (LoadLibrary + GetProcAddress + jump thunks)
 * Architecture: x64 only
 *
 * Unlike linker forwarding, exports are resolved at runtime under our
 * own control instead of by the PE loader.
 *
 * Thunks: {short_name}_runtime.asm (MASM, MSVC builds) or the GNU naked
 * stubs inside this header (MinGW-w64 builds). Exported names map to
 * thunks via MSVC pragmas or proxy_exports.def respectively.
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
    
    # Export wiring is toolchain-specific:
    #   MSVC: pragma directives map exported names to the ASM thunks.
    #   MinGW-w64: a generated .def file does the same mapping
    #   (proxy_exports.def, see generate_runtime_def) and the thunks
    #   themselves are naked GNU stubs emitted below.
    header += "// ============================================================\n"
    header += "// Export wiring (toolchain-specific)\n"
    header += "// ============================================================\n\n"

    header += "#if defined(_MSC_VER)\n"
    for func_name, ordinal in all_named:
        private_flag = ",PRIVATE" if func_name in com_functions else ""
        header += f'#pragma comment(linker, "/EXPORT:{func_name}=__proxy_{func_name},@{ordinal}{private_flag}")\n'

    for ordinal in ordinal_only_exports:
        header += f'#pragma comment(linker, "/EXPORT:__proxy_ord{ordinal}=__proxy_ord{ordinal},@{ordinal},NONAME")\n'
    header += "#endif\n"

    header += """#if defined(__GNUC__) && !defined(_MSC_VER)
// MinGW-w64 (GCC): naked thunk stubs. Exported names are mapped to
// these symbols through proxy_exports.def; each stub jumps through the
// matching function pointer resolved by LoadOriginalDLL().
// GCC supports the naked attribute on x86_64 (>= GCC 8), which
// guarantees no prologue is emitted for the stubs.
"""
    for func_name, ordinal in all_named:
        header += f'extern "C" __attribute__((naked)) void __proxy_{func_name}(void) {{ __asm__ volatile ("jmp *orig_{func_name}(%rip)"); }}\n'

    for ordinal in ordinal_only_exports:
        header += f'extern "C" __attribute__((naked)) void __proxy_ord{ordinal}(void) {{ __asm__ volatile ("jmp *orig___proxy_ord{ordinal}(%rip)"); }}\n'

    header += "#endif\n"
    
    # Where the original module is loaded from at runtime: the system
    # directory by default, or the custom forward target verbatim
    # (a plain module name resolves in the loading application's
    # directory first - the classic same-folder layout)
    if target_module:
        load_block = (f'    HMODULE hOriginal = LoadLibraryA("'
                      f'{forward_targets(dll_name, target_module)[1]}");')
    else:
        load_block = (
            '    // Get System32 directory dynamically (works on all '
            'Windows installs)\n'
            '    char sysDir[MAX_PATH];\n'
            '    GetSystemDirectoryA(sysDir, MAX_PATH);\n\n'
            '    char dllPath[MAX_PATH];\n'
            f'    sprintf_s(dllPath, MAX_PATH, "%s\\\\{dll_name}", '
            'sysDir);\n\n'
            '    HMODULE hOriginal = LoadLibraryA(dllPath);')

    # LoadOriginalDLL function
    header += f"""
// ============================================================
// Load original DLL and resolve all function pointers
// Call this from DllMain(DLL_PROCESS_ATTACH)
// ============================================================
inline bool LoadOriginalDLL() {{
{load_block}
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


def generate_runtime_def(dll_name, exports):
    """
    Generate a GNU ld .def file mapping the proxy's exported names to
    the runtime thunks (MinGW-w64 runtime mode).

    Every internal name is a real link-time symbol (__proxy_*), so GNU
    ld emits true exports of the thunk code - not forwarder entries.
    Flag semantics mirror the MSVC pragma lines: pinned ordinals,
    NONAME for ordinal-only exports, PRIVATE for COM exports.

    Args:
        dll_name: Name of the DLL (e.g., "winmm.dll")
        exports: List of tuples (function_name, ordinal)

    Returns:
        String containing the runtime .def file content
    """
    com_functions = {
        'DllCanUnloadNow', 'DllGetClassObject', 'DllInstall',
        'DllRegisterServer', 'DllUnregisterServer'
    }

    lines = [
        f"; Auto-generated GNU ld export mapping for the {dll_name} runtime proxy",
        "; Generated by extract_exports.py (--def --runtime)",
        "; Each export targets a naked GNU thunk symbol defined in",
        f"; {dll_name.replace('.dll', '')}_runtime.h (resolved by LoadOriginalDLL at startup).",
        f'LIBRARY "{dll_name}"',
        "EXPORTS",
        "",
    ]

    for func_name, ordinal in exports:
        if func_name is None:
            # Ordinal-only export: thunk + NONAME at the same ordinal
            thunk = f"__proxy_ord{ordinal}"
            lines.append(f'"{thunk}" = "{thunk}" @{ordinal} NONAME')
        else:
            thunk = f"__proxy_{func_name}"
            line = f'"{func_name}" = "{thunk}" @{ordinal}'
            if func_name in com_functions:
                line += " PRIVATE"
            lines.append(line)

    lines.append("")
    return "\n".join(lines)


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


def save_def(dll_name, def_content, output_dir=None):
    """
    Save generated .def file.

    Returns:
        Path to saved file
    """
    if output_dir is None:
        output_dir = Path("exports")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def_path = output_dir / (dll_name.replace('.dll', '') + '.def')

    with open(def_path, 'w', encoding='utf-8') as f:
        f.write(def_content)

    return def_path


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

    if asm_content is None:
        # Header-only save (MinGW-w64 runtime builds: thunks live in the
        # header as GNU naked stubs, no MASM file needed)
        return header_path, None

    with open(asm_path, 'w', encoding='utf-8') as f:
        f.write(asm_content)

    return header_path, asm_path


def save_runtime_def(dll_name, def_content, output_dir=None):
    """
    Save the generated runtime export-mapping .def file.

    Returns:
        Path to saved file
    """
    if output_dir is None:
        output_dir = Path("exports")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def_path = output_dir / (dll_name.replace('.dll', '') + '_runtime.def')

    with open(def_path, 'w', encoding='utf-8') as f:
        f.write(def_content)

    return def_path


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


def process_dll(dll_arg, output_dir=None, verbose=True, use_ordinals=True,
                runtime=False, def_out=False, target_module=None):
    """
    Process a single DLL: extract exports and generate the output files.

    Args:
        dll_arg: Path to the DLL file to extract exports from
        output_dir: Custom output directory for generated files
        verbose: Print detailed information
        use_ordinals: Include ordinals in exports (default: True)
        runtime: Also generate runtime forwarding files
                 (.h + .asm for MSVC; .h + .def for MinGW-w64 when
                 def_out is set - GNU thunks live in the header)
        def_out: Generate GNU ld .def output (MinGW-w64) instead of the
                 MSVC pragma header
        target_module: Module the proxy forwards to (default: the
                 GLOBALROOT system module matching the source's name)

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
    
    # Generate the toolchain-specific output files
    if def_out and runtime:
        # MinGW-w64 runtime bundle: runtime header (GNU naked thunks
        # included, MSVC pragmas gated out) + thunk-mapping .def.
        # No MASM assembly and no pragma/forwarder files.
        rt_header = generate_runtime_header(dll_name, exports, target_module)
        rt_header_path, _ = save_runtime_files(dll_name, rt_header, None, output_dir)
        rt_def_content = generate_runtime_def(dll_name, exports)
        rt_def_path = save_runtime_def(dll_name, rt_def_content, output_dir)

        if verbose:
            print(f"✓ Runtime header generated: {rt_header_path} (GNU thunks inside)")
            print("✓ Local build:\n"
                  "    cmake -B build -G Ninja -DCMAKE_SYSTEM_NAME=Windows "
                  f"-DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ "
                  f"-DDLL_SOURCE=/path/to/{dll_name} -DPROXY_METHOD=runtime")
    elif def_out:
        def_content = generate_def(dll_name, exports, use_ordinals, target_module)
        def_path = save_def(dll_name, def_content, output_dir)

        if verbose:
            print(f"✓ GNU ld def generated:    {def_path}")
            print("✓ Local build:\n"
                  "    cmake -B build -G Ninja -DCMAKE_SYSTEM_NAME=Windows "
                  f"-DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ "
                  f"-DDLL_SOURCE=/path/to/{dll_name}")
    else:
        header_content = generate_header(dll_name, exports, use_ordinals, target_module)
        header_path = save_header(dll_name, header_content, output_dir)

        if verbose:
            print(f"✓ Linker header generated: {header_path}")

        # Generate runtime forwarding files (MSVC/MASM, if requested)
        if runtime:
            rt_header = generate_runtime_header(dll_name, exports, target_module)
            rt_asm = generate_runtime_asm(dll_name, exports)
            rt_header_path, rt_asm_path = save_runtime_files(
                dll_name, rt_header, rt_asm, output_dir
            )

            if verbose:
                print(f"✓ Runtime header generated: {rt_header_path}")
                print(f"✓ Runtime ASM generated:    {rt_asm_path}")

    if verbose and not def_out:
        method_info = " -DPROXY_METHOD=runtime" if runtime else ""
        print(f"✓ Ready to use in CMake with -DDLL_SOURCE=<path to {dll_name}>{method_info}\n")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Extract DLL exports and generate forwarding headers '
                    '(source defaults to the local Windows system files)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a GNU ld .def file for MinGW-w64 local builds
  python extract_exports.py /path/to/winmm.dll --def

  # Custom forward target, for a private DLL whose original was
  # renamed next to where the proxy will be dropped
  python extract_exports.py /path/to/custom.dll --target custom_orig.dll

  # Custom output directory
  python extract_exports.py /path/to/winmm.dll -o /path/to/output

Usage from CMake (generation runs automatically at configure time):
  cmake -B build -DDLL_SOURCE=C:\\Windows\\System32\\winmm.dll
  cmake --build build --config Release

  # MinGW-w64 cross-build on Linux (see the repo README for the full flags)
  cmake -B build -G Ninja -DCMAKE_SYSTEM_NAME=Windows \\
        -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \\
        -DDLL_SOURCE=/path/to/winmm.dll
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
        help='Also generate runtime forwarding files '
             '(.h + .asm for MSVC; .h + .def for MinGW-w64 when paired with --def)'
    )

    parser.add_argument(
        '--def',
        action='store_true',
        dest='def_file',
        help='Generate a GNU ld .def file (MinGW-w64) instead of the MSVC pragma header'
    )

    parser.add_argument(
        '--target',
        metavar='MODULE',
        help='Module the proxy forwards to (default: '
             '\\\\.\\GLOBALROOT\\SystemRoot\\System32\\<source dll name>). '
             'Use a custom target for private DLLs - point it at the '
             'renamed original (e.g. "game_orig.dll", resolved in the '
             "application's directory). Never the proxy's own name."
    )

    args = parser.parse_args()

    # Determine ordinal usage
    use_ordinals = not args.no_ordinals

    # Process single DLL
    if args.dll_file:
        success = process_dll(args.dll_file, args.output, verbose=not args.quiet,
                            use_ordinals=use_ordinals, runtime=args.runtime,
                            def_out=args.def_file, target_module=args.target)
        return 0 if success else 1
    
    # No arguments provided
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
