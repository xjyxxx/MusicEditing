#include "common/frame_shm.h"

#include "common/logger.h"

#include <cstring>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

namespace media::common {

bool FrameSharedMemory::open(const std::string& name, size_t capacity) {
    close();
    if (name.empty() || capacity == 0) {
        return false;
    }
#ifdef _WIN32
    HANDLE h = OpenFileMappingA(FILE_MAP_WRITE, FALSE, name.c_str());
    if (!h) {
        LOG_ERROR("OpenFileMapping 失败 name=" + name
            + " err=" + std::to_string(GetLastError()));
        return false;
    }
    void* view = MapViewOfFile(h, FILE_MAP_WRITE, 0, 0, capacity);
    if (!view) {
        LOG_ERROR("MapViewOfFile 失败 err=" + std::to_string(GetLastError()));
        CloseHandle(h);
        return false;
    }
    mapping_ = h;
    view_ = view;
    name_ = name;
    capacity_ = capacity;
    LOG_INFO("SHM 已打开 name=" + name + " capacity=" + std::to_string(capacity));
    return true;
#else
    (void)name;
    (void)capacity;
    LOG_ERROR("FrameSharedMemory 仅支持 Windows");
    return false;
#endif
}

void FrameSharedMemory::close() {
#ifdef _WIN32
    if (view_) {
        UnmapViewOfFile(view_);
        view_ = nullptr;
    }
    if (mapping_) {
        CloseHandle(static_cast<HANDLE>(mapping_));
        mapping_ = nullptr;
    }
#else
    view_ = nullptr;
    mapping_ = nullptr;
#endif
    name_.clear();
    capacity_ = 0;
}

bool FrameSharedMemory::writePackedRgb(
    const uint8_t* src, int width, int height, int srcStride) {
    if (!view_ || !src || width <= 0 || height <= 0) {
        return false;
    }
    const size_t rowBytes = static_cast<size_t>(width) * 3u;
    const size_t need = rowBytes * static_cast<size_t>(height);
    if (need > capacity_) {
        LOG_ERROR("SHM 容量不足 need=" + std::to_string(need)
            + " cap=" + std::to_string(capacity_));
        return false;
    }
    auto* dst = static_cast<uint8_t*>(view_);
    if (srcStride == static_cast<int>(rowBytes)) {
        std::memcpy(dst, src, need);
        return true;
    }
    for (int y = 0; y < height; ++y) {
        std::memcpy(
            dst + static_cast<size_t>(y) * rowBytes,
            src + static_cast<ptrdiff_t>(y) * srcStride,
            rowBytes);
    }
    return true;
}

} // namespace media::common
