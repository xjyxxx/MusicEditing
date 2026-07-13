"""播放器音频诊断脚本"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client", "scripts"))

from core.player_backend import PlayerBackend


def find_test_video():
    for name in ("test_video.mp4", "测试视频.mp4"):
        path = os.path.join(ROOT, "tests", name)
        if os.path.isfile(path):
            return path
    tests_dir = os.path.join(ROOT, "tests")
    for name in os.listdir(tests_dir):
        if name.lower().endswith((".mp4", ".mkv", ".avi", ".mov")):
            return os.path.join(tests_dir, name)
    return None


def main():
    video = find_test_video()
    if not video:
        print("未找到测试视频")
        return 1
    print(f"测试视频: {video}")

    backend = PlayerBackend()
    info = backend.open(video)
    print(f"OPEN: duration={info.duration_sec:.1f}s {info.width}x{info.height} audio={info.has_audio}")

    backend.set_volume(0.8)
    audio_ok = backend.resume()
    print(f"RESUME: audio_device={audio_ok}")

    start = time.time()
    frames = 0
    while time.time() - start < 3.0:
        frame = backend.next_frame()
        if frame is None:
            print("FRAME_EOF")
            break
        frames += 1

    backend.pause()
    backend.close()
    print(f"3秒内解码 {frames} 帧")
    if info.has_audio and not audio_ok:
        print("FAIL: 有音频轨但设备未启动")
        return 2
    if info.has_audio:
        print("OK: 请确认是否听到声音（本脚本无法自动检测）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
