# coding:utf-8

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, ElevatedCardWidget, ImageLabel, \
    CaptionLabel, FlowLayout

from view.components.auto_flow_layout import AutoFlowLayout
from common.style_sheet import StyleSheet
from view.components.convert_tool_card import ToolMessageBox


class ToolInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('ToolInterface')

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.topdf = ToolCard(QImage(':/cmbok/images/to_pdf.png'), '转PDF', '支持常见格式转换成PDF')
        self.topdf.clicked.connect(lambda: self.show_box(1))
        self.mergepdf = ToolCard(QImage(':/cmbok/images/merge_pdf.png'), '合并PDF', '支持常见格式合并成PDF')
        self.mergepdf.clicked.connect(lambda: self.show_box(2))
        self.toepub = ToolCard(QImage(':/cmbok/images/to_epub.png'), '转EPUB', '支持常见格式转换成EPUB')
        self.toepub.clicked.connect(lambda: self.show_box(3))
        self.todoc = ToolCard(QImage(':/cmbok/images/to_doc.png'), '转DOC', '支持常见格式转换成DOC')
        self.todoc.clicked.connect(lambda: self.show_box(4))

        self.flowLayout = AutoFlowLayout()
        self.flowLayout.addWidget(self.topdf)
        self.flowLayout.addWidget(self.mergepdf)
        self.flowLayout.addWidget(self.toepub)
        self.flowLayout.addWidget(self.todoc)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        StyleSheet.COMIC_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(40)
        self.vBoxLayout.addLayout(self.flowLayout)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self._layoutCards()

    # 窗口宽度变化时，卡片每行 5 个、宽度自适应
    def _layoutCards(self):
        n = 5
        lm = self.vBoxLayout.contentsMargins()
        fm = self.flowLayout.contentsMargins()
        avail = self.viewport().width() - lm.left() - lm.right() - fm.left() - fm.right()
        hs = self.flowLayout.horizontalSpacing()
        hs = hs if hs and hs > 0 else 10
        card_w = max(int(avail / n) - hs, 100)
        for i in range(self.flowLayout.count()):
            item = self.flowLayout.itemAt(i)
            if item and item.widget():
                item.widget().setFixedWidth(card_w)
        self.flowLayout.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layoutCards()

    def show_box(self, type):
        w = ToolMessageBox(type, self)
        w.exec()


class ToolCard(ElevatedCardWidget):

    def __init__(self, iconPath: str, title: str, desc: str, parent=None):
        super().__init__(parent)

        self.iconWidget = ImageLabel(iconPath, self)
        self.title = CaptionLabel(title, self)
        self.title.setObjectName('titleLabel')

        self.desc = CaptionLabel(desc, self)
        self.desc.setObjectName('contentLabel')

        self.iconWidget.scaledToHeight(68)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setAlignment(Qt.AlignCenter)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignCenter)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.title, 0, Qt.AlignHCenter | Qt.AlignBottom)
        self.vBoxLayout.addWidget(self.desc, 0, Qt.AlignHCenter | Qt.AlignBottom)

        self.setFixedSize(160, 175)
        StyleSheet.SAMPLE_CARD.apply(self)
