#include <windows.h>

// ============================================================
// Export forwarding: choose between linker and runtime methods
// ============================================================
#if defined(PROXY_RUNTIME)
    // Runtime forwarding: LoadLibrary + GetProcAddress + ASM thunks
    // Compatible with ALL applications including complex game engines
    #if defined(DLL_TYPE_version)
        #include "src/exports/version_runtime.h"
    #elif defined(DLL_TYPE_winmm)
        #include "src/exports/winmm_runtime.h"
    #elif defined(DLL_TYPE_winhttp)
        #include "src/exports/winhttp_runtime.h"
    #elif defined(DLL_TYPE_wininet)
        #include "src/exports/wininet_runtime.h"
    #else
        #error "DLL_TYPE not defined. Please specify -DDLL_TYPE=<type> in CMake."
    #endif
#else
    // Linker forwarding: MSVC pragma directives (default)
    // Simple and clean, works for most applications
    #if defined(DLL_TYPE_version)
        #include "src/exports/version.h"
    #elif defined(DLL_TYPE_winmm)
        #include "src/exports/winmm.h"
    #elif defined(DLL_TYPE_winhttp)
        #include "src/exports/winhttp.h"
    #elif defined(DLL_TYPE_wininet)
        #include "src/exports/wininet.h"
    #else
        #error "DLL_TYPE not defined. Please specify -DDLL_TYPE=<type> in CMake."
    #endif
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
