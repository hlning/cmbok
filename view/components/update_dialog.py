# coding:utf-8
"""新版本更新提示对话框

启动检测与设置页手动检查更新共用：弹出对话框，提供 GitHub 下载链接与
「甜甜的小站」博客跳转。两处调用统一走本函数，避免逻辑重复。
"""
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import MessageBox, PushButton

BLOG_URL = "https://bluemood.xiaomy.net/"


def show_new_version_dialog(parent, body, html_url):
    """弹出新版本对话框。

    - 点 GitHub（确认按钮）：打开 Release 页
    - 点「甜甜的小站」：打开博客并关闭对话框（reject 后 exec 返回 False，不再打开 GitHub）
    - 点取消/关闭：不跳转
    """
    w = MessageBox("检测到新版本，是否更新？", body, parent)
    w.yesButton.setText("GitHub")
    # GitHub 右侧加「甜甜的小站」按钮
    blog_btn = PushButton("甜甜的小站", w.buttonGroup)
    w.buttonLayout.insertWidget(1, blog_btn, 1, Qt.AlignVCenter)

    def _open_blog():
        QDesktopServices.openUrl(QUrl(BLOG_URL))
        w.reject()
    blog_btn.clicked.connect(_open_blog)

    if w.exec():
        # 点 GitHub -> 打开 Release 页
        QDesktopServices.openUrl(QUrl(html_url))
