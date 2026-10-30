cmake_minimum_required(VERSION 3.15)
project(dll-proxy LANGUAGES CXX)

# MinGW-w64 cross-build detection (GNU compiler targeting Windows).
# Enabled by: cmake -B build -DCMAKE_SYSTEM_NAME=Windows ... x86_64-w64-mingw32-g++
if(DEFINED CMAKE_CXX_COMPILER_ID AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND WIN32)
    set(IS_MINGW_BUILD TRUE)
endif()

# Toolchain support: MSVC (native Windows) and MinGW-w64 cross-builds
# from Linux. Everything else is unsupported.
if(NOT MSVC AND NOT IS_MINGW_BUILD)
    message(FATAL_ERROR "Unsupported toolchain configuration.\n"
            "\n"
            "Supported setups:\n"
            "  - MSVC on Windows (all forwarding methods)\n"
            "  - MinGW-w64 cross-builds on Linux (all forwarding methods):\n"
            "      cmake -B build -DCMAKE_SYSTEM_NAME=Windows \\\n"
            "            -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \\\n"
            "            -DDLL_TYPE=version.dll \\\n"
            "            [-DDLL_SOURCE=/path/to/the/system/version.dll]\n"
            "\n"
            "Current toolchain: ${CMAKE_CXX_COMPILER_ID} targeting "
            "${CMAKE_SYSTEM_NAME} (WIN32=${WIN32}).")
endif()

# DLL_TYPE parameter: the file name of ANY x64 system DLL to proxy.
# Pass the DLL file name (e.g. "winmm.dll"); exports are extracted at
# configure time from the local Windows system files (System32), or from
# DLL_SOURCE on hosts that cannot read them (Linux cross-builds).
set(DLL_TYPE "version.dll" CACHE STRING "System DLL file name to proxy (e.g. version.dll, winmm.dll)")

# PROXY_METHOD parameter: linker (default) or runtime
# - linker: PE-level forwarder exports, no runtime code
#   (MSVC: #pragma comment(linker, ...) / MinGW: generated .def file)
# - runtime: LoadLibrary + GetProcAddress + jump thunks
#   (required for complex applications/game engines)
set(PROXY_METHOD "linker" CACHE STRING "Export forwarding method (linker or runtime)")
set_property(CACHE PROXY_METHOD PROPERTY STRINGS linker runtime)

# Validate PROXY_METHOD
if(NOT PROXY_METHOD STREQUAL "linker" AND NOT PROXY_METHOD STREQUAL "runtime")
    message(FATAL_ERROR "Invalid PROXY_METHOD: ${PROXY_METHOD}. "
                        "Supported methods: linker, runtime")
endif()

# MSVC runtime builds need the MASM assembler (thunks in a .asm file);
# MinGW builds use GNU thunks inside the runtime header instead.
if(PROXY_METHOD STREQUAL "runtime" AND NOT IS_MINGW_BUILD)
    enable_language(ASM_MASM)
endif()

# Note: Windows' own files are located via GLOBALROOT\SystemRoot, which
# resolves regardless of the installation drive - the same path the proxy
# then forwards to at runtime.

# Normalize DLL_TYPE: reject paths first, then strip the ".dll" suffix
get_filename_component(DLL_NODIR "${DLL_TYPE}" NAME)
if(NOT DLL_NODIR STREQUAL "${DLL_TYPE}")
    message(FATAL_ERROR "Invalid DLL_TYPE: '${DLL_TYPE}'. "
                        "Pass just the DLL file name (e.g. 'winmm.dll'), not a path.")
endif()

get_filename_component(DLL_NAME "${DLL_TYPE}" NAME_WLE)
get_filename_component(DLL_EXT "${DLL_TYPE}" LAST_EXT)
string(TOLOWER "${DLL_EXT}" DLL_EXT)

# Validate the DLL name (target file name + generated headers use it)
if(NOT DLL_NAME MATCHES "^[A-Za-z0-9_]+$" OR NOT DLL_EXT STREQUAL ".dll")
    message(FATAL_ERROR "Invalid DLL_TYPE: '${DLL_TYPE}'. "
                        "Pass just the DLL file name, e.g. 'winmm.dll' "
                        "(letters, digits and underscores).")
endif()
set(DLL_FILE_NAME "${DLL_NAME}.dll")

