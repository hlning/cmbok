# coding:utf-8
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QHBoxLayout
from qfluentwidgets import IconWidget, TextWrap, SingleDirectionScrollArea

from common.style_sheet import StyleSheet


class LinkCard(QFrame):

    def __init__(self, icon, title, content, url, parent=None):
        super().__init__(parent=parent)
        self.url = QUrl(url)
        self.setFixedHeight(270)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)
        # self.urlWidget = IconWidget(FluentIcon.DOWNLOAD, self)

        self.__initWidget()

    def __initWidget(self):
        self.setCursor(Qt.PointingHandCursor)

        self.iconWidget.setFixedSize(180, 80)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(15, 24, 0, 13)
        self.vBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addSpacing(16)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # self.urlWidget.setFixedSize(16, 16)
        # self.urlWidget.move(170, 230)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        QDesktopServices.openUrl(self.url)


class LinkCardView(SingleDirectionScrollArea):
    """ Link card view """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Horizontal)
        self.view = QWidget(self)
        self.hBoxLayout = QHBoxLayout(self.view)

        self.hBoxLayout.setContentsMargins(36, 0, 36, 0)
        self.hBoxLayout.setSpacing(12)
        self.hBoxLayout.setAlignment(Qt.AlignLeft)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setObjectName('view')
        StyleSheet.LINK_CARD.apply(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjustCardWidths()

    def _adjustCardWidths(self):
        """按视口宽度自适应卡片宽度，与搜索框宽度保持一致"""
        margins = self.hBoxLayout.contentsMargins()
        avail = self.viewport().width() - margins.left() - margins.right()
        spacing = self.hBoxLayout.spacing()
        n = self.hBoxLayout.count()
        if n == 0 or avail <= 0:
            return
        card_w = max(180, (avail - spacing * (n - 1)) // n)
        for i in range(n):
            item = self.hBoxLayout.itemAt(i)
            if item and item.widget():
                item.widget().setFixedWidth(card_w)

    def addCard(self, icon, title, content, url):
        """ add link card """
        card = LinkCard(icon, title, content, url, self.view)
        self.hBoxLayout.addWidget(card, 0, Qt.AlignLeft)
        self._adjustCardWidths()
