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

    # Combine several modules into one proxy: the first file is the
    # identity; every --source entry is merged name-only and forwarded
    # to its own module.
    python extract_exports.py winmm.dll --source version.dll

Requirements:
    - pefile (pip install pefile)
    - Works on any OS (input is an explicit file path)
"""

import os
import re
import sys
import argparse
from pathlib import Path

# Exported functions that carry the PRIVATE flag (COM registration entry points)
COM_FUNCTIONS = {
    'DllCanUnloadNow', 'DllGetClassObject', 'DllInstall',
    'DllRegisterServer', 'DllUnregisterServer'
}

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
    Compute the descriptor of the module a proxy forwards its exports to.

    Default: the Windows system module via the GLOBALROOT NT path, which
    resolves regardless of the installation drive - the same module the
    proxy impersonates. GLOBALROOT is valid as a LOADER forwarder string
    only, so the runtime method loads the module from the system
    directory by name instead (hence 'load_name').

    target_module: any module string a forwarder may legally reference -
    a plain module name (resolved through the loading application's
    directory first, the classic same-folder hijack) or an absolute path.
    It must NOT be the proxy's own name (that would forward to itself).

    Returns dict:
        forward    - the module string for forwarder exports
        forward_c  - the same string, backslashes doubled for C literals
        load_direct- string to pass to LoadLibraryA() at runtime, or None
        load_name  - module name to load from the system directory, or None
    """
    if target_module:
        natural = str(target_module)
        return {
            'forward': natural,
            'forward_c': natural.replace('\\', '\\\\'),
            'load_direct': natural,
            'load_name': None,
        }
    natural = rf"\\.\GLOBALROOT\SystemRoot\System32\{dll_name}"
    return {
        'forward': natural,
        'forward_c': natural.replace('\\', '\\\\'),
        'load_direct': None,
        'load_name': dll_name,
    }


def collect_exports(sources, verbose=False):
    """
    Extract and merge exports from one or more source DLLs.

    sources: list of (dll_path, target_module) pairs. The FIRST entry is
    the identity source: it keeps its original ordinals, its COM
    (PRIVATE) flags and its ordinal-only (NONAME) exports. Following
    entries are merged name-only: an additional module cannot keep
    original ordinals in the same export table (the ordinal spaces
    collide), and its NONAME exports cannot be represented without a
    name - both are reported as warnings.

    Returns:
        (entries, warnings) - entries is a list of dicts:
            {'name', 'ordinal' (None = auto), 'private', 'tgt' (descriptor)}
        or (None, None) if any source failed.
    """
    entries = []
    warnings = []
    seen_names = set()
    for idx, (path, target_module) in enumerate(sources):
        dll_name = os.path.basename(str(path)).lower()
        exports = extract_exports(path)
        if exports is None:
            return None, None
        if verbose:
            print(f"  source {idx}: {path} ({len(exports)} exports)")
        tgt = forward_targets(dll_name, target_module)

        for func_name, ordinal in exports:
            if func_name is None:
                if idx == 0:
                    entries.append({'name': None, 'ordinal': ordinal,
                                    'private': False, 'tgt': tgt})
                else:
                    warnings.append(
                        f"  dropped ordinal-only export #{ordinal} of '{dll_name}' "
                        "(another module's NONAME ordinals cannot be represented)")

                continue
            if func_name in seen_names:
                warnings.append(
                    f"  skipped duplicate export '{func_name}' from '{dll_name}' "
                    "(same name already exported from an earlier source)")
                continue
            seen_names.add(func_name)
            entries.append({
                'name': func_name,
                # only the identity source keeps its original ordinals
                'ordinal': ordinal if idx == 0 else None,
                'private': func_name in COM_FUNCTIONS,
                'tgt': tgt,
            })

    if verbose:
        for w in warnings:
            print(w)
        if any(e['ordinal'] is None for e in entries):
            print("  ordinal policy: identity source pinned, extra sources name-only")

    return entries, warnings


