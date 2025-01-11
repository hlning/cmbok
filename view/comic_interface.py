# coding:utf-8
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPixmap, QPainter, QColor, QBrush, QPainterPath, QLinearGradient
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from qfluentwidgets import ScrollArea, isDarkTheme, InfoBarIcon, InfoBarPosition

from common.style_sheet import StyleSheet
from common.view_util import info_bar_tip
from components.comic_search_card import ComicSearchCardView
from components.link_card import LinkCardView


class ComicInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.banner = BannerWidget(self)

        self.basicInputView = ComicSearchCardView('开始搜索', self.view)
        self.basicInputView.success.connect(self.infoShow)

        self.__initWidget()


    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('comicInterface')
        StyleSheet.COMIC_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(40)
        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.addWidget(self.basicInputView)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

    def infoShow(self, status):
        if status == 'success':
            info_bar_tip(InfoBarIcon.INFORMATION, '温馨提示', '开始下载，可以到下载窗口查看进度，o(￣▽￣)ｄ', self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'error':
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，(。・＿・。)ﾉI’m sorry~', self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'lock':
            info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '前一个任务还在下载，请等会再下载吧(*￣︶￣)', self,
                         InfoBarPosition.TOP_RIGHT)


class BannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(336)

        self.vBoxLayout = QVBoxLayout(self)
        self.galleryLabel = QLabel('我看过的漫画', self)
        self.banner = QPixmap(':/cmbok/images/header.jpeg')
        self.linkCardView = LinkCardView(self)

        self.galleryLabel.setObjectName('galleryLabel')

        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 20, 0, 0)
        self.vBoxLayout.addWidget(self.galleryLabel)
        self.vBoxLayout.addWidget(self.linkCardView, 1, Qt.AlignBottom)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.linkCardView.addCard(
            ':/cmbok/images/recommend1.jpg',
            '炎拳',
            '就因为一个被称为<冰之魔女>的祝福者 世界被冰雪与飢饿还有疯狂所笼罩。 对主人公阿格尼所降下的祝福...',
            ''
        )

        self.linkCardView.addCard(
            ':/cmbok/images/recommend2.jpg',
            '恋如雨止',
            '外表看似很酷，但情感表达却十分笨拙的17岁女高中生—— 橘 。对她打工的家庭餐厅的店长，45岁的近藤正...',
            ''
        )

        self.linkCardView.addCard(
            ':/cmbok/images/recommend3.jpg',
            '黄金神威',
            '黄金神威漫画 ，“生存”就是“战斗”，在北部的土地上，探寻生命的意义，寻找黄金，生存竞争。一掘千金的...',
            ''
        )

        self.linkCardView.addCard(
            ':/cmbok/images/recommend4.jpg',
            '大剑',
            '大陆上怪物横行危害人类，而为了对抗它们某神秘组织制造出了一些半人半妖的妖怪猎人，并称之为“大剑”...',
            ''
        )

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        w, h = self.width(), self.height()
        path.addRoundedRect(QRectF(0, 0, w, h), 10, 10)
        path.addRect(QRectF(0, h - 50, 50, 50))
        path.addRect(QRectF(w - 50, 0, 50, 50))
        path.addRect(QRectF(w - 50, h - 50, 50, 50))
        path = path.simplified()

        gradient = QLinearGradient(0, 0, 0, h)

        if not isDarkTheme():
            gradient.setColorAt(0, QColor(207, 216, 228, 255))
            gradient.setColorAt(1, QColor(207, 216, 228, 0))
        else:
            gradient.setColorAt(0, QColor(0, 0, 0, 255))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))

        painter.fillPath(path, QBrush(gradient))

        pixmap = self.banner.scaled(
            self.size(), transformMode=Qt.SmoothTransformation)
        painter.fillPath(path, QBrush(pixmap))
