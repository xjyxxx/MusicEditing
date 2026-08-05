"""热评已并入 DownloadPage（一步获取评论 + 唯一媒体）。

保留本模块名以免旧 import 失败；请使用 ui.download_page.DownloadPage。
"""

from ui.download_page import DownloadPage as HotCommentsPanel

HotCommentsPage = HotCommentsPanel
