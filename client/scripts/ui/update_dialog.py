"""检查更新对话框：落地页 / 包直链 / OTA 后台下载 / 立即升级并退出。"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from core.update_check import UpdateInfo, setup_help_text


class _OtaDownloadWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(object)  # OtaDownloadResult

    def __init__(self, plan) -> None:
        super().__init__()
        self._plan = plan
        self._abort = False

    def request_abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        from core.ota_update import download_package

        def prog(received: int, total: int) -> None:
            self.progress.emit(received, total)

        result = download_package(
            self._plan,
            progress=prog,
            abort=lambda: self._abort,
        )
        self.finished.emit(result)


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

    landing = (info.landing_url or "").strip()
    if not landing and info.manifest_extra:
        landing = str(
            info.manifest_extra.get("landing_url")
            or info.manifest_extra.get("page_url")
            or ""
        ).strip()

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
        "可打开说明页/浏览器，或下载后自动替换便携目录（将退出并重启）。"
    )
    btn_web = None
    if landing:
        btn_web = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
    else:
        btn_web = box.addButton("在浏览器打开包", QMessageBox.ButtonRole.AcceptRole)
    btn_ota = box.addButton("下载并升级…", QMessageBox.ButtonRole.ActionRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_web:
        QDesktopServices.openUrl(QUrl(landing or info.url))
        return
    if clicked is btn_ota:
        _run_ota_download(parent, info, offer_inplace=True)


def _run_ota_download(
    parent: QWidget | None,
    info: UpdateInfo,
    *,
    offer_inplace: bool = True,
) -> None:
    from core.ota_update import PackageKind, apply_package, ota_apply_enabled, plan_from_update_info

    plan = plan_from_update_info(info, manifest_extra=info.manifest_extra)
    if plan is None:
        QMessageBox.warning(parent, "OTA", "无法构造下载计划（缺少 url）")
        return

    prog = QProgressDialog("正在下载更新包…", "取消", 0, 100, parent)
    prog.setWindowTitle("OTA 下载")
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    prog.setMinimumDuration(0)
    prog.setValue(0)

    thread = QThread(parent)
    worker = _OtaDownloadWorker(plan)
    worker.moveToThread(thread)

    def on_prog(received: int, total: int) -> None:
        if total > 0:
            prog.setMaximum(100)
            prog.setValue(min(99, int(received * 100 / total)))
        else:
            prog.setMaximum(0)

    def on_cancel() -> None:
        worker.request_abort()

    def on_done(result) -> None:
        prog.close()
        thread.quit()
        if not result.ok or result.path is None:
            if "取消" in (result.message or ""):
                QMessageBox.information(parent, "OTA", "已取消下载")
            else:
                QMessageBox.warning(parent, "OTA 下载失败", result.message)
            return
        _after_download(parent, info, plan, result, offer_inplace=offer_inplace)

    prog.canceled.connect(on_cancel)
    worker.progress.connect(on_prog)
    worker.finished.connect(on_done)
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    # 保持引用，避免被 GC
    prog._ota_thread = thread  # type: ignore[attr-defined]
    prog._ota_worker = worker  # type: ignore[attr-defined]


def _after_download(parent, info, plan, result, *, offer_inplace: bool) -> None:
    from core.ota_update import PackageKind, apply_package, ota_apply_enabled

    is_zip = result.path.suffix.lower() == ".zip" or plan.package_kind in (
        PackageKind.PORTABLE_ZIP,
        PackageKind.SHARE_ZIP,
    )
    force_inplace = False
    if offer_inplace and is_zip:
        default_yes = ota_apply_enabled()
        ask = QMessageBox.question(
            parent,
            "立即升级？",
            f"{result.message}\n\n"
            "将退出程序，由后台替换便携目录并自动重新打开。\n"
            "（开发目录请勿使用；请对打包后的便携版操作。）\n\n"
            + ("建议立即升级并退出。" if default_yes else "是否立即升级并退出？"),
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
    QMessageBox.information(parent, "OTA", f"{result.message}\n\n{apply.message}")
    if apply.request_exit:
        _quit_after_ota(parent)


def _quit_after_ota(parent: QWidget | None) -> None:
    def _bye() -> None:
        win = parent.window() if parent is not None else None
        if win is not None:
            win.close()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()

    QTimer.singleShot(600, _bye)


def prompt_pending_ota(parent: QWidget | None) -> None:
    """启动时未完成 OTA 的轻量提示。"""
    from core.ota_update import clear_pending, resume_pending_if_any

    tip = resume_pending_if_any()
    if not tip:
        return
    box = QMessageBox(parent)
    box.setWindowTitle("未完成的升级")
    box.setText(tip)
    btn_ignore = box.addButton("忽略并删除标记", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    if box.clickedButton() is btn_ignore:
        clear_pending()
