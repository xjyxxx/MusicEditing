# 分发 / 安装 / 授权（发版与赚钱）

本文覆盖：便携包验收、代码签名、Inno 安装包、卡密激活服务。  
枢纽状态见 [implementation_flow.md](implementation_flow.md)；发版清单见 [release_checklist.md](release_checklist.md)。

---

## 1. 真·发版闭环

```powershell
# 推荐：一条龙（回归 → pack → accept → Inno → 清单）
.\scripts\release_oneclick.bat
# 或:
python scripts\release_oneclick.py --profile standard
python scripts\release_oneclick.py --profile slim --no-installer
python scripts\release_oneclick.py --skip-regression --sign

# 分步:
# 外发给别人（推荐：强制 zip + 严格无业务 .py）:
.\scripts\pack_for_share.bat
# 或通用便携:
python scripts\pack_portable.py --profile standard --zip
python scripts\accept_portable.py
```

输出清单：`dist/RELEASE_MANIFEST_*.txt`。

档位：`slim`（演示/无大 ONNX） / `standard`（默认可卖） / `full`（含 LLM/vosk）。

---

## 1.1 代码安全（外发必读）

| 措施 | 说明 |
|------|------|
| 默认去源码 | `client/scripts`、`third_party/iphoto` 编成 `.pyc` 后删除 `.py` |
| 严格审计 | 残留业务 `.py` / `.git` / `docs/design` / 顶层 `src` / 密钥类文件 → **拒绝出包** |
| 不进包 | C++ 工程源、设计文档、课程文稿、`.cursor`、地图 font/OBF |
| 禁止外发开关 | `--ship-source`（可读 `.py`）；外发请用 `pack_for_share` |
| 诚实边界 | `.pyc` **仍可被反编译**，只是提高门槛；军工级需另行 Nuitka/加壳 |
| 无黑框子进程 | 启动时 `install_hidden_console_patch`：media_cli/ffmpeg/media_player 等不再弹控制台（否则 pythonw 下狂闪且 UI 卡） |
| 内嵌 runtime | 官方 embeddable Python + **瘦身后的** PySide6/numpy/opencv；默认**裁掉** WebEngine/Designer/3D 与未用的 scipy；vosk 仅 `full`/`--with-llm` |
| 图库最小依赖 | 默认 `requirements-iphoto-min`（jsonschema/Pillow…，**不含** imagehash→scipy） |

```powershell
# 唯一推荐外发入口（禁止带源码；默认瘦包）
.\scripts\只打包.bat
# 或:
.\scripts\pack_for_share.bat
# 演示更小:
python scripts\pack_for_share.py --profile slim
# 需要去水印/超分 ONNX（约 +200MB）:
python scripts\pack_for_share.py --with-models
```

输出：`dist/MusicEditing_Share_YYYYMMDD*.zip`。

### 体积预期（外发瘦包）

| 项 | 约略 |
|----|------|
| zip（`compresslevel=9`） | 视机器约 **300–450MB**（旧包 700MB+ 多为未裁剪 / 带 models） |
| 解压后目录 | runtime 裁剪后约 **400MB** + 引擎 DLL；无 `lama.onnx` 时通常 **&lt;700MB** |
| 默认不带 | `models/*.onnx`、测试视频、WebEngine/Designer、scipy、vosk |
| 硬底线 | 内嵌 Python + PySide6 + OpenCV + FFmpeg 引擎，无法压成「几 MB 单文件」 |

打包日志应出现 `[裁剪] runtime 已删约 … MB`；若无此行，说明仍是旧脚本产物。

---

## 1.2 最终用户要装什么？（结论：基本不用）

| 角色 | 需要 |
|------|------|
| **开发者本机** | Visual Studio / CMake / Python（用来编译与打包） |
| **收到 zip 的对方** | 只要 **Windows 10/11 64 位**；解压 → 双击 `MusicEditing.exe` |

对方**不需要**安装：Visual Studio、Python、CUDA Toolkit、Vulkan SDK。

打包脚本会：