def generate_header(dll_name, entries, use_ordinals=True):
    """
    Generate C/C++ header file with MSVC pragma export forwarding (linker method).

    entries: list of dicts as built by collect_exports(), each carrying
        'name', 'ordinal' (None = auto-assigned by the linker), 'target'
        (module the export forwards to) and 'private' (COM flag). The
        first source keeps its original ordinals and NONAME exports;
        additional sources are name-only (see collect_exports).

    Args:
        dll_name: Name of the proxy DLL (identity, e.g. "version.dll")
        entries: Forwarder entries
        use_ordinals: Pin ordinals where available (default: True)

    Returns:
        String containing the header file content
    """
    base_name = dll_name.replace('.dll', '').upper()

    # Group the entries per forward target, preserving first-seen order
    targets = []
    for e in entries:
        if e['tgt']['forward'] not in targets:
            targets.append(e['tgt']['forward'])

    auto = any(e['ordinal'] is None for e in entries)
    noname = any(e['name'] is None for e in entries)
    total = len(entries)

    summary = (f"Total Exports: {total} across {len(targets)} target module(s)")
    if auto:
        summary += " (extra sources are name-only: auto ordinals)"
    if use_ordinals:
        summary += ", ordinals pinned where available"
    else:
        summary += ", ordinals off (--no-ordinals)"

    header = f"""#pragma once
/*
 * Auto-generated export forwarding header for {dll_name}
 * Generated by extract_exports.py
 * Inspired by Perfect DLL Proxy (https://github.com/mrexodia/perfect-dll-proxy)
 *
 * {summary}
 * Architecture: x64 only
 *
 * Usage:
 *   #include "exports/{dll_name.replace('.dll', '')}.h"
 *
 * MSVC #pragma directives forward every export to its target module.
 */

#ifndef {base_name}_EXPORTS_H
#define {base_name}_EXPORTS_H

"""
    # Per-target module paths and pragma macros
    for idx, target in enumerate(targets):
        c_path = target.replace('\\', '\\\\')
        header += f"// Forward target {idx}: {target}\n"
        header += f'#define ORIGINAL_DLL_{idx} "{c_path}"\n\n'
        header += f"""#define MAKE_EXPORT_{idx}(name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL_{idx} "." #name ",@" #ordinal))

#define MAKE_EXPORT_AUTO_{idx}(name) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL_{idx} "." #name))

#define MAKE_EXPORT_PRIVATE_{idx}(name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL_{idx} "." #name ",@" #ordinal ",PRIVATE"))

#define MAKE_EXPORT_PRIVATE_AUTO_{idx}(name) \
    __pragma(comment(linker, "/EXPORT:" #name "=" ORIGINAL_DLL_{idx} "." #name ",PRIVATE"))

#define MAKE_EXPORT_ORDINAL_{idx}(proxy_name, ordinal) \
    __pragma(comment(linker, "/EXPORT:" #proxy_name "=" ORIGINAL_DLL_{idx} ".#" #ordinal ",@" #ordinal ",NONAME"))

"""
    # The export lines, grouped per target, preserving the entry order
    for idx, target in enumerate(targets):
        header += f"// Exports -> {target}\n"
        for e in entries:
            if e['tgt']['forward'] != target:
                continue
            if e['name'] is None:
                header += f"MAKE_EXPORT_ORDINAL_{idx}(__proxy{e['ordinal']}, {e['ordinal']})\n"
                continue
            pinned = use_ordinals and e['ordinal'] is not None
            if e['private']:
                header += (f"MAKE_EXPORT_PRIVATE_{idx}({e['name']}, {e['ordinal']})\n"
                           if pinned else f"MAKE_EXPORT_PRIVATE_AUTO_{idx}({e['name']})\n")
            else:
                header += (f"MAKE_EXPORT_{idx}({e['name']}, {e['ordinal']})\n"
                           if pinned else f"MAKE_EXPORT_AUTO_{idx}({e['name']})\n")
        header += "\n"

    header += f"""
#endif // {base_name}_EXPORTS_H
"""

    return header


