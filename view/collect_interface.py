# coding:utf-8
import logging
import math

from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget
from qfluentwidgets import ScrollArea, CardWidget, BodyLabel, CaptionLabel, \
    FlowLayout, SearchLineEdit, SegmentedToolWidget, TransparentToolButton, FluentIcon, InfoBarPosition, Flyout, \
    FlyoutAnimationType, InfoBarIcon, PipsPager, PipsScrollButtonDisplayMode

from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from common.util import truncate_string
from common.view_util import info_bar_tip
from components.comic_search_card import DownloadFlyoutView
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicCollects, BookDownload


class CollectInterface(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('CollectInterface')
        self.resize(400, 400)

        self.pivot = SegmentedToolWidget(self)
        self.stackedWidget = QStackedWidget(self)

        self.hBoxLayout = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        # 顶部导航
        # 漫画收藏
        self.collectAreaInterface = CollectAreaInterface('请输入漫画名搜索', 1)
        self.collectAreaInterface.success.connect(self.infoShow)
        self.addSubInterface(self.collectAreaInterface, '漫画', MyFluentIcon.COMIC)
        # 图书收藏
        self.bookAreaInterface = CollectAreaInterface('请输入图书名搜索', 2)
        self.bookAreaInterface.success.connect(self.infoShow)
        self.addSubInterface(self.bookAreaInterface, '图书', MyFluentIcon.BOOK)

        self.hBoxLayout.addWidget(self.pivot, 0, Qt.AlignCenter)
        self.vBoxLayout.addLayout(self.hBoxLayout)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

        self.stackedWidget.setCurrentWidget(self.collectAreaInterface)
        self.pivot.setCurrentItem(self.collectAreaInterface.objectName())
        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

        self.stackedWidget.currentChanged.connect(lambda index: self.updateComicRecords(index + 1))

    def addSubInterface(self, widget: QLabel, objectName, icon):
        widget.setObjectName(objectName)
        widget.setAlignment(Qt.AlignCenter)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, icon=icon)

    # 更新漫画收藏记录
    def updateComicRecords(self, type=1):
        if type == 1:
            self.collectAreaInterface.banner.search(None)
        else:
            self.bookAreaInterface.banner.search(None)

    def infoShow(self, status):
        if status == 'success':
            info_bar_tip(InfoBarIcon.INFORMATION, '温馨提示', '开始下载，可以到下载窗口查看进度，o(￣▽￣)ｄ', self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'error':
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，(。・＿・。)ﾉI’m sorry~', self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'lock':
            info_bar_tip(InfoBarIcon.WARNING, '前一个任务还在下载，请等会再下载吧(*￣︶￣)', self,
                         InfoBarPosition.TOP_RIGHT)


# 漫画收藏窗口
class CollectAreaInterface(ScrollArea):
    success = pyqtSignal(object)

    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.banner = CollectWidget(name, type)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('comicCollectInterface')
        StyleSheet.COMIC_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.setAlignment(Qt.AlignTop)


# 漫画收藏记录窗口
class CollectWidget(QWidget):
    success = pyqtSignal()

    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.type = type
        self.vBoxLayout = QVBoxLayout(self)

        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setPlaceholderText(name)
        self.lineEdit.searchSignal.connect(lambda text: self.search(text))
        self.lineEdit.textChanged.connect(lambda text: self.on_text_changed(text))
        self.lineEdit.returnPressed.connect(self.enter)

        self.vBoxLayout.addWidget(self.lineEdit, alignment=Qt.AlignCenter)

        self.flowLayout = FlowLayout()
        # 查询收藏记录
        self.vBoxLayout.addLayout(self.flowLayout)

        # 分页器
        self.pager = PipsPager(Qt.Horizontal)
        # 设置当前页码
        self.pager.setCurrentIndex(0)
        self.setPage(None)
        # 始终显示前进和后退按钮
        self.pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        # 页码切换
        self.pager.currentIndexChanged.connect(lambda index: self.getRecords(self.lineEdit.text(), index))

        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignCenter)

    # 回车搜索
    def enter(self):
        comic_name = self.lineEdit.text()
        self.search(comic_name)

    # 搜索内容监听
    def on_text_changed(self, text):
        if text == "":
            self.search(None)

    # 搜索
    def search(self, text):
        self.setPage(text)

    # 设置页码
    def setPage(self, text):
        with SQLiteDatabase() as db:
            # 查询总数更新分页器
            count = db.count_data('cmbok_collection_record',
                                  conditions={'name': f'%{text}%', 'type': self.type})
            pageNumber = math.ceil(count / 16)
            # 设置当前页码
            if pageNumber == 0:
                self.pager.setCurrentIndex(0)
            # 设置页数
            self.pager.setPageNumber(pageNumber)
            # 设置圆点数量
            self.pager.setVisibleNumber(10 if pageNumber > 10 else pageNumber)

    # 获取收藏记录
    def getRecords(self, text, index):
        # 清空流动布局内容
        self.flowLayout.takeAllWidgets()
        self.comicCollects = ComicCollects(index=index, text=text, type=self.type)
        self.comicCollects.success.connect(self.updateView)
        self.comicCollects.start()

    def updateView(self, status, comics):
        if status == 'success':
            for comic in comics:
                card = CollectCard(
                    cover=comic.cover,
                    name=comic.name,
                    author=comic.author,
                    key=comic.key,
                    book_hash=comic.book_hash,
                    extension=comic.book_extension,
                    type=self.type
                )
                self.flowLayout.addWidget(card)


