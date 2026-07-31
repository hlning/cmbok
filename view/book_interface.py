# coding:utf-8

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, InfoBarPosition, InfoBarIcon

from common.style_sheet import StyleSheet
from view.components.book_search_card import BookSearchCardView
from view.components.info_bar_tip import show_tip


# 图书窗口
class BookInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('BookInterface')

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.basicInputView = BookSearchCardView('📚图书搜索', self.view)
        self.basicInputView.success.connect(self.infoShow)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('bookInterface')
        StyleSheet.BOOK_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        # 外层左右边距交由 BookSearchCardView 内部控制（36），与漫画搜索页面结构保持一致
        self.vBoxLayout.setContentsMargins(0, 20, 0, 15)
        self.vBoxLayout.addWidget(self.basicInputView, 1)

    # 温馨提示
    def infoShow(self, status):
        if status == 'success':
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '开始下载，可以到下载窗口查看进度，o(￣▽￣)ｄ', self,
                     InfoBarPosition.TOP_RIGHT)
        elif status == 'error':
            show_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，(。・＿・。)ﾉI’m sorry~', self,
                     InfoBarPosition.TOP_RIGHT)

    # 切回图书搜索时重排卡片宽度
    def refreshCards(self):
        self.basicInputView.refreshCardWidth()
