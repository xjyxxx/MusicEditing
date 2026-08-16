"""检查更新对话框：打开下载页 / OTA 下载 / 立即升级并退出。"""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from core.update_check import UpdateInfo, setup_help_text


def prompt_update_result(parent: QWidget | None, info: UpdateInfo) -> None:
    if not info.configured:
        QMessageBox.information(
            parent,
            "检查更新",
            f"{info.message}\n\n{setup_help_text()}",
        )
        return
    if not (info.has_update and info.url):
        QMessageBox.information(parent, "检查更新", info.message)
        return

    box = QMessageBox(parent)
    box.setWindowTitle("发现新版本")
    notes = (info.notes or "").strip()
    extra = ""
    if info.sha256:
        extra += f"\nSHA256: {info.sha256[:16]}…"
    if info.package_kind:
        extra += f"\n包类型: {info.package_kind}"
    box.setText(f"{info.message}\n\n{notes}{extra}".strip())
    box.setInformativeText(
        "打开下载页，或下载后自动替换便携目录（将退出并重启）。"
    )
    btn_web = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
    btn_ota = box.addButton("下载并升级…", QMessageBox.ButtonRole.ActionRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_web:
        QDesktopServices.openUrl(QUrl(info.url))
        return
    if clicked is btn_ota:
        _run_ota_download(parent, info, offer_inplace=True)


def _run_ota_download(
    parent: QWidget | None,
    info: UpdateInfo,
    *,
    offer_inplace: bool = True,
) -> None:
    from core.ota_update import (
        PackageKind,
        apply_package,
        download_package,
        plan_from_update_info,
    )

    plan = plan_from_update_info(info, manifest_extra=info.manifest_extra)
    if plan is None:
        QMessageBox.warning(parent, "OTA", "无法构造下载计划（缺少 url）")
        return

    prog = QProgressDialog("正在下载更新包…", "取消", 0, 100, parent)
    prog.setWindowTitle("OTA 下载")
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    prog.setMinimumDuration(0)
    prog.setValue(0)
    cancelled = {"v": False}

    def on_prog(received: int, total: int) -> None:
        if prog.wasCanceled():
            cancelled["v"] = True
            return
        if total > 0:
            prog.setMaximum(100)
            prog.setValue(min(99, int(received * 100 / total)))
        else:
            prog.setMaximum(0)
        QApplication.processEvents()

    result = download_package(plan, progress=on_prog)
    prog.close()
    if cancelled["v"]:
        QMessageBox.information(parent, "OTA", "已取消下载")
        return
    if not result.ok or result.path is None:
        QMessageBox.warning(parent, "OTA 下载失败", result.message)
        return

    is_zip = result.path.suffix.lower() == ".zip" or plan.package_kind in (
        PackageKind.PORTABLE_ZIP,
        PackageKind.SHARE_ZIP,
    )
    force_inplace = False
    if offer_inplace and is_zip:
        ask = QMessageBox.question(
            parent,
            "立即升级？",
            f"{result.message}\n\n"
            "将退出程序，由后台替换便携目录并自动重新打开。\n"
            "（开发目录请勿使用；请对打包后的便携版操作。）\n\n"
            "是否立即升级并退出？",
        )
        force_inplace = ask == QMessageBox.StandardButton.Yes
        if not force_inplace:
            apply = apply_package(plan, result.path, force_inplace=False)
            QMessageBox.information(parent, "OTA", f"{result.message}\n\n{apply.message}")
            return

    apply = apply_package(
        plan,
        result.path,
        force_inplace=force_inplace,
        wait_pid=os.getpid(),
    )
    QMessageBox.information(
        parent,
        "OTA",
        f"{result.message}\n\n{apply.message}",
    )
    if apply.request_exit:
        _quit_after_ota(parent)


def _quit_after_ota(parent: QWidget | None) -> None:
    from PySide6.QtCore import QTimer

    def _bye() -> None:
        win = parent.window() if parent is not None else None
        if win is not None:
            win.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    QTimer.singleShot(600, _bye)