1. 内嵌 `runtime\`（官方 embeddable Python + 裁剪后的 PySide6/numpy/opencv；默认无 WebEngine/vosk/scipy）  
2. 尽量把 **VC++ CRT DLL**（`vcruntime140.dll` / `msvcp140.dll` 等）拷进引擎目录——这是「可再发行运行库」，**不是** Visual Studio  

极少数干净机仍闪退时，再装微软官网的「Visual C++ 2015–2022 **可再发行组件** x64」（几 MB），仍然**不是**装 VS。

---

## 2. 代码签名

1. 购买 Windows 代码签名证书（OV/EV，支持 Authenticode）  
2. 安装到本机证书库，记下证书 SHA1 指纹  
3. 打包时：

```powershell
$env:MUSIC_CODE_SIGN_THUMBPRINT="你的SHA1"
python scripts\pack_portable.py --profile standard --zip --sign
.\scripts\build_installer.bat   # 生成 Setup 后自动尝试签名
# 或单独: python scripts\sign_artifact.py --latest-setup
```

无证书时 `--sign` / `sign_artifact` 会跳过并提示（属正常）。未签名包务必在使用说明里写清 SmartScreen 步骤。`accept_portable` 会打印 exe/Setup 的 Authenticode 状态。

---

## 3. Inno Setup 安装包

依赖：[Inno Setup 6](https://jrsoftware.org/isdl.php)（或 `winget install JRSoftware.InnoSetup`）。

```powershell
.\scripts\build_installer.bat
# 指定便携目录:
.\scripts\build_installer.bat dist\MusicEditing_Portable_YYYYMMDD
```

输出：`dist\MusicEditing_Setup_0.1.0.exe`（开始菜单 + 可选桌面图标 + 卸载）。  
脚本：`scripts/inno/MusicEditing.iss`。

---

## 4. 支付 / 卡密后端

客户端已支持：

| 配置 | 作用 |
|------|------|
| `license_purchase_url` | 个人中心「打开购买页」 |
| `license_server_url` | `POST {url}/v1/activate` 联网校验 |

仓库自带**演示服务**（stdlib，无第三方依赖）：

```powershell
python scripts\license_server\gen_keys.py --count 5
python scripts\license_server\server.py --port 8765
```

`app.conf` 示例：

```
license_purchase_url=http://127.0.0.1:8765/
license_server_url=http://127.0.0.1:8765
```

协议：

```
POST /v1/activate
{"key":"...","machine":"<fingerprint>","product":"MusicEditing"}
→ {"ok":true,"message":"联网激活成功"}

POST /v1/issue   （支付成功后发卡钩子；演示购买页按钮可调）
{"product":"MusicEditing","note":"order-123","token":"<可选>"}
→ {"ok":true,"key":"XXXX-..."}
```

若设置环境变量 `MUSIC_LICENSE_ISSUE_TOKEN`，则 `issue` 必须带同名 `token`（生产必设）。未设置时演示页开放发卡（仅本地联调）。

**真实收款闭环：**

1. 外部收银台收款成功  
2. 商店 webhook / 你的后端调 `POST {license_server}/v1/issue`（或本机 `gen_keys.py`）  
3. 把返回的 `key` 发给用户  
4. 用户在个人中心粘贴；客户端 `POST /v1/activate`  

本仓库**不内置**微信/支付宝 SDK。生产建议：`MUSIC_LICENSE_OFFLINE_FALLBACK=0`。

正式配置清单：

```
license_purchase_url=https://你的商店页或演示服/
license_server_url=https://你的激活服
```

---

## 5. 自动更新（可选）

客户端：帮助 →「检查更新…」/ 个人中心「检查更新…」。  
若 `update_check_on_startup=true`，启动约 3.5s 后静默检查；同一 `remote_version` 只提示一次（写入 `update_last_notified`）。

### 5.1 配置

其一即可：

- 环境变量 `MUSIC_UPDATE_URL`
- `app.conf`：`update_manifest_url=https://…/musicediting_update.json`

可选：

- `update_check_on_startup=true`（或环境变量 `MUSIC_UPDATE_CHECK_STARTUP=1`）
- `update_last_notified=`（客户端自动写，勿手改）

