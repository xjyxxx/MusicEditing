/*
 * MusicEditing portable launcher (no console).
 * Calls: runtime\pythonw.exe client\scripts\main.pyc  (fallback: main.py)
 *
 * cl /nologo /O2 /utf-8 /Fe:MusicEditing.exe portable_launcher.c /link /SUBSYSTEM:WINDOWS user32.lib
 */
#include <windows.h>
#include <stdio.h>

static void fail(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"MusicEditing", MB_OK | MB_ICONERROR);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    (void)inst;
    (void)prev;
    (void)cmd;
    (void)show;

    wchar_t exe_path[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        fail(L"Cannot resolve app directory.");
        return 1;
    }
    for (wchar_t *p = exe_path + n; p > exe_path; --p) {
        if (*p == L'\\' || *p == L'/') {
            *(p + 1) = L'\0';
            break;
        }
    }

    wchar_t pythonw[MAX_PATH];
    wchar_t script_pyc[MAX_PATH];
    wchar_t script_py[MAX_PATH];
    wchar_t bin_dir[MAX_PATH];
    _snwprintf_s(pythonw, MAX_PATH, _TRUNCATE, L"%sruntime\\pythonw.exe", exe_path);
    _snwprintf_s(script_pyc, MAX_PATH, _TRUNCATE, L"%sclient\\scripts\\main.pyc", exe_path);
    _snwprintf_s(script_py, MAX_PATH, _TRUNCATE, L"%sclient\\scripts\\main.py", exe_path);
    _snwprintf_s(bin_dir, MAX_PATH, _TRUNCATE, L"%sbuild_x64\\bin\\Release", exe_path);

    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES) {
        fail(L"Missing runtime\\pythonw.exe\nPlease use a full portable package.");
        return 2;
    }

    const wchar_t *script = NULL;
    if (GetFileAttributesW(script_pyc) != INVALID_FILE_ATTRIBUTES) {
        script = script_pyc;
    } else if (GetFileAttributesW(script_py) != INVALID_FILE_ATTRIBUTES) {
        script = script_py;
    } else {
        fail(L"Missing client\\scripts\\main.pyc (or main.py)");
        return 3;
    }

    wchar_t old_path[32768];
    DWORD plen = GetEnvironmentVariableW(L"PATH", old_path, 32768);
    if (plen == 0 || plen >= 32768) {
        old_path[0] = L'\0';
    }
    wchar_t new_path[32768];
    _snwprintf_s(new_path, 32768, _TRUNCATE, L"%s;%s", bin_dir, old_path);
    SetEnvironmentVariableW(L"PATH", new_path);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");

    wchar_t cmdline[4096];
    _snwprintf_s(cmdline, 4096, _TRUNCATE, L"\"%s\" \"%s\"", pythonw, script);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    if (!CreateProcessW(
            pythonw, cmdline, NULL, NULL, FALSE, 0, NULL, exe_path, &si, &pi)) {
        fail(L"Failed to start runtime\\pythonw.exe\n"
             L"Install VC++ 2015-2022 x64 redistributable if needed.");
        return 4;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
