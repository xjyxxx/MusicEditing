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
    _snwprintf_s(pythonw, MAX_PATH, _TRUNCATE, L"%sruntime\\pythonw.exe", exe_path);
    _snwprintf_s(script_pyc, MAX_PATH, _TRUNCATE, L"%sclient\\scripts\\main.pyc", exe_path);
    _snwprintf_s(script_py, MAX_PATH, _TRUNCATE, L"%sclient\\scripts\\main.py", exe_path);

    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES) {
        fail(L"Missing runtime\\pythonw.exe\n"
             L"Please use a full portable package.\n"
             L"Do NOT install Visual Studio.\n"
             L"If the app flashes and exits: install VC++ Redistributable x64\n"
             L"(small runtime, not Visual Studio).");
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

    /* 勿把引擎 bin 塞进 Python PATH（会与 PySide6 FFmpeg 混载导致播放跳片尾）。
     * media_player / media_cli 在各自 Popen 里单独 prepend exe 目录。 */
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    /* Windows 多媒体后端，避开 Qt FFmpeg 插件与引擎 av*.dll 冲突 */
    SetEnvironmentVariableW(L"QT_MEDIA_BACKEND", L"windows");

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
             L"1) Do NOT install Visual Studio\n"
             L"2) If flash-exit: install VC++ Redistributable x64 (small runtime)\n"
             L"3) If SmartScreen blocked the zip, unblock / re-extract\n"
             L"4) Try 「启动 MusicEditing.bat」");
        return 4;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
