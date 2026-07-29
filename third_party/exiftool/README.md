# ExifTool（图片 / 媒体元数据）

本目录存放 **ExifTool** Windows 可执行包，供导入图片时展示 EXIF/IPTC/XMP 等元数据。

## 布局

```
third_party/exiftool/
  exiftool.exe          # 由 scripts/download_exiftool.bat 安装（默认不进 git）
  exiftool_files/       # 必须与 exe 同目录（内含 Perl 运行时）
  README.md
```

**注意：** 移动 `exiftool.exe` 时必须一并移动 `exiftool_files/`。

## 获取

```powershell
.\scripts\download_exiftool.bat
```

官网：https://exiftool.org/  
Oliver Betz 镜像（下载脚本优先）：https://oliverbetz.de/pages/Artikel/ExifTool-for-Windows  
（下载 `exiftool-*_64.zip`，将 `exiftool(-k).exe` 重命名为 `exiftool.exe`。）

## 运行时查找顺序

`MediaBridge`：

1. `third_party/exiftool/exiftool.exe`
2. `build_x64/bin/Release/exiftool.exe`（`run_ui_x64.bat` 会复制 exe + `exiftool_files`）
3. `PATH` 中的 `exiftool`

## 许可

ExifTool 版权归 Phil Harvey；使用请遵守其许可与站点条款。
