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

# DLL_TYPE parameter (user must specify which DLL to build)
set(DLL_TYPE "version" CACHE STRING "Type of DLL to build (version, winmm, etc)")
set_property(CACHE DLL_TYPE PROPERTY STRINGS version winmm winhttp wininet)

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

# Validate DLL_TYPE and set export header + ASM sources
if(DLL_TYPE STREQUAL "version")
    set(OUTPUT_NAME "version")
    if(PROXY_METHOD STREQUAL "runtime")
        set(EXPORT_HEADER "src/exports/version_runtime.h")
        set(ASM_SOURCE "src/exports/version_runtime.asm")
        message(STATUS "Building version.dll proxy (RUNTIME forwarding)")
    else()
        set(EXPORT_HEADER "src/exports/version.h")
        message(STATUS "Building version.dll proxy (LINKER forwarding)")
    endif()
elseif(DLL_TYPE STREQUAL "winmm")
    set(OUTPUT_NAME "winmm")
    if(PROXY_METHOD STREQUAL "runtime")
        set(EXPORT_HEADER "src/exports/winmm_runtime.h")
        set(ASM_SOURCE "src/exports/winmm_runtime.asm")
        message(STATUS "Building winmm.dll proxy (RUNTIME forwarding)")
    else()
        set(EXPORT_HEADER "src/exports/winmm.h")
        message(STATUS "Building winmm.dll proxy (LINKER forwarding)")
    endif()
elseif(DLL_TYPE STREQUAL "winhttp")
    set(OUTPUT_NAME "winhttp")
    if(PROXY_METHOD STREQUAL "runtime")
        set(EXPORT_HEADER "src/exports/winhttp_runtime.h")
        set(ASM_SOURCE "src/exports/winhttp_runtime.asm")
        message(STATUS "Building winhttp.dll proxy (RUNTIME forwarding)")
    else()
        set(EXPORT_HEADER "src/exports/winhttp.h")
        message(STATUS "Building winhttp.dll proxy (LINKER forwarding)")
    endif()
elseif(DLL_TYPE STREQUAL "wininet")
    set(OUTPUT_NAME "wininet")
    if(PROXY_METHOD STREQUAL "runtime")
        set(EXPORT_HEADER "src/exports/wininet_runtime.h")
        set(ASM_SOURCE "src/exports/wininet_runtime.asm")
        message(STATUS "Building wininet.dll proxy (RUNTIME forwarding)")
    else()
        set(EXPORT_HEADER "src/exports/wininet.h")
        message(STATUS "Building wininet.dll proxy (LINKER forwarding)")
    endif()
else()
    message(FATAL_ERROR "Invalid DLL_TYPE: ${DLL_TYPE}. "
                        "Supported types: version, winmm, winhttp, wininet")
endif()

# Verify export header exists
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${EXPORT_HEADER}")
    message(FATAL_ERROR "Export header not found: ${EXPORT_HEADER}\n"
                        "Please ensure the export header exists for DLL type: ${DLL_TYPE}")
endif()

# Verify ASM source exists for runtime mode
if(PROXY_METHOD STREQUAL "runtime")
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${ASM_SOURCE}")
        message(FATAL_ERROR "ASM thunks not found: ${ASM_SOURCE}\n"
                            "Generate runtime files with: python extract_exports.py ${DLL_TYPE}.dll --runtime")
    endif()
endif()

# Create shared library (DLL)
# For runtime mode, include the ASM thunk source
if(PROXY_METHOD STREQUAL "runtime")
    add_library(${OUTPUT_NAME} SHARED main.cpp ${ASM_SOURCE})
else()
    add_library(${OUTPUT_NAME} SHARED main.cpp)
endif()

# Set output name to match DLL type
set_target_properties(${OUTPUT_NAME} PROPERTIES
    OUTPUT_NAME ${OUTPUT_NAME}
    SUFFIX ".dll"
    PREFIX ""
)

# Add compile definitions (DLL_TYPE_<type> for conditional compilation)
target_compile_definitions(${OUTPUT_NAME} PRIVATE
    DLL_TYPE_${DLL_TYPE}
)

# Add PROXY_RUNTIME definition for runtime forwarding mode
if(PROXY_METHOD STREQUAL "runtime")
    target_compile_definitions(${OUTPUT_NAME} PRIVATE PROXY_RUNTIME)
endif()

# Set C++ standard
target_compile_features(${OUTPUT_NAME} PRIVATE cxx_std_17)

# MSVC-specific compiler flags (scoped to C++ only, not MASM)
if(MSVC)
    target_compile_options(${OUTPUT_NAME} PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:/W4>              # Warning level 4
        $<$<COMPILE_LANGUAGE:CXX>:/WX->             # Don't treat warnings as errors
        $<$<COMPILE_LANGUAGE:CXX>:/permissive->     # Standards conformance mode
        $<$<COMPILE_LANGUAGE:CXX>:/Zc:__cplusplus>  # Enable correct __cplusplus macro
    )
    
    # Release optimizations (C++ only)
    target_compile_options(${OUTPUT_NAME} PRIVATE
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:CXX>>:/O2>      # Maximum optimization
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:CXX>>:/GL>      # Whole program optimization
    )
    
    # Release linker optimizations
    target_link_options(${OUTPUT_NAME} PRIVATE
        $<$<CONFIG:Release>:/LTCG>    # Link-time code generation
        $<$<CONFIG:Release>:/OPT:REF> # Remove unreferenced functions/data
        $<$<CONFIG:Release>:/OPT:ICF> # Enable COMDAT folding
    )
    
    # Static linking of MSVC runtime (no external DLL dependencies)
    set_property(TARGET ${OUTPUT_NAME} PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

# Include directories (for export headers)
target_include_directories(${OUTPUT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# Print build information
message(STATUS "")
message(STATUS "===== dll-proxy Build Configuration =====")
message(STATUS "DLL Type:        ${DLL_TYPE}")
message(STATUS "Proxy Method:    ${PROXY_METHOD}")
message(STATUS "Output Name:     ${OUTPUT_NAME}.dll")
message(STATUS "Export Header:   ${EXPORT_HEADER}")
if(PROXY_METHOD STREQUAL "runtime")
    message(STATUS "ASM Thunks:      ${ASM_SOURCE}")
endif()
message(STATUS "Compiler:        ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "Build Type:      ${CMAKE_BUILD_TYPE}")
message(STATUS "========================================")
message(STATUS "")
