#include <windows.h>

// ============================================================
// Export forwarding: choose between linker and runtime methods
//
// The forwarding headers are generated at CMake configure time 
// by tools/extract_exports.py, which extracts the exports
// of the requested system DLL (see DLL_TYPE) directly from the local
// Windows system files. The generated headers are published under fixed
// names in the build tree ("exports/proxy_exports*.h"), so this file
// never needs changes when a new DLL type is used.
// ============================================================
#ifdef PROXY_RUNTIME
    // Runtime forwarding: LoadLibrary + GetProcAddress + ASM thunks
    // Compatible with ALL applications including complex game engines
    #include "exports/proxy_exports_runtime.h"
#else
    // Linker forwarding: MSVC pragma directives (default)
    // Simple and clean, works for most applications
    #include "exports/proxy_exports.h"
#endif

// Payload function - your custom code goes here
DWORD WINAPI Payload(LPVOID lpParam) {
    MessageBoxA(NULL, "DLL Proxy Loaded!", "dll-proxy", MB_OK);
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD dwReason, LPVOID lpReserved) {
    switch (dwReason) {
        case DLL_PROCESS_ATTACH: {
            DisableThreadLibraryCalls(hModule); // Optimization: We don't need thread attach/detach notifications

            // Runtime forwarding: load the original DLL and resolve function pointers
            // This MUST happen before any forwarded export is called
            #ifdef PROXY_RUNTIME
            if (!LoadOriginalDLL()) {
                // Critical: if we can't load the original DLL, the process will crash
                // when any forwarded function is called (NULL function pointer)
                return FALSE;
            }
            #endif

            HANDLE hThread = CreateThread(NULL, 0, Payload, NULL, 0, NULL);
            if (hThread != NULL) {
                CloseHandle(hThread);
            }
            break;
        }
        case DLL_PROCESS_DETACH:
            // Cleanup code here (if needed)
            // For simple payloads, no cleanup is usually necessary
            break;
    }
    return TRUE;
}
