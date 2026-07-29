# coding:utf-8
"""账号头像组件：导航展开时两行显示（第一行用户名/未登录，第二行当日下载计数）。

qfluentwidgets 的 NavigationAvatarWidget 仅单行绘制 name，无法显示下载计数，
故子类化重写 paintEvent，展开时画两行。"""
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QFont, QFontMetrics
from qfluentwidgets import NavigationAvatarWidget, isDarkTheme


class AccountAvatarWidget(NavigationAvatarWidget):
    """账号头像：展开时两行（名称 + 下载计数）"""

    def __init__(self, name, avatar=None, parent=None):
        super().__init__(name, avatar, parent)
        self._subText = ''
        # 加高给两行文字留白（默认高度 36 不够；两行按实际高度动态垂直居中）
        self.setFixedHeight(60)

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

        # 文字区域：头像右侧到组件右边缘（右边留 4px，避免文字贴边）
        x0 = 40
        text_w = self.width() - x0 - 4
        if text_w <= 0:
            text_w = self.width() - x0

        # 两行字体：第一行名称（默认字号），第二行下载计数（小 2 号）
        font1 = self.font()
        font2 = QFont(font1)
        font2.setPointSize(max(font1.pointSize() - 1, 7))
        fm1 = QFontMetrics(font1)
        fm2 = QFontMetrics(font2)

        # 两行垂直居中分布在组件高度内（按实际高度动态计算，避免底部被裁）
        gap = 2
        total_h = fm1.height() + gap + fm2.height()
        y1 = max(0, (self.height() - total_h) // 2)
        y2 = y1 + fm1.height() + gap

        # 第一行：名称（超长省略）
        painter.setPen(self.textColor())
        painter.setFont(font1)
        name = fm1.elidedText(self.name, Qt.ElideRight, text_w)
        painter.drawText(QRect(x0, y1, text_w, fm1.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, name)

        # 第二行：下载计数（灰色）
        if self._subText:
            painter.setFont(font2)
            painter.setPen(QColor(150, 150, 150) if not isDarkTheme() else QColor(170, 170, 170))
            sub = fm2.elidedText(self._subText, Qt.ElideRight, text_w)
            painter.drawText(QRect(x0, y2, text_w, fm2.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, sub)