# DLL_SOURCE parameter: explicit path to the source DLL for export
# extraction. Required on hosts that cannot read the Windows system
# files directly (e.g. Linux cross-builds using a local copy); at
# runtime the proxy still targets the DLL_FILE_NAME system module.
set(DLL_SOURCE "" CACHE FILEPATH
    "Explicit source DLL path for export extraction (Linux cross-builds)")

# Python is required for the build-time export extraction
find_package(Python3 REQUIRED COMPONENTS Interpreter)

# Ensure 'pefile' is available for the interpreter CMake found. The 'python'
# on PATH may be a different installation from the one find_package() picks,
# so installing via the PATH python is not reliable; check and self-provision
# when missing.
execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c
        "import sys, importlib.util as u; sys.exit(0 if u.find_spec('pefile') else 1)"
    RESULT_VARIABLE PEFILE_CHECK
)
# pefile is required by tools/extract_exports.py. When the interpreter
# CMake found does not have it, never touch the system/user Python:
# an isolated venv is created inside the build tree and pefile is
# installed there. System-wide Python stays untouched, and PEP 668
# locked distributions (Arch/Artix/Fedora/...) work without any flags.
set(EXTRACT_PYTHON "${Python3_EXECUTABLE}")
if(NOT PEFILE_CHECK EQUAL 0)
    message(STATUS "pefile not found for ${Python3_EXECUTABLE}; "
                   "setting up an isolated 'tooling_venv' inside the build tree...")
    set(TOOLING_VENV "${CMAKE_BINARY_DIR}/tooling_venv")
    if(CMAKE_HOST_UNIX)
        set(TOOLING_VENV_PY "${TOOLING_VENV}/bin/python")
    else()
        set(TOOLING_VENV_PY "${TOOLING_VENV}/Scripts/python.exe")
    endif()
    if(NOT EXISTS "${TOOLING_VENV}/pyvenv.cfg")
        execute_process(
            COMMAND "${Python3_EXECUTABLE}" -m venv "${TOOLING_VENV}"
            RESULT_VARIABLE VENV_CREATE
        )
        if(NOT VENV_CREATE EQUAL 0)
            message(FATAL_ERROR "Failed to create the build-time Python venv "
                                "'${TOOLING_VENV}'.\n"
                                "Hints:\n"
                                "  - Debian/Ubuntu require the python3-venv package:\n"
                                "      sudo apt install python3-venv\n"
                                "  - Or pass a Python that already has pefile:\n"
                                "      -DPython3_EXECUTABLE=/path/to/venv/bin/python")
        endif()
    endif()
    # Install pefile into the venv only if it is not there already
    execute_process(
        COMMAND "${TOOLING_VENV_PY}" -c
            "import sys, importlib.util as u; sys.exit(0 if u.find_spec('pefile') else 1)"
        RESULT_VARIABLE VENV_PEFILE_CHECK
    )
    if(NOT VENV_PEFILE_CHECK EQUAL 0)
        execute_process(
            COMMAND "${TOOLING_VENV_PY}" -m pip install pefile
            RESULT_VARIABLE VENV_PIP
        )
        if(NOT VENV_PIP EQUAL 0)
            message(FATAL_ERROR "Failed to install 'pefile' into the build-tree "
                                "venv '${TOOLING_VENV_PY}'.\n"
                                "Hints:\n"
                                "  - Usually a network/proxy issue downloading the wheel.\n"
                                "  - Run \"${TOOLING_VENV_PY} -m pip install pefile\" "
                                "manually to see the full error.")
        endif()
    endif()
    set(EXTRACT_PYTHON "${TOOLING_VENV_PY}")
    message(STATUS "Using isolated build-time Python: ${EXTRACT_PYTHON}")
endif()