# 收藏卡片
class CollectCard(CardWidget):
    def __init__(self, cover, name, author, key, book_hash=None, extension=None, type=1, parent=None):
        super().__init__(parent)
        self.type = type

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(45, 55)
        self.load_image(cover)

        self.titleLabel = BodyLabel(truncate_string(name, 15), self)
        if len(name) > 15:
            self.titleLabel.setToolTip(name)
        self.contentLabel = CaptionLabel(author, self)
        if len(author) > 20:
            self.contentLabel.setToolTip(author)

        self.hBoxLayout = QHBoxLayout(self)
        self.setFixedWidth(395)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        # 按钮区域
        self.vBtnBoxLayout = QHBoxLayout()
        self.vBtnBoxLayout.addStretch()
        self.vBtnBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBtnBoxLayout.setAlignment(Qt.AlignRight)
        # 收藏
        self.collectBtn = TransparentToolButton(MyFluentIcon.HAVE_COLLECT)
        self.collectBtn.setFixedWidth(30)
        self.collectBtn.clicked.connect(lambda: self.collect(key, type))

        self.vBtnBoxLayout.addWidget(self.collectBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)

        if type == 1:
            # 获取章节
            self.operateBtn = TransparentToolButton(FluentIcon.SEND)
            self.operateBtn.clicked.connect(lambda: self.showComicInfo(cover, name, author, key))
        else:
            # 下载图书
            self.operateBtn = TransparentToolButton(FluentIcon.DOWNLOAD)
            self.operateBtn.clicked.connect(lambda: self.downloadBook(cover, name, author, key, book_hash, extension))

        self.operateBtn.setFixedWidth(30)
        self.vBtnBoxLayout.addWidget(self.operateBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 按钮区域

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addLayout(self.vBtnBoxLayout)

    # 加载网络图片
    def load_image(self, image_url):
        """从指定的 URL 加载图片"""
        self.manager = QNetworkAccessManager(self)
        self.manager.finished.connect(self.on_image_loaded)

        request = QNetworkRequest(QUrl(image_url))
        self.manager.get(request)  # 发送请求

    def on_image_loaded(self, reply):
        """当图片加载完成时的处理函数"""
        if reply.error() == reply.NoError:
            image_data = reply.readAll()  # 读取返回的图片数据
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)  # 将读取的数据加载到 QPixmap
            self.iconWidget.setPixmap(pixmap)  # 设置标签的图片
        else:
            self.load_fallback_image(
                ':/cmbok/images/comic_cover.png' if self.type == 1 else ':/cmbok/images/book_cover.png')  # 加载备用图片
            logging.info(f"错误: {reply.errorString()}")  # 打印错误信息

    def load_fallback_image(self, fallback_image_path):
        """加载备用本地图片"""
        pixmap = QPixmap(fallback_image_path)
        if not pixmap.isNull():
            self.iconWidget.setPixmap(pixmap)  # 设置标签的备用图片
        else:
            logging.info("备用图片加载失败")  # 处理备用图片加载失败的情况

    # 取消收藏
    def collect(self, key, type):
        with SQLiteDatabase() as db:
            # 取消收藏
            db.delete_data('cmbok_collection_record', {'key': key, 'type': type})
            self.parent().search(None)
            info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self.parent().parent())

    # 显示漫画信息
    def showComicInfo(self, icon, title, author, path_word):
        Flyout.make(DownloadFlyoutView(icon, title, author, path_word), self.operateBtn, self,
                    aniType=FlyoutAnimationType.PULL_UP)

    # 下载图书
    def downloadBook(self, cover, name, author, key, book_hash, extension):
        book = {
            'cover': cover,
            'title': name,
            'author': author,
            'id': key,
            'hash': book_hash,
            'extension': extension
        }
        self.bookDownload = BookDownload(book=book)
        self.bookDownload.success.connect(self.downloadBookStatus)
        self.bookDownload.start()

    def downloadBookStatus(self, status):
        current_widget = self.parent()
        while current_widget is not None:
            if isinstance(current_widget, CollectAreaInterface):
                current_widget.success.emit(status)
                return
            current_widget = current_widget.parent()  # 继续向上查找
# 收藏窗口
