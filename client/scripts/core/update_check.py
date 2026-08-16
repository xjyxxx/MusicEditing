"""检查新版本（可选远程 manifest）。

配置（任选其一）:
  环境变量 MUSIC_UPDATE_URL
  app.conf  update_manifest_url=https://example.com/musicediting_update.json

上线配套:
  python scripts/publish_update_manifest.py --version 0.2.0 --base-url https://cdn/.../
  python scripts/serve_update_channel.py   # 本地联调

manifest JSON 示例见 docs/examples/musicediting_update.example.json

无 URL 时返回「未配置」，不报错。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


def _parse_ver(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (v or "").strip())
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums[:4])


def version_newer(remote: str, local: str) -> bool:
    return _parse_ver(remote) > _parse_ver(local)


@dataclass
class UpdateInfo:
    configured: bool
    has_update: bool
    local_version: str
    remote_version: str = ""
    url: str = ""
    notes: str = ""
    message: str = ""
    sha256: str = ""
    size_bytes: int = 0
    package_kind: str = ""
    channel: str = ""
    landing_url: str = ""
    # 原始 manifest 片段，供 OTA 模板使用
    manifest_extra: dict | None = None


def manifest_url() -> str:
    env = (os.environ.get("MUSIC_UPDATE_URL") or "").strip()
    if env:
        return env
    try:
        from core.app_logic import load_app_config
        return (load_app_config().get("update_manifest_url") or "").strip()
    except Exception:
        return ""


def check_on_startup_enabled() -> bool:
    env = (os.environ.get("MUSIC_UPDATE_CHECK_STARTUP") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        from core.app_logic import load_app_config
        v = (load_app_config().get("update_check_on_startup") or "").strip().lower()
        return v in ("1", "true", "yes", "on")
    except Exception:
        return False


def last_notified_version() -> str:
    try:
        from core.app_logic import load_app_config
        return (load_app_config().get("update_last_notified") or "").strip()
    except Exception:
        return ""


def remember_notified_version(version: str) -> None:
    try:
        from core.app_logic import update_app_config_value
        update_app_config_value("update_last_notified", (version or "").strip())
    except Exception:
        pass


def setup_help_text() -> str:
    """未配置更新通道时，帮助/个人中心弹窗用的操作说明。"""
    return (
        "配置（任选其一）：\n"
        "  · app.conf：update_manifest_url=https://你的域名/musicediting_update.json\n"
        "  · 环境变量：MUSIC_UPDATE_URL\n"
        "  · 启动静默检查：update_check_on_startup=true\n\n"
        "发布更新通道：\n"
        "  python scripts/publish_update_manifest.py --version x.y.z\n"
        "  （可选 --base-url https://cdn.example.com/me/ --notes \"说明\"）\n\n"
        "本地联调：\n"
        "  python scripts/serve_update_channel.py\n"
        "  update_manifest_url=http://127.0.0.1:8777/musicediting_update.json\n\n"
        "OTA（下载校验 + 便携 zip 退出后替换）：\n"
        "  · 帮助/个人中心 → 检查更新 →「下载并升级」→ 确认立即升级\n"
        "  · ota_apply_enabled=true 仅加强提示，真正替换仍需确认\n"
        "  · 正式通道 manifest 必须含 sha256（联调可 MUSIC_OTA_ALLOW_NO_HASH=1）\n"
        "  · 详见 docs/design/distribution.md §5.3\n\n"
        "详见 docs/design/distribution.md §5。"
    )


def should_prompt_startup(info: UpdateInfo) -> bool:
    """启动静默检查：仅当有新版本且与上次提示版本不同才弹窗。"""
    if not info.configured or not info.has_update:
        return False
    last = last_notified_version()
    if last and last == info.remote_version:
        return False
    return True


def check_for_update(local_version: str, *, timeout: float = 8.0) -> UpdateInfo:
    local = (local_version or "0.0.0").strip()
    url = manifest_url()
    if not url:
        return UpdateInfo(
            configured=False,
            has_update=False,
            local_version=local,
            message="未配置更新地址（MUSIC_UPDATE_URL 或 app.conf update_manifest_url）",
        )
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "MusicEditing-UpdateCheck"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("manifest 不是对象")
        remote = str(data.get("version") or "").strip()
        dl = str(data.get("url") or data.get("download_url") or "").strip()
        notes = str(data.get("notes") or data.get("changelog") or "").strip()
        sha256 = str(data.get("sha256") or data.get("hash") or "").strip().lower()
        package_kind = str(data.get("package_kind") or data.get("kind") or "").strip()
        channel = str(data.get("channel") or "").strip()
        landing = str(data.get("landing_url") or data.get("page_url") or "").strip()
        size_bytes = 0
        try:
            size_bytes = int(data.get("size_bytes") or data.get("size") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        if not remote:
            raise ValueError("缺少 version 字段")
        # 相对 url：拼到 manifest 所在目录
        if dl and not dl.lower().startswith(("http://", "https://")):
            base = url.rsplit("/", 1)[0]
            dl = f"{base}/{dl.lstrip('/')}"
        if landing and not landing.lower().startswith(("http://", "https://")):
            base = url.rsplit("/", 1)[0]
            landing = f"{base}/{landing.lstrip('/')}"
        newer = version_newer(remote, local)
        return UpdateInfo(
            configured=True,
            has_update=newer,
            local_version=local,
            remote_version=remote,
            url=dl,
            notes=notes,
            sha256=sha256,
            size_bytes=size_bytes,
            package_kind=package_kind,
            channel=channel,
            landing_url=landing,
            manifest_extra=data,
            message=(
                f"发现新版本 {remote}（当前 {local}）"
                if newer
                else f"已是最新（{local}）"
            ),
        )
    except urllib.error.URLError as e:
        return UpdateInfo(
            configured=True,
            has_update=False,
            local_version=local,
            message=f"检查更新失败：网络错误（{e}）",
        )
    except Exception as e:
        return UpdateInfo(
            configured=True,
            has_update=False,
            local_version=local,
            message=f"检查更新失败：{e}",
        )