manifest 示例：[docs/examples/musicediting_update.example.json](../examples/musicediting_update.example.json)  
`url` 可为绝对 `https://…`，或相对文件名（相对 manifest 所在目录，便于本地 serve）。

### 5.2 发版生成 + 本地联调

```bat
REM 先打好 Setup / Portable 到 dist\
python scripts\publish_update_manifest.py --version 0.2.0 --notes "修复说明" --base-url https://cdn.example.com/me/
REM 产物: dist\update\musicediting_update.json + 拷贝安装包

REM 本地联调（不传 --base-url 时 url 为相对名）
python scripts\publish_update_manifest.py --version 0.2.0
python scripts\serve_update_channel.py
REM app.conf:
REM   update_manifest_url=http://127.0.0.1:8777/musicediting_update.json
REM   update_check_on_startup=true
```

上线：把 `dist/update/` 整目录上传 CDN/静态站，再把客户端 `update_manifest_url` 指到该 JSON。

**注意：** 仓库默认 `app.conf` 不要保留 `127.0.0.1` 联调地址（发版/给别人用会误弹更新）。本地联调时临时取消注释即可。

### 5.3 OTA 远程升级

| 阶段 | 状态 | 说明 |
|------|------|------|
| 检查 manifest | ✅ | `core/update_check.py` |
| 下载到暂存 | ✅ | `%LOCALAPPDATA%/MusicEditing/ota/<ver>/` |
| SHA256 校验 | ✅ | **正式通道强制**（缺 hash 拒下载）；联调 `MUSIC_OTA_ALLOW_NO_HASH=1` |
| 下载可取消 / 不堵 UI | ✅ | 后台线程 + abort；取消删 `.part` |
| Zip Slip 防护 | ✅ | `safe_extract_zip`；助手校验含 `MusicEditing.exe` |
| 打开下载页 | ✅ | 优先 `landing_url`；否则「在浏览器打开包」 |
| **便携 zip 自动替换** | ✅ | 用户确认后 → pending → PowerShell 助手（失败回滚 bak） |
| Inno Setup | ✅ 半自动 | 确认后 `os.startfile` |
| 启动器内嵌热切换 | ⏳ | 仍用系统 PowerShell 助手 |

流程：

1. `publish_update_manifest.py`（无产物默认失败；需 `--allow-placeholder` 才写无 hash 占位）  
2. 客户端「检查更新」→ **下载并升级…** → 确认「立即升级并退出」  
3. 助手日志：`%LOCALAPPDATA%\MusicEditing\ota\apply_helper.log`  
4. 失败时尽量把 `*.ota_bak_*` 改回安装目录  

配置：`ota_apply_enabled`（仅加强「建议立即升级」文案）、`ota_staging_dir`、`ota_allow_no_hash`（仅联调）。  
**注意：** 请对**打包后的便携目录**使用；不要对开发仓库根目录点「立即升级」。  
包内需带 `scripts/ota_apply_helper.ps1`。

### 5.4 发版卫生（一眼能跟）

1. 打外发包：`.\scripts\pack_for_share.bat`（或 `--profile standard`）  
   - 图库完整：再加 `--with-iphoto-extras`（HEIC）与/或 `--with-maps`（font，体积大）  
2. 生成并上传：`publish_update_manifest.py --base-url https://正式CDN/…` → 上传 `dist/update/`  
3. 正式包 `app.conf`：`update_manifest_url=https://…/musicediting_update.json`（**禁止 127.0.0.1**）  
4. 可选：`--sign` + `build_installer.bat`（Setup 自动再签）、购买/激活 URL、`update_check_on_startup=true`  
5. 干净机手测（§6.1）  

照片图库：HEIC / 离线 maps 为**可选**；默认瘦包可能降级，不是「图库坏了」。带 `--with-iphoto-extras` / `--with-maps` 才接近完整。

冒烟：`python tests/regression/test_ota_update.py`、`test_ota_apply_helper.py`（已入 `run_regression_short.bat`）

---

## 6. 上线跑通清单（P0→P3）

