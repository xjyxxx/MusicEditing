#pragma once

#if defined(_WIN32)
    #if defined(MEDIA_SHARED_EXPORTS)
        #define MEDIA_API __declspec(dllexport)
    #else
        #define MEDIA_API __declspec(dllimport)
    #endif
#else
    #define MEDIA_API __attribute__((visibility("default")))
#endif
