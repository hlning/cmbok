# coding:utf-8
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPainter, QColor, QPainterPath
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QHBoxLayout
from qfluentwidgets import IconWidget, TextWrap, SingleDirectionScrollArea, ElevatedCardWidget, isDarkTheme

from common.style_sheet import StyleSheet


class LinkCard(ElevatedCardWidget):

    def __init__(self, icon, title, content, url, parent=None):
        super().__init__(parent=parent)
        self.url = QUrl(url)
        self.setMinimumHeight(260)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(content, self)
        self.contentLabel.setWordWrap(True)

        self.__initWidget()

    # 正常态背景色
    def _normalBackgroundColor(self):
        return QColor(248, 248, 248) if not isDarkTheme() else QColor(45, 45, 45)

    # 悬停态背景色
    def _hoverBackgroundColor(self):
        return QColor(248, 248, 248) if not isDarkTheme() else QColor(50, 50, 50)

    def __initWidget(self):
        self.setCursor(Qt.PointingHandCursor)

        self.iconWidget.setFixedSize(180, 80)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(15, 24, 15, 13)
        # 图片、漫画名、漫画介绍居中显示
        self.vBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignHCenter)
        self.vBoxLayout.addSpacing(30)
        self.titleLabel.setAlignment(Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.contentLabel.setAlignment(Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjustCoverSize()

    # 封面随卡片宽度等比缩放（保持 180:80 比例）
    def _adjustCoverSize(self):
        lm = self.vBoxLayout.contentsMargins()
        w = self.width() - lm.left() - lm.right()
        if w <= 0:
            return
        # 高度按比例缩放，但封顶 100，避免宽窗口封面过大挤压描述文字
        cover_h = min(int(w * 80 / 180), 130)
        cover_w = int(cover_h * 180 / 80)
        self.iconWidget.setFixedSize(cover_w, cover_h)

    def paintEvent(self, e):
        # 卡片顶部圆角、底部直角；边框只画上、左、右三边（去掉下边框）
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = self.borderRadius
        d = 2 * r

        # 背景：上圆角、下直角
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.backgroundColor)
        bg = QPainterPath()
        bg.moveTo(1, r)
        bg.arcTo(1, 1, d, d, -180, -90)
        bg.lineTo(w - r, 1)
        bg.arcTo(w - d - 1, 1, d, d, 90, -90)
        bg.lineTo(w - 1, h - 1)
        bg.lineTo(1, h - 1)
        bg.closeSubpath()
        painter.drawPath(bg)

        # 边框：只画上、左、右三边（底部直角，不画下边框）
        painter.setPen(QColor(0, 0, 0, 48) if isDarkTheme() else QColor(0, 0, 0, 12))
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(1, h - 1)
        path.lineTo(1, r)
        path.arcTo(1, 1, d, d, -180, -90)
        path.lineTo(w - r, 1)
        path.arcTo(w - d - 1, 1, d, d, 90, -90)
        path.lineTo(w - 1, h - 1)
        painter.drawPath(path)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        QDesktopServices.openUrl(self.url)

    def _startElevateAni(self, start, end):
        # 禁用 ElevatedCardWidget 的位移抬起动画：启动时若鼠标已悬停于卡片上，
        # enterEvent 会把未就绪的 pos 记为 _originalPos，离开后恢复到错误位置，
        # 造成卡片重叠且无法复原。保留 hover 背景色与阴影变化，仅取消位移。
        pass


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
        # 垂直顶部对齐：卡片高度跟随内容，避免被拉伸后封面上方留白、底部介绍文字被裁
        self.hBoxLayout.addWidget(card, 0, Qt.AlignLeft | Qt.AlignTop)
        self._adjustCardWidths()
