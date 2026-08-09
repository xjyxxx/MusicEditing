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
python scripts\pack_portable.py --profile standard --zip
python scripts\accept_portable.py
```

输出清单：`dist/RELEASE_MANIFEST_*.txt`。

档位：`slim`（演示/无大 ONNX） / `standard`（默认可卖） / `full`（含 LLM/vosk）。

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

---

## 6. 试用策略（客户端）

见 [feature_flows.md](feature_flows.md) §5.17：`trial_policy` 门禁 + 高光/竖屏次数 + ≤720p。