def generate_def(dll_name, entries, use_ordinals=True):
    """
    Generate a GNU ld .def forwarding file (for MinGW-w64 builds).

    entries: forwarder entries from collect_exports(); each export line
    points at the entry's own target module. pivot True/False on
    use_ordinals controls whether pinned ordinals are emitted (none of
    the extra-source entries carry one anyway).

    Args:
        dll_name: Name of the proxy DLL (identity, e.g. "version.dll")
        entries: Forwarder entries
        use_ordinals: Pin ordinals where available (default: True)

    Returns:
        String containing the .def file content
    """
    targets = []
    for e in entries:
        if e['tgt']['forward'] not in targets:
            targets.append(e['tgt']['forward'])

    lines = [
        f"; Auto-generated GNU ld forwarding file for {dll_name}",
        "; Generated by extract_exports.py (--def)",
        f"; Targets: {len(targets)} module(s) - "
        + ", ".join(targets),
    ]
    if any(e['ordinal'] is None for e in entries):
        lines.append("; Extra-source exports are name-only (auto ordinals)")
    lines += [f'LIBRARY "{dll_name}"', "EXPORTS", ""]

    for e in entries:
        target = e['tgt']['forward']
        if e['name'] is None:
            lines.append(f'"__proxy{e['ordinal']}" = "{target}"."#{e['ordinal']}" '
                         f"@{e['ordinal']} NONAME")
            continue
        line = f'"{e["name"]}" = "{target}"."{e["name"]}"'
        if use_ordinals and e['ordinal'] is not None:
            line += f" @{e['ordinal']}"
        if e['private']:
            line += " PRIVATE"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def generate_runtime_header(dll_name, entries):
    """
    Generate runtime forwarding header file.
    Uses LoadLibrary + GetProcAddress for export resolution.

    entries: forwarder entries from collect_exports(). Every unique
    target module is loaded once in LoadOriginalDLL() - the identity
    source from the system directory by default (or from the custom
    forward target), extra sources from their module path - and every
    export pointer is resolved from ITS OWN module.

    Thunks: MSVC builds pair this header with a separate
    <name>_runtime.asm (MASM) and pragma export directives; MinGW-w64
    builds use the GNU naked stubs inside this header plus a generated
    <name>_runtime.def export mapping.
    """
    base_name = dll_name.replace('.dll', '').upper()
    short_name = dll_name.replace('.dll', '')

    # Unique load specs, in first-seen order (identity source first)
    load_specs = []
    for e in entries:
        spec = (e['tgt']['load_direct'], e['tgt']['load_name'])
        if spec not in load_specs:
            load_specs.append(spec)

    noname_entries = [e for e in entries if e['name'] is None]
    named_entries = [e for e in entries if e['name'] is not None]
    total = len(entries)

    header = f"""#pragma once
/*
 * Auto-generated RUNTIME export forwarding header for {dll_name}
 * Generated by extract_exports.py (runtime mode)
 *
 * Total Exports: {total} ({len(named_entries)} named + {len(noname_entries)} ordinal-only)
 * Modules loaded: {len(load_specs)}
 * Architecture: x64 only
 *
 * Unlike linker forwarding, exports are resolved at runtime under our
 * own control instead of by the PE loader.
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
    for e in entries:
        name = e['name']
        if name is None:
            header += f"    FARPROC orig___proxy_ord{e['ordinal']} = NULL;\n"
        else:
            header += f"    FARPROC orig_{name} = NULL;\n"

    header += "}\n\n"

    # Export wiring: toolchain-specific.
    #   MSVC: pragma directives map exported names to the ASM thunks.
    #   MinGW-w64: a generated .def file does the same mapping
    #   (proxy_exports.def, see generate_runtime_def) and the thunks
    #   themselves are naked GNU stubs emitted below.
    header += "// ============================================================\n"
    header += "// Export wiring (toolchain-specific)\n"
    header += "// ============================================================\n\n"

    header += "#if defined(_MSC_VER)\n"
    for e in entries:
        if e['name'] is None:
            o = e['ordinal']
            header += f'#pragma comment(linker, "/EXPORT:__proxy_ord{o}=__proxy_ord{o},@{o},NONAME")\n'
            continue
        private_flag = ",PRIVATE" if e['private'] else ""
        ord_flag = f",@{e['ordinal']}" if e['ordinal'] is not None else ""
        header += f'#pragma comment(linker, "/EXPORT:{e["name"]}=__proxy_{e["name"]}{ord_flag}{private_flag}")\n'
    header += "#endif\n"

    header += """#if defined(__GNUC__) && !defined(_MSC_VER)
// MinGW-w64 (GCC): naked thunk stubs. Exported names are mapped to
// these symbols through proxy_exports.def; each stub jumps through the
// matching function pointer resolved by LoadOriginalDLL().
// GCC supports the naked attribute on x86_64 (>= GCC 8), which
// guarantees no prologue is emitted for the stubs.
"""
    for e in entries:
        if e['name'] is None:
            header += f'extern "C" __attribute__((naked)) void __proxy_ord{e["ordinal"]}(void) {{ __asm__ volatile ("jmp *orig___proxy_ord{e["ordinal"]}(%rip)"); }}\n'
            continue
        header += f'extern "C" __attribute__((naked)) void __proxy_{e["name"]}(void) {{ __asm__ volatile ("jmp *orig_{e["name"]}(%rip)"); }}\n'

    header += "#endif\n"

    # ---- LoadOriginalDLL: load every target module, resolve by module ----
    header += """
