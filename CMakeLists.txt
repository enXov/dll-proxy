cmake_minimum_required(VERSION 3.15)
project(dll-proxy LANGUAGES CXX)

# Set default build type to Release for minimal size
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

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
set_property(CACHE DLL_TYPE PROPERTY STRINGS version winmm)

# Validate DLL_TYPE and set export header
if(DLL_TYPE STREQUAL "version")
    set(EXPORT_HEADER "src/exports/version.h")
    set(OUTPUT_NAME "version")
    message(STATUS "Building version.dll proxy")
elseif(DLL_TYPE STREQUAL "winmm")
    set(EXPORT_HEADER "src/exports/winmm.h")
    set(OUTPUT_NAME "winmm")
    message(STATUS "Building winmm.dll proxy")
else()
    message(FATAL_ERROR "Invalid DLL_TYPE: ${DLL_TYPE}. "
                        "Supported types: version, winmm")
endif()

# Verify export header exists
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${EXPORT_HEADER}")
    message(FATAL_ERROR "Export header not found: ${EXPORT_HEADER}\n"
                        "Please ensure the export header exists for DLL type: ${DLL_TYPE}")
endif()

# Create shared library (DLL)
add_library(${OUTPUT_NAME} SHARED main.cpp)

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

# Set C++ standard
target_compile_features(${OUTPUT_NAME} PRIVATE cxx_std_17)

# MSVC-specific compiler flags
if(MSVC)
    target_compile_options(${OUTPUT_NAME} PRIVATE
        /W4              # Warning level 4
        /WX-             # Don't treat warnings as errors (some Windows SDK warnings)
        /permissive-     # Standards conformance mode
        /Zc:__cplusplus  # Enable correct __cplusplus macro
    )
    
    # Release optimizations for minimal size
    target_compile_options(${OUTPUT_NAME} PRIVATE
        $<$<CONFIG:Release>:/O1>      # Minimize size (changed from /O2)
        $<$<CONFIG:Release>:/GL>      # Whole program optimization
        $<$<CONFIG:Release>:/Gy>      # Enable function-level linking
    )
    
    # Release linker optimizations for minimal size
    target_link_options(${OUTPUT_NAME} PRIVATE
        $<$<CONFIG:Release>:/LTCG>       # Link-time code generation
        $<$<CONFIG:Release>:/OPT:REF>    # Remove unreferenced functions/data
        $<$<CONFIG:Release>:/OPT:ICF>    # Enable COMDAT folding
        $<$<CONFIG:Release>:/INCREMENTAL:NO> # Disable incremental linking
        $<$<CONFIG:Release>:/RELEASE>    # Set checksum in PE header
    )
    
    # Explicitly disable debug info generation in Release
    set_target_properties(${OUTPUT_NAME} PROPERTIES
        COMPILE_PDB_NAME ""
        COMPILE_PDB_OUTPUT_DIRECTORY ""
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
message(STATUS "Output Name:     ${OUTPUT_NAME}.dll")
message(STATUS "Export Header:   ${EXPORT_HEADER}")
message(STATUS "Compiler:        ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "Build Type:      ${CMAKE_BUILD_TYPE}")
message(STATUS "========================================")
message(STATUS "")

