#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace media::common {

/// 跨进程 RGB 帧共享内存（Windows 命名映射；Python mmap tagname 同名打开）
class FrameSharedMemory {
public:
    FrameSharedMemory() = default;
    ~FrameSharedMemory() { close(); }

    FrameSharedMemory(const FrameSharedMemory&) = delete;
    FrameSharedMemory& operator=(const FrameSharedMemory&) = delete;

    /// 打开已由对端创建的命名共享内存（只写映射）
    bool open(const std::string& name, size_t capacity);
    void close();

    bool isOpen() const { return view_ != nullptr; }
    uint8_t* data() { return static_cast<uint8_t*>(view_); }
    const uint8_t* data() const { return static_cast<const uint8_t*>(view_); }
    size_t capacity() const { return capacity_; }
    const std::string& name() const { return name_; }

    /// 写入紧密打包 RGB24（自动按行拷贝去除 stride）
    bool writePackedRgb(const uint8_t* src, int width, int height, int srcStride);

private:
    std::string name_;
    size_t capacity_ = 0;
    void* mapping_ = nullptr; // HANDLE on Windows
    void* view_ = nullptr;
};

} // namespace media::common
