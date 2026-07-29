# coding:utf-8
"""空数据占位组件：图标 + 文字，垂直居中显示。

用于漫画/图书搜索、收藏、下载管理等界面的空数据态。
图标用 qfluentwidgets FluentIconBase（IconWidget 内部 drawIcon 自动随主题黑/白），
文字用 BodyLabel 禁用态取灰色。"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import IconWidget, BodyLabel, FluentIconBase


class EmptyStateWidget(QWidget):
    """空数据占位：图标 + 文字，垂直居中"""

    def __init__(self, icon: FluentIconBase, text: str, parent=None, icon_size=56):
        super().__init__(parent)
        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(icon_size, icon_size)

        self.textLabel = BodyLabel(text, self)
        self.textLabel.setEnabled(False)  # 禁用态：浅灰色文字

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setAlignment(Qt.AlignCenter)
        self.vBoxLayout.setSpacing(10)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.textLabel, 0, Qt.AlignHCenter)
        self.vBoxLayout.addStretch(1)

    def setText(self, text: str):
        self.textLabel.setText(text)

    def setIcon(self, icon: FluentIconBase):
        self.iconWidget.setIcon(icon)
