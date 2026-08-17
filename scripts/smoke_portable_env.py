# -*- coding: utf-8 -*-
"""在「外发包」目录上叠加入最新修复并冒烟（不依赖开发机 PATH 里的引擎 DLL）。

用法（仓库根）:
  python scripts/smoke_portable_env.py
  python scripts/smoke_portable_env.py dist/_share_probe/MusicEditing_Share_20260817
"""

from __future__ import annotations

import compileall
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _die(msg: str) -> None:
    print(f"[失败] {msg}", flush=True)
    raise SystemExit(1)


def _find_pack() -> Path:
    probe = ROOT / "dist" / "_share_probe" / "MusicEditing_Share_20260817"
    if probe.is_dir() and (probe / "runtime" / "python.exe").is_file():
        return probe
    zips = sorted(
        (ROOT / "dist").glob("MusicEditing_Share_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not zips:
        _die("未找到 Share 包目录或 zip，请先打包")
    out = ROOT / "dist" / "_pack_smoke" / zips[0].stem
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[解压] {zips[0].name} → {out}", flush=True)
    with zipfile.ZipFile(zips[0], "r") as zf:
        zf.extractall(out.parent)
    # zip 内可能自带同名目录
    if (out.parent / zips[0].stem).is_dir() and out != out.parent / zips[0].stem:
        return out.parent / zips[0].stem
    kids = [p for p in out.parent.iterdir() if p.is_dir() and p.name.startswith("MusicEditing_Share")]
    return kids[0] if kids else out


def _overlay_sources(pack: Path) -> None:
    """把仓库当前 client/scripts 与 iphoto 源码编成 .pyc 覆盖进包（模拟新打包结果）。"""
    py = pack / "runtime" / "python.exe"
    if not py.is_file():
        _die(f"包内无 runtime/python.exe: {pack}")

    # 1) 覆盖 scripts 源再 compileall -b，再删 .py
    dst_scripts = pack / "client" / "scripts"
    src_scripts = ROOT / "client" / "scripts"
    print("[叠加] client/scripts → 包内并 compileall", flush=True)
    # 只同步关键改动文件，避免整树复制过久；同时保证 main/video_player/iphoto 最新
    critical = [
        "main.py",
        "ui/video_player.py",
        "ui/main_window.py",
        "ui/gl_video_widget.py",
        "ui/iphoto_host_page.py",
        "core/iphoto_bootstrap.py",
        "core/player_backend.py",
        "core/win_subprocess.py",
        "core/qt_audio_output.py",
        "requirements-iphoto-min.txt",
    ]
    for rel in critical:
        s = src_scripts / rel
        d = dst_scripts / rel
        if not s.is_file():
            print(f"  [跳过] 缺源 {rel}", flush=True)
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)

    # compileall 整个 scripts（含刚拷的 py）
    ok = compileall.compile_dir(str(dst_scripts), legacy=True, quiet=1, force=True, optimize=2)
    if not ok:
        print("[警告] compileall scripts 有失败项", flush=True)
    # 删除刚拷入的业务 .py，保留 .pyc（贴近外发包）
    for rel in critical:
        if not rel.endswith(".py"):
            continue
        p = dst_scripts / rel
        if p.is_file():
            p.unlink(missing_ok=True)

    # 2) iphoto-min 装进 runtime
    min_req = ROOT / "client" / "scripts" / "requirements-iphoto-min.txt"
    if min_req.is_file():
        print("[叠加] pip install requirements-iphoto-min …", flush=True)
        r = subprocess.run(
            [str(py), "-m", "pip", "install", "-r", str(min_req)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            print(r.stdout[-800:], flush=True)
            print(r.stderr[-800:], flush=True)
            _die("pip 安装 iphoto-min 失败")
        print("[叠加] iphoto-min OK", flush=True)

    # 3) 重写 bat：去 PATH 污染 + QT_MEDIA_BACKEND
    bat = pack / "启动 MusicEditing.bat"
    if bat.is_file():
        text = bat.read_text(encoding="utf-8", errors="replace")
        text = text.replace('set "PATH=%BIN%;%PATH%"\r\n', "")
        text = text.replace('set "PATH=%BIN%;%PATH%"\n', "")
        if "QT_MEDIA_BACKEND" not in text:
            text = text.replace(
                "set PYTHONUTF8=1\r\n",
                "set PYTHONUTF8=1\r\nset QT_MEDIA_BACKEND=windows\r\n",
            )
            text = text.replace(
                "set PYTHONUTF8=1\n",
                "set PYTHONUTF8=1\nset QT_MEDIA_BACKEND=windows\n",
            )
        bat.write_text(text, encoding="ascii", newline="\r\n")
        print("[叠加] 已修补启动 bat", flush=True)

    # 4) 尽量重编 MusicEditing.exe
    launcher_c = ROOT / "scripts" / "portable_launcher.c"
    if launcher_c.is_file():
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from pack_portable import _compile_exe_launcher

            exe = _compile_exe_launcher(pack)
            print(f"[叠加] MusicEditing.exe = {exe}", flush=True)
        except Exception as e:
            print(f"[警告] 重编 exe 失败（仍可用 bat）: {e}", flush=True)


def _smoke(pack: Path) -> int:
    py = pack / "runtime" / "python.exe"
    bin_dir = pack / "build_x64" / "bin" / "Release"
    video = ROOT / "tests" / "测试视频.mp4"
    if not video.is_file():
        # 备选英文名
        for cand in (ROOT / "tests").glob("*.mp4"):
            video = cand
            break
    if not video.is_file():
        _die("tests 下没有可测 mp4")

    # 刻意清空 PATH 里可能的开发引擎目录，模拟干净机
    clean_path = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
    env = os.environ.copy()
    env["PATH"] = clean_path
    env["PYTHONUTF8"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["QT_MEDIA_BACKEND"] = "windows"
    env["MUSIC_LOG_LEVEL"] = "INFO"

    probe = r'''
import os, sys, time
from pathlib import Path

pack = Path(r"""{pack}""")
sys.path.insert(0, str(pack / "client" / "scripts"))
os.chdir(pack)

# --- 图库 ---
from core.iphoto_bootstrap import try_import_iphoto, vendor_src_root
print("vendor", vendor_src_root())
mods, err = try_import_iphoto()
if mods is None:
    print("IPHOTO_FAIL", err)
    raise SystemExit(2)
print("IPHOTO_OK", sorted(mods.keys()))
from iPhoto.gui.coordinators.main_coordinator import MainCoordinator
print("COORDINATOR_OK", MainCoordinator.__name__)

# --- 播放：OPEN + 连续 NEXT，不应立刻 EOF ---
from core.player_backend import PlayerBackend
be = PlayerBackend()
info = be.open(r"""{video}""")
print("OPEN", info.width, info.height, "dur=%.3f" % info.duration_sec, "hw=", info.hw_decode)
frames = []
for i in range(12):
    fr = be.next_frame(min_ts=-1.0, apply_filter=False)
    if fr is None:
        print("EARLY_EOF at", i)
        raise SystemExit(3)
    ts, rgb, w, h = fr
    frames.append(ts)
print("FRAMES", ",".join("%.3f" % t for t in frames[:8]), "...")
if frames[0] > 1.0:
    print("FIRST_FRAME_TOO_LATE", frames[0])
    raise SystemExit(4)

# --- Qt 音频时钟（windows 后端）：开播后不应立刻跳到片尾 ---
from PySide6.QtWidgets import QApplication
from core.qt_audio_output import QtAudioOutput
app = QApplication.instance() or QApplication([])
au = QtAudioOutput()
au.open(r"""{video}""")
au.play(0.0)
t0 = time.time()
bad = False
last = 0.0
while time.time() - t0 < 1.2:
    app.processEvents()
    time.sleep(0.05)
    pos = au.position_sec()
    dur = au.duration_sec() or info.duration_sec
    last = pos
    if dur > 2.0 and pos >= dur - 0.5 and (time.time() - t0) < 0.8:
        print("AUDIO_JUMP_END pos=%.3f dur=%.3f t=%.2f" % (pos, dur, time.time()-t0))
        bad = True
        break
au.stop()
print("AUDIO_POS_AFTER_1s", "%.3f" % last, "dur=%.3f" % (au.duration_sec() or info.duration_sec))
be.shutdown()
if bad:
    raise SystemExit(5)

# --- 模拟首页「点播放」：音画同步跑 ~3 秒，进度不得跳尾 ---
be2 = PlayerBackend()
info2 = be2.open(r"""{video}""")
au2 = QtAudioOutput()
au2.open(r"""{video}""")
# 先停在片头一帧
fr0 = be2.seek_and_frame(0.0, min_ts=0.0, apply_filter=False)
if not fr0:
    print("SEEK0_FAIL")
    raise SystemExit(6)
shown_ts = fr0[0]
au2.play(0.0)
t_play = time.time()
last_audio = 0.0
n_frames = 1
jumped = False
while time.time() - t_play < 3.0:
    app.processEvents()
    time.sleep(0.04)
    audio_sec = au2.position_sec()
    dur = au2.duration_sec() or info2.duration_sec
    last_audio = audio_sec
    if dur > 5.0 and audio_sec >= dur - 0.5 and (time.time() - t_play) < 1.5:
        print("PLAY_AUDIO_JUMP pos=%.3f dur=%.3f" % (audio_sec, dur))
        jumped = True
        break
    # 画面追音频（与 UI 类似：落后才拉帧）
    if audio_sec > shown_ts + 0.02:
        fr = be2.next_frame(min_ts=max(0.0, audio_sec - 0.08), apply_filter=False)
        if fr is None:
            # 开播 3s 内不应 EOF（片长通常远大于 3s）
            if info2.duration_sec > 10 and (time.time() - t_play) < 2.5:
                print("PLAY_EARLY_EOF at audio=%.3f shown=%.3f" % (audio_sec, shown_ts))
                jumped = True
                break
        else:
            shown_ts = fr[0]
            n_frames += 1
au2.stop()
be2.shutdown()
print(
    "PLAY_SIM frames=%d shown=%.3f audio=%.3f elapsed=%.2f"
    % (n_frames, shown_ts, last_audio, time.time() - t_play)
)
if jumped:
    raise SystemExit(7)
if n_frames < 5:
    print("PLAY_TOO_FEW_FRAMES", n_frames)
    raise SystemExit(8)
if last_audio < 0.4:
    print("PLAY_AUDIO_STUCK", last_audio)
    raise SystemExit(9)
print("SMOKE_PASS")
'''.format(pack=str(pack).replace("\\", "\\\\"), video=str(video).replace("\\", "\\\\"))

    print("[冒烟] 干净 PATH + 包内 python …", flush=True)
    print(f"  pack={pack}", flush=True)
    print(f"  video={video.name}", flush=True)
    r = subprocess.run(
        [str(py), "-c", probe],
        cwd=str(pack),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    print(out[-5000:], flush=True)
    if r.returncode != 0:
        print(f"[冒烟] FAIL code={r.returncode}", flush=True)
        return 1
    if "SMOKE_PASS" not in out:
        print("[冒烟] FAIL 未见 SMOKE_PASS", flush=True)
        return 1
    print("[冒烟] PASS（图库 + 解码 + 音频未跳尾 + 模拟播放3秒）", flush=True)

    # 启动包内 GUI，便于本机点播手测（与外发一致）
    exe = pack / "MusicEditing.exe"
    if exe.is_file():
        print(f"[手测] 正在启动: {exe}", flush=True)
        print("       请在弹出窗口：打开视频 → 点播放 → 确认从头顺播、不跳尾", flush=True)
        print("       再进「照片图库」确认能加载", flush=True)
        # 干净 PATH，模拟外发机
        gui_env = env.copy()
        subprocess.Popen(
            [str(exe)],
            cwd=str(pack),
            env=gui_env,
            close_fds=True,
        )
    else:
        print("[手测] 无 MusicEditing.exe，请用「启动 MusicEditing.bat」", flush=True)
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    skip_overlay = "--no-overlay" in args
    paths = [a for a in args if not a.startswith("--")]
    pack = Path(paths[0]) if paths else _find_pack()
    if not pack.is_absolute():
        pack = (ROOT / pack).resolve()
    if not pack.is_dir():
        _die(f"不是目录: {pack}")
    print(f"[目标] {pack}", flush=True)
    if not skip_overlay:
        _overlay_sources(pack)
    else:
        print("[跳过] --no-overlay", flush=True)
    return _smoke(pack)


if __name__ == "__main__":
    raise SystemExit(main())
