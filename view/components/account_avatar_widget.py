# coding:utf-8
"""账号头像组件：导航展开时两行显示（第一行用户名/未登录，第二行当日下载计数）。

qfluentwidgets 的 NavigationAvatarWidget 仅单行绘制 name，无法显示下载计数，
故子类化重写 paintEvent，展开时画两行。"""
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QFont
from qfluentwidgets import NavigationAvatarWidget, isDarkTheme


class AccountAvatarWidget(NavigationAvatarWidget):
    """账号头像：展开时两行（名称 + 下载计数）"""

    def __init__(self, name, avatar=None, parent=None):
        super().__init__(name, avatar, parent)
        self._subText = ''

    def setSubText(self, text):
        self._subText = text or ''
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        if self.isPressed:
            painter.setOpacity(0.7)

        # 背景
        if self.isEnter:
            c = 255 if isDarkTheme() else 0
            painter.setBrush(QColor(c, c, c, 10))
            painter.drawRoundedRect(self.rect(), 5, 5)

        # 折叠态只显示头像，不画文字
        if self.isCompacted:
            return

        # 文字区域：头像右侧到组件右边缘
        x0 = 44
        text_w = self.width() - x0 - 8

        # 第一行：名称
        painter.setPen(self.textColor())
        painter.setFont(self.font())
        painter.drawText(QRect(x0, 4, text_w, 18),
                         Qt.AlignVCenter | Qt.AlignLeft, self.name)

        # 第二行：下载计数（比第一行小 1 号，灰色）
        if self._subText:
            sub_font = QFont(self.font())
            sub_font.setPointSize(max(self.font().pointSize() - 1, 8))
            painter.setFont(sub_font)
            painter.setPen(QColor(150, 150, 150) if not isDarkTheme() else QColor(170, 170, 170))
            painter.drawText(QRect(x0, 22, text_w, 16),
                             Qt.AlignVCenter | Qt.AlignLeft, self._subText)