// ============================================================
// Load the target module(s) and resolve all function pointers
// Call this from DllMain(DLL_PROCESS_ATTACH)
// ============================================================
"""
    for idx, (direct, load_name) in enumerate(load_specs):
        if direct:
            c = direct.replace('\\', '\\\\')
            header += f"static HMODULE LoadOriginal_{idx}() {{ return LoadLibraryA(\"{c}\"); }}\n"
        else:
            header += f"""static HMODULE LoadOriginal_{idx}() {{
    // Get System32 directory dynamically (works on all Windows installs)
    char sysDir[MAX_PATH];
    GetSystemDirectoryA(sysDir, MAX_PATH);

    char dllPath[MAX_PATH];
    sprintf_s(dllPath, MAX_PATH, "%s\\\\{load_name}", sysDir);

    return LoadLibraryA(dllPath);
}}
"""

    header += """
inline bool LoadOriginalDLL() {
"""
    for idx in range(len(load_specs)):
        header += f"    HMODULE hOriginal_{idx} = LoadOriginal_{idx}();\n"
    header += "\n"
    for idx in range(len(load_specs)):
        header += f"    if (!hOriginal_{idx}) {{\n        return false;\n    }}\n"
    header += """
    // Resolve every pointer from the module that owns it
"""
    for e in entries:
        idx = load_specs.index((e['tgt']['load_direct'], e['tgt']['load_name']))
        if e['name'] is None:
            header += (f'    orig___proxy_ord{e["ordinal"]} = '
                       f'GetProcAddress(hOriginal_{idx}, MAKEINTRESOURCEA({e["ordinal"]}));\n')
            continue
        header += f'    orig_{e["name"]} = GetProcAddress(hOriginal_{idx}, "{e["name"]}");\n'

    header += """
    return true;
}

#endif // """ + base_name + "_RUNTIME_H\n"

    return header


def generate_runtime_def(dll_name, entries):
    """
    Generate a GNU ld .def file mapping the proxy's exported names to
    the runtime thunks (MinGW-w64 runtime mode).

    Every internal name is a real link-time symbol (__proxy_*), so GNU
    ld emits true exports of the thunk code - not forwarder entries.
    Flag semantics mirror the MSVC pragma lines: pinned ordinals,
    NONAME for ordinal-only exports, PRIVATE for COM exports.

    Args:
        dll_name: Name of the DLL (e.g., "winmm.dll")
        entries: Forwarder entries from collect_exports()

    Returns:
        String containing the runtime .def file content
    """
    lines = [
        f"; Auto-generated GNU ld export mapping for the {dll_name} runtime proxy",
        "; Generated by extract_exports.py (--def --runtime)",
        "; Each export targets a naked GNU thunk symbol defined in",
        f"; {dll_name.replace('.dll', '')}_runtime.h (resolved by LoadOriginalDLL at startup).",
        f'LIBRARY "{dll_name}"',
        "EXPORTS",
        "",
    ]

    for e in entries:
        ordinal = e['ordinal']
        if e['name'] is None:
            # Ordinal-only export: thunk + NONAME at the same ordinal
            thunk = f"__proxy_ord{ordinal}"
            lines.append(f'"{thunk}" = "{thunk}" @{ordinal} NONAME')
        else:
            thunk = f"__proxy_{e['name']}"
            line = f'"{e["name"]}" = "{thunk}"'
            if ordinal is not None:
                line += f" @{ordinal}"
            if e['private']:
                line += " PRIVATE"
            lines.append(line)

    lines.append("")
    return "\n".join(lines)


def generate_runtime_asm(dll_name, entries):
    """
    Generate MASM x64 assembly file with jump thunks for runtime forwarding.
    Each thunk is a simple indirect JMP through a function pointer.

    Args:
        dll_name: Name of the DLL (e.g., "winmm.dll")
        entries: Forwarder entries from collect_exports()

    Returns:
        String containing the ASM file content
    """
    short_name = dll_name.replace('.dll', '')
    total = len(entries)

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
    for e in entries:
        if e['name'] is None:
            asm += f"EXTERNDEF orig___proxy_ord{e['ordinal']} : QWORD\n"
        else:
            asm += f"EXTERNDEF orig_{e['name']} : QWORD\n"

    asm += "\n.code\n\n"

    # Jump thunks
    for e in entries:
        if e['name'] is None:
            o = e['ordinal']
            asm += f"__proxy_ord{o} PROC\n"
            asm += f"    jmp QWORD PTR [orig___proxy_ord{o}]\n"
            asm += f"__proxy_ord{o} ENDP\n\n"
            continue
        asm += f"__proxy_{e['name']} PROC\n"
        asm += f"    jmp QWORD PTR [orig_{e['name']}]\n"
        asm += f"__proxy_{e['name']} ENDP\n\n"

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