set(EXTRACT_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/tools/extract_exports.py")
set(GEN_DIR "${CMAKE_BINARY_DIR}/exports")
set(GEN_HEADER "${GEN_DIR}/proxy_exports.h")
set(GEN_HEADER_RUNTIME "${GEN_DIR}/proxy_exports_runtime.h")

# Generate the export forwarding files
# (always verbose so the configure log shows the extracted export list)
file(MAKE_DIRECTORY "${GEN_DIR}")
set(GEN_ARGS "")
if(IS_MINGW_BUILD)
    list(APPEND GEN_ARGS --def)
endif()
if(PROXY_METHOD STREQUAL "runtime")
    list(APPEND GEN_ARGS --runtime)
endif()

# Linux cross-builds must be given an explicit local copy of the system DLL;
# Windows hosts (MSVC) read it straight from System32.
set(EXTRACT_INPUT "${DLL_FILE_NAME}")
if(DLL_SOURCE)
    if(NOT EXISTS "${DLL_SOURCE}")
        message(FATAL_ERROR "DLL_SOURCE '${DLL_SOURCE}' does not exist.")
    endif()
    set(EXTRACT_INPUT "${DLL_SOURCE}")
endif()
if(IS_MINGW_BUILD AND NOT DLL_SOURCE)
    message(FATAL_ERROR "MinGW-w64 cross-builds need the source DLL file explicitly:\n"
                        "  -DDLL_SOURCE=/path/to/${DLL_FILE_NAME}\n"
                        "(on Windows MSVC builds it is read from System32 directly).")
endif()
execute_process(
    COMMAND "${EXTRACT_PYTHON}" "${EXTRACT_SCRIPT}" "${EXTRACT_INPUT}" ${GEN_ARGS} -o "${GEN_DIR}"
    RESULT_VARIABLE GEN_RESULT
)
if(NOT GEN_RESULT EQUAL 0)
    message(FATAL_ERROR "Failed to extract exports of '${DLL_FILE_NAME}'.\n"
                        "Hints:\n"
                        "  - Make sure the DLL name is spelled correctly (e.g. 'winmm.dll', not 'winnm.dll').\n"
                        "  - The DLL must be an x64 file inside System32 (Windows MSVC hosts)\n"
                        "    or inside DLL_SOURCE (Linux cross-builds).\n"
                        "  - CMake installs pefile into an isolated build-tree venv automatically\n"
                        "    (${EXTRACT_PYTHON}); try it manually to see the full error.\n"
                        "  - Try manually: ${EXTRACT_PYTHON} tools/extract_exports.py ${EXTRACT_INPUT} ${GEN_ARGS}")
endif()

# Verify the output file exists (paranoia before it enters the build)
if(IS_MINGW_BUILD)
    # MinGW: exports are wired through a generated .def file - forwarder
    # entries (linker method) or thunk-mapping entries (runtime method).
    set(GEN_DEFSRC "${GEN_DIR}/${DLL_NAME}.def")
    if(PROXY_METHOD STREQUAL "runtime")
        set(GEN_DEFSRC "${GEN_DIR}/${DLL_NAME}_runtime.def")
    endif()
    if(NOT EXISTS "${GEN_DEFSRC}")
        message(FATAL_ERROR "Export generation did not produce '${GEN_DEFSRC}'")
    endif()
else()
    set(GEN_OUTPUT_CANDIDATE "${GEN_DIR}/${DLL_NAME}.h")
    if(NOT EXISTS "${GEN_OUTPUT_CANDIDATE}")
        message(FATAL_ERROR "Export generation did not produce '${GEN_OUTPUT_CANDIDATE}'")
    endif()
endif()

# Publish generated files under fixed include names so main.cpp needs no
# per-DLL branching; this is what makes DLL_TYPE fully dynamic.
set(GEN_DEF "${GEN_DIR}/proxy_exports.def")
if(IS_MINGW_BUILD)
    configure_file("${GEN_DEFSRC}" "${GEN_DEF}" COPYONLY)
else()
    configure_file("${GEN_DIR}/${DLL_NAME}.h" "${GEN_HEADER}" COPYONLY)
endif()

# Verify the runtime header exists for runtime mode and publish it under
# the fixed include name
set(PROXY_SOURCES main.cpp)
if(PROXY_METHOD STREQUAL "runtime")
    if(NOT EXISTS "${GEN_DIR}/${DLL_NAME}_runtime.h")
        message(FATAL_ERROR "Runtime generation did not produce '${GEN_DIR}/${DLL_NAME}_runtime.h'")
    endif()
    configure_file("${GEN_DIR}/${DLL_NAME}_runtime.h" "${GEN_HEADER_RUNTIME}" COPYONLY)
    if(NOT IS_MINGW_BUILD)
        # MSVC: MASM jump thunks in a dedicated assembly file
        set(ASM_SOURCE "${GEN_DIR}/${DLL_NAME}_runtime.asm")
        if(NOT EXISTS "${ASM_SOURCE}")
            message(FATAL_ERROR "Runtime generation did not produce '${ASM_SOURCE}'")
        endif()
        list(APPEND PROXY_SOURCES "${ASM_SOURCE}")
    endif()
    # MinGW: thunks are GNU naked stubs inside the runtime header itself
endif()

# Create shared library (DLL)
add_library(${DLL_NAME} SHARED ${PROXY_SOURCES})

# Set output name to match the DLL type
set_target_properties(${DLL_NAME} PROPERTIES
    OUTPUT_NAME ${DLL_NAME}
    SUFFIX ".dll"
    PREFIX ""
)

# Set C++ standard
target_compile_features(${DLL_NAME} PRIVATE cxx_std_17)

# Add PROXY_RUNTIME definition for runtime forwarding mode
if(PROXY_METHOD STREQUAL "runtime")
    target_compile_definitions(${DLL_NAME} PRIVATE PROXY_RUNTIME)
endif()

# MinGW-w64 cross-build flags: forward the exports through the generated
# .def file (GNU ld resolves "NAME = MODULE.EXTERNAL" lines into forwarder
# exports); keep the C/C++ runtime statically linked to the proxy itself.
if(IS_MINGW_BUILD)
    target_compile_options(${DLL_NAME} PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:-Wall>  # warnings on, not treated as errors
    )
    target_link_options(${DLL_NAME} PRIVATE
        -static-libgcc
        -static-libstdc++
    )
    # GNU ld takes .def files as regular link inputs and parses
    # LIBRARY/EXPORTS from them natively (ld/deffilep.y).
    target_link_libraries(${DLL_NAME} PRIVATE "${GEN_DEF}")
endif()

# MSVC-specific compiler flags (scoped to C++ only, not MASM)
if(MSVC)
    target_compile_options(${DLL_NAME} PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:/W4>              # Warning level 4
        $<$<COMPILE_LANGUAGE:CXX>:/WX->             # Don't treat warnings as errors
        $<$<COMPILE_LANGUAGE:CXX>:/permissive->     # Standards conformance mode
        $<$<COMPILE_LANGUAGE:CXX>:/Zc:__cplusplus>  # Enable correct __cplusplus macro
    )
    
    # Release optimizations (C++ only)
    target_compile_options(${DLL_NAME} PRIVATE
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:CXX>>:/O2>      # Maximum optimization
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:CXX>>:/GL>      # Whole program optimization
    )
    
    # Release linker optimizations
    target_link_options(${DLL_NAME} PRIVATE
        $<$<CONFIG:Release>:/LTCG>    # Link-time code generation
        $<$<CONFIG:Release>:/OPT:REF> # Remove unreferenced functions/data
        $<$<CONFIG:Release>:/OPT:ICF> # Enable COMDAT folding
    )
    
    # Static linking of MSVC runtime (no external DLL dependencies)
    set_property(TARGET ${DLL_NAME} PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

# Include directories:
# - project root for main.cpp
# - build tree for the generated export files ("exports/proxy_exports*")
target_include_directories(${DLL_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}
)

# Print build information
message(STATUS "")
message(STATUS "===== dll-proxy Build Configuration =====")
message(STATUS "DLL Type:        ${DLL_NAME} (proxying System32\\${DLL_FILE_NAME})")
message(STATUS "Proxy Method:    ${PROXY_METHOD}")
if(IS_MINGW_BUILD)
    if(PROXY_METHOD STREQUAL "runtime")
        message(STATUS "Exports File:    exports/proxy_exports.def (thunk mapping, runtime method)")
    else()
        message(STATUS "Exports File:    exports/proxy_exports.def (GNU ld forwarders)")
    endif()
else()
    message(STATUS "Generated Exports: exports/proxy_exports.h (MSVC linker directives)")
endif()
if(PROXY_METHOD STREQUAL "runtime")
    if(IS_MINGW_BUILD)
        message(STATUS "Thunks:          GNU naked stubs in exports/proxy_exports_runtime.h")
    else()
        message(STATUS "ASM Thunks:      exports/${DLL_NAME}_runtime.asm")
    endif()
endif()
message(STATUS "Compiler:        ${CMAKE_CXX_COMPILER_ID} (${CMAKE_CXX_COMPILER})")
message(STATUS "Build Type:      ${CMAKE_BUILD_TYPE}")
message(STATUS "========================================")
message(STATUS "")