| 级别 | 项 | 本仓库能否代劳 | 操作 |
|------|----|----------------|------|
| P0 | 关掉本地更新 URL | ✅ | `app.conf` 注释掉 `update_manifest_url` / `update_check_on_startup` |
| P0 | 干净机手测 | ⚠ 需人手 | 见下「6.1」；本机可先 `accept_portable.py` |
| P1 | 长页不裁半 | ✅ | 封面工厂整页滚动；音频/BGM/溯源 Tab 滚动；队列右侧参数滚动 |
| P1 | 更新真通道 | ⚠ 需 CDN | Setup/zip → `publish_update_manifest.py --base-url …` → 上传 `dist/update/` → 客户端填正式 URL |
| P2 | 代码签名 | ⚠ 需证书 | `$env:MUSIC_CODE_SIGN_THUMBPRINT=…` + `pack … --sign` |
| P2 | 外部收银台 | ⚠ 需商店 | 支付成功后发卡；客户端 `license_purchase_url` + 可选 `license_server_url` |
| P3 | 真 game_event | ⏸ 需数据 | 现为 stub ONNX，非真击杀模型 |
| P3 | AI 超分再抠 | ⏸ 可选 | 已有 tile≈640 / JPEG / CUDA EP；收益递减 |

### 6.1 干净机手测（必须你自己做）

1. 另找一台未装本项目依赖的 Win10/11 x64  
2. 解压 `MusicEditing_Portable_*.zip` 或跑 `MusicEditing_Setup_*.exe`  
3. 若 SmartScreen：更多信息 → 仍要运行  
4. 双击 `MusicEditing.exe`（**无需装 Visual Studio / Python**）  
5. 若闪退 / **黑框狂闪**：装 [VC++ 可再发行组件 x64](https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist)（小运行库，不是 VS）；务必用完整解压目录里的 `MusicEditing.exe`  
6. 打开包内测试视频 → 播放 / Seek；若打不开：看播放器标题「打开失败…」，并打开 `docs\log_playerbackend.txt`、`docs\log_media_player.txt`  
7. **一点播放就跳到最后一帧**：确认是本轮修复后的新包（启动器不再污染 PATH + `QT_MEDIA_BACKEND=windows`）；临时验证可在 bat 里设 `set QT_MEDIA_BACKEND=windows`  
8. **照片图库打不开**：新包已带 `requirements-iphoto-min`；旧包会因缺 `jsonschema` 回退经典图库。HEIC 另需 `--with-iphoto-extras`  
9. 仍失败：个人中心关掉 GPU 再试；画面闪/黑可设 `MUSIC_SOFTWARE_GL=1` 后重启  
10. 个人中心看试用配额；帮助「检查更新」在未配置 URL 时应提示未配置（勿指 127.0.0.1）

`pack_portable` / `pack_for_share` 验收现已**硬检查**播放 DLL（`avcodec/avutil/swscale…`、`glew32`、`vcruntime140`、`msvcp140`）；缺了会打包失败，避免「本机能播、干净机不能播」。

本机预检：

```powershell
python scripts\accept_portable.py
# 模拟外发环境（干净 PATH）：叠加最新修复后测图库 import + 解码 + 音频时钟
python scripts\smoke_portable_env.py
```

### 6.2 更新通道一次上线（需你的 CDN）

```powershell
python scripts\pack_portable.py --profile standard --zip
.\scripts\build_installer.bat
python scripts\publish_update_manifest.py --version 0.2.0 --notes "说明" --base-url https://你的CDN/me/
# 上传 dist\update\ 全部文件
# 正式包内 app.conf（或发布渠道配置）:
#   update_manifest_url=https://你的CDN/me/musicediting_update.json
#   update_check_on_startup=true
```

### 6.3 收银台（店外）

1. 用户在商店付完款 → 你的后端调 `scripts/license_server/gen_keys.py`（或自建发卡 API）把卡密发给用户  
2. `app.conf`：`license_purchase_url=https://商店页`  
3. 可选联网激活：`license_server_url=https://激活服`（`POST /v1/activate`），演示服见 `scripts/license_server/`

---

## 7. 试用策略（客户端）

见 [feature_flows.md](feature_flows.md) §5.17：`trial_policy` 门禁 + 高光/竖屏次数 + ≤720p。