def process_dll(dll_arg, output_dir=None, verbose=True, use_ordinals=True,
                runtime=False, def_out=False, target_module=None,
                extra_sources=None):
    """
    Process one identity DLL (plus optional extra DLLs): extract exports,
    merge them into a single export set and generate the output files.

    Args:
        dll_arg: Path to the identity DLL file (drives the proxy name)
        output_dir: Custom output directory for generated files
        verbose: Print detailed information
        use_ordinals: Pin ordinals where available (default: True)
        runtime: Also generate runtime forwarding files
                 (.h + .asm for MSVC; .h + .def for MinGW-w64 when
                 def_out is set - GNU thunks live in the header)
        def_out: Generate GNU ld .def output (MinGW-w64) instead of the
                 MSVC pragma header
        target_module: Forward module for the identity source (default:
                 its GLOBALROOT system module)
        extra_sources: Additional DLL paths whose exports are merged in,
                 name-only, each forwarded to its own module

    Returns:
        True if successful, False otherwise
    """
    dll_path = resolve_dll_source(dll_arg)
    if dll_path is None:
        return False

    dll_name = os.path.basename(str(dll_path)).lower()

    # Build the source list: identity first, then the extra sources
    sources = [(dll_path, target_module)]
    for extra in (extra_sources or []):
        extra_path = resolve_dll_source(extra)
        if extra_path is None:
            return False
        sources.append((extra_path, None))

    if verbose:
        print(f"Processing: {dll_path} (+{len(sources) - 1} extra source(s))")

    entries, warnings = collect_exports(sources, verbose=verbose)
    if entries is None:
        print("Error: failed to extract exports")
        return False
    if not entries:
        print("Warning: no usable exports found across the given sources")
        return False

    if verbose:
        targets = []
        for e in entries:
            if e['tgt']['forward'] not in targets:
                targets.append(e['tgt']['forward'])
        print(f"Exports: {len(entries)} -> {len(targets)} target module(s)")
        for t in targets:
            print(f"  -> {t}")

    # Generate the toolchain-specific output files
    if def_out and runtime:
        # MinGW-w64 runtime bundle: runtime header (GNU naked thunks
        # included, MSVC pragmas gated out) + thunk-mapping .def.
        # No MASM assembly and no pragma/forwarder files.
        rt_header = generate_runtime_header(dll_name, entries)
        rt_header_path, _ = save_runtime_files(dll_name, rt_header, None, output_dir)
        rt_def_content = generate_runtime_def(dll_name, entries)
        rt_def_path = save_runtime_def(dll_name, rt_def_content, output_dir)

        if verbose:
            print(f"✓ Runtime header generated: {rt_header_path} (GNU thunks inside)")
            print("✓ Local build:\n"
                  "    cmake -B build -G Ninja -DCMAKE_SYSTEM_NAME=Windows "
                  f"-DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ "
                  f"-DDLL_SOURCE={dll_path} -DPROXY_METHOD=runtime")
    elif def_out:
        def_content = generate_def(dll_name, entries, use_ordinals)
        def_path = save_def(dll_name, def_content, output_dir)

        if verbose:
            print(f"✓ GNU ld def generated:    {def_path}")
            print("✓ Local build:\n"
                  "    cmake -B build -G Ninja -DCMAKE_SYSTEM_NAME=Windows "
                  f"-DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ "
                  f"-DDLL_SOURCE={dll_path}")
    else:
        header_content = generate_header(dll_name, entries, use_ordinals)
        header_path = save_header(dll_name, header_content, output_dir)

        if verbose:
            print(f"✓ Linker header generated: {header_path}")

        # Generate runtime forwarding files (MSVC/MASM, if requested)
        if runtime:
            rt_header = generate_runtime_header(dll_name, entries)
            rt_asm = generate_runtime_asm(dll_name, entries)
            rt_header_path, rt_asm_path = save_runtime_files(
                dll_name, rt_header, rt_asm, output_dir
            )

            if verbose:
                print(f"✓ Runtime header generated: {rt_header_path}")
                print(f"✓ Runtime ASM generated:    {rt_asm_path}")

    if verbose and not def_out:
        method_info = " -DPROXY_METHOD=runtime" if runtime else ""
        print(f"✓ Ready to use in CMake with -DDLL_SOURCE={dll_path}{method_info}\n")

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
        '--source',
        action='append',
        dest='extra_sources',
        metavar='DLL',
        help='Additional DLL to merge into the same proxy (repeatable). '
             'Its exports are name-only (no ordinals) and forward to its '
             'own module. The first positional file stays the identity.'
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
                            def_out=args.def_file, target_module=args.target,
                            extra_sources=args.extra_sources)
        return 0 if success else 1
    
    # No arguments provided
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
