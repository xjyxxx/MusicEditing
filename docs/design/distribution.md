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

```powershell
# 唯一推荐外发入口（禁止带源码）
.\scripts\pack_for_share.bat
# 演示体积:
python scripts\pack_for_share.py --profile slim
```

输出：`dist/MusicEditing_Share_YYYYMMDD*.zip`。

---

## 2. 代码签名

1. 购买 Windows 代码签名证书（OV/EV，支持 Authenticode）  
2. 安装到本机证书库，记下证书 SHA1 指纹  
3. 打包时：

```powershell
$env:MUSIC_CODE_SIGN_THUMBPRINT="你的SHA1"
python scripts\pack_portable.py --profile standard --zip --sign
```

无证书时 `--sign` 会跳过并提示（属正常）。未签名包务必在使用说明里写清 SmartScreen 步骤。

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
```

**真实收款：** 用微信/支付宝/Lemon 等收银台，支付成功后调用 `gen_keys`（或你的发卡 API）把卡密发给用户。本仓库服务负责**激活校验**，不内置支付通道。

生产建议：`MUSIC_LICENSE_OFFLINE_FALLBACK=0`，禁止联网失败时回退本地格式校验。

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
4. 缺 VC++：装 [VC++ 2015–2022 x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)  
5. 双击 `MusicEditing.exe`：打开 `tests\test_video.mp4`（包内若有）→ 播放 / Seek  
6. 个人中心看试用配额；帮助「检查更新」在未配置 URL 时应提示未配置（勿指 127.0.0.1）

本机预检：

```powershell
python scripts\accept_portable.py
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
