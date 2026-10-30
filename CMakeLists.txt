cmake_minimum_required(VERSION 3.15)
project(dll-proxy LANGUAGES CXX)

# Enforce MSVC compiler only
if(NOT MSVC)
    message(FATAL_ERROR "This project requires MSVC (Microsoft Visual C++ Compiler). "
                        "MinGW-w64 and other compilers are not supported because "
                        "we use MSVC-specific #pragma comment(linker, ...) directives. "
                        "\n\n"
                        "For Linux users: Use GitHub Actions to build with MSVC in the cloud.")
endif()

# DLL_TYPE parameter: the file name of ANY x64 system DLL to proxy.
# Pass the DLL file name (e.g. "winmm.dll"); exports are extracted from the
# local Windows system files at configure time.
set(DLL_TYPE "version.dll" CACHE STRING "System DLL file name to proxy (e.g. version.dll, winmm.dll)")

# PROXY_METHOD parameter: linker (default) or runtime
# - linker: Uses MSVC pragma export forwarding (simple, works for most apps)
# - runtime: Uses LoadLibrary + GetProcAddress + ASM thunks (required for complex applications)
set(PROXY_METHOD "linker" CACHE STRING "Export forwarding method (linker or runtime)")
set_property(CACHE PROXY_METHOD PROPERTY STRINGS linker runtime)

# Validate PROXY_METHOD
if(NOT PROXY_METHOD STREQUAL "linker" AND NOT PROXY_METHOD STREQUAL "runtime")
    message(FATAL_ERROR "Invalid PROXY_METHOD: ${PROXY_METHOD}. "
                        "Supported methods: linker, runtime")
endif()

# Enable MASM assembler if runtime mode is selected
if(PROXY_METHOD STREQUAL "runtime")
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

# Python is required for the build-time export extraction
find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(EXTRACT_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/tools/extract_exports.py")
set(GEN_DIR "${CMAKE_BINARY_DIR}/exports")
set(GEN_HEADER "${GEN_DIR}/proxy_exports.h")
set(GEN_HEADER_RUNTIME "${GEN_DIR}/proxy_exports_runtime.h")

# Generate the export forwarding files from the local system DLL
# (always verbose so CI logs show the extracted export list)
file(MAKE_DIRECTORY "${GEN_DIR}")
set(GEN_ARGS "")
if(PROXY_METHOD STREQUAL "runtime")
    list(APPEND GEN_ARGS --runtime)
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${EXTRACT_SCRIPT}" "${DLL_FILE_NAME}" ${GEN_ARGS} -o "${GEN_DIR}"
    RESULT_VARIABLE GEN_RESULT
)
if(NOT GEN_RESULT EQUAL 0)
    message(FATAL_ERROR "Failed to extract exports of '${DLL_FILE_NAME}' from your system files.\n"
                        "Hints:\n"
                        "  - Make sure the DLL name is spelled correctly (e.g. 'winmm.dll', not 'winnm.dll').\n"
                        "  - The DLL must be an x64 file inside System32.\n"
                        "  - Python needs the 'pefile' package: python -m pip install pefile\n"
                        "  - Try manually: python tools/extract_exports.py ${DLL_FILE_NAME}")
endif()

# Verify the output files exist (paranoia before they enter the build)
if(NOT EXISTS "${GEN_DIR}/${DLL_NAME}.h")
    message(FATAL_ERROR "Export generation did not produce '${GEN_DIR}/${DLL_NAME}.h'")
endif()

# Publish generated files under fixed include names so main.cpp needs no
# per-DLL branching; this is what makes DLL_TYPE fully dynamic.
configure_file("${GEN_DIR}/${DLL_NAME}.h" "${GEN_HEADER}" COPYONLY)

# Verify ASM source exists for runtime mode and copy its header under fixed name
set(PROXY_SOURCES main.cpp)
if(PROXY_METHOD STREQUAL "runtime")
    set(ASM_SOURCE "${GEN_DIR}/${DLL_NAME}_runtime.asm")
    if(NOT EXISTS "${ASM_SOURCE}")
        message(FATAL_ERROR "Runtime generation did not produce '${ASM_SOURCE}'")
    endif()
    configure_file("${GEN_DIR}/${DLL_NAME}_runtime.h" "${GEN_HEADER_RUNTIME}" COPYONLY)
    list(APPEND PROXY_SOURCES "${ASM_SOURCE}")
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
# - build tree for generated exports ("exports/proxy_exports*.h")
target_include_directories(${DLL_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}
)

# Print build information
message(STATUS "")
message(STATUS "===== dll-proxy Build Configuration =====")
message(STATUS "DLL Type:        ${DLL_NAME} (proxying System32\\${DLL_FILE_NAME})")
message(STATUS "Proxy Method:    ${PROXY_METHOD}")
message(STATUS "Output Name:     ${DLL_NAME}.dll")
message(STATUS "Generated Exports: exports/proxy_exports.h (from local system files)")
if(PROXY_METHOD STREQUAL "runtime")
    message(STATUS "ASM Thunks:      exports/${DLL_NAME}_runtime.asm")
endif()
message(STATUS "Compiler:        ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "Build Type:      ${CMAKE_BUILD_TYPE}")
message(STATUS "========================================")
message(STATUS "")
