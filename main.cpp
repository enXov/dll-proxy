#include <windows.h>

#if defined(DLL_TYPE_version)
    #include "src/exports/version.h"
#elif defined(DLL_TYPE_winmm)
    #include "src/exports/winmm.h"
#else
    #error "DLL_TYPE not defined. Please specify -DDLL_TYPE=<type> in CMake."
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

