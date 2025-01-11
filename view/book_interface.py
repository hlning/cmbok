# coding:utf-8

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, InfoBarPosition, InfoBarIcon

from common.style_sheet import StyleSheet
from common.view_util import info_bar_tip
from components.book_search_card import BookSearchCardView


# 图书窗口
class BookInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.basicInputView = BookSearchCardView('开始搜索', self.view)
        self.basicInputView.success.connect(self.infoShow)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('bookInterface')
        StyleSheet.BOOK_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(60, 20, 30, 40)
        self.vBoxLayout.addWidget(self.basicInputView)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

    # 温馨提示
    def infoShow(self, status):
        if status == 'success':
            info_bar_tip(InfoBarIcon.INFORMATION, '温馨提示', '开始下载，可以到下载窗口查看进度，o(￣▽￣)ｄ', self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'error':
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，(。・＿・。)ﾉI’m sorry~', self,
                         InfoBarPosition.TOP_RIGHT)
