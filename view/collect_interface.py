# coding:utf-8
import logging
import math
from uuid import uuid1

from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap, QMovie, QColor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget
from qfluentwidgets import ScrollArea, CardWidget, BodyLabel, CaptionLabel, \
    FlowLayout, SearchLineEdit, SegmentedToolWidget, TransparentToolButton, FluentIcon, InfoBarPosition, Flyout, \
    FlyoutAnimationType, InfoBarIcon, PipsPager, PipsScrollButtonDisplayMode, RoundMenu, Action, MessageBoxBase, \
    SubtitleLabel, LineEdit, MessageBox, BreadcrumbBar, setFont

from common.sqlite_util import SQLiteDatabase
from common.config import cfg
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicCollects, BookDownload
from utils.base_utils import get_current_time, truncate_string
from view.components.comic_search_card import DownloadFlyoutView
from view.components.folder_tree import TreeFrame
from view.components.auto_flow_layout import AutoFlowLayout
from view.components.info_bar_tip import show_tip


class CollectInterface(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('CollectInterface')

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
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '开始下载，可以到下载窗口查看进度，o(￣▽￣)ｄ', self,
                     InfoBarPosition.TOP_RIGHT)
        elif status == 'error':
            show_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，(。・＿・。)ﾉI’m sorry~', self,
                     InfoBarPosition.TOP_RIGHT)
        elif status == 'lock':
            show_tip(InfoBarIcon.WARNING, '前一个任务还在下载，请等会再下载吧(*￣︶￣)', self,
                     InfoBarPosition.TOP_RIGHT)


# 漫画收藏窗口
class CollectAreaInterface(ScrollArea):
    success = pyqtSignal(object)

    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        self.type = type
        self.banner = CollectWidget(name, type)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('collectInterface')
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
        self.folder_id = 0
        self.vBoxLayout = QVBoxLayout(self)

        # 搜索框
        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setPlaceholderText(name)
        self.lineEdit.searchSignal.connect(lambda text: self.search(text))
        self.lineEdit.textChanged.connect(lambda text: self.on_text_changed(text))
        self.lineEdit.returnPressed.connect(self.enter)
        self.vBoxLayout.addWidget(self.lineEdit, alignment=Qt.AlignCenter)

        # 面包屑
        self.breadcrumbBar = BreadcrumbBar(self)
        setFont(self.breadcrumbBar, 15)
        self.addBreadcrumbBar(str(self.folder_id), '收藏 > 首页')
        self.breadcrumbBar.currentItemChanged.connect(lambda routeKey: self.changeBreadcrumbBar(routeKey))
        self.vBoxLayout.addWidget(self.breadcrumbBar)

        self.flowLayout = AutoFlowLayout()
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

    # 面包屑切换
    def changeBreadcrumbBar(self, folder_id: str):
        # 查询记录
        self.folder_id = int(folder_id)
        self.search(None)

    # 面包屑添加
    def addBreadcrumbBar(self, folder_id: str, text: str):
        if not text:
            return
        w = SubtitleLabel(text)
        w.setObjectName(uuid1().hex)
        w.setAlignment(Qt.AlignCenter)
        self.breadcrumbBar.addItem(folder_id, text)

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
            # 查询文件夹数量
            folder_count = db.count_data('comic_collection_folder',
                                         conditions={'name': f'%{text}%', 'type': self.type,
                                                     'parent_id': self.folder_id})
            # 查询收藏记录数量
            collection_count = db.count_data('cmbok_collection_record',
                                             conditions={'name': f'%{text}%', 'type': self.type,
                                                         'folder_id': self.folder_id})
            pageNumber = math.ceil((folder_count + collection_count) / 16)
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
        self.comicCollects = ComicCollects(index=index, text=text, type=self.type, folder_id=self.folder_id)
        self.comicCollects.success.connect(self.updateView)
        self.comicCollects.start()

    # 流动布局
    def updateView(self, status, comics):
        if status == 'success':
            with SQLiteDatabase() as db:
                for comic in comics:
                    author = comic.author
                    if comic.is_folder == 'folder':
                        # 文件夹显示其下收藏文件数量
                        cnt = db.count_data('cmbok_collection_record', {'folder_id': comic.id})
                        author = f'{cnt} 个文件'
                    card = CollectCard(
                        id=comic.id,
                        cover=comic.cover,
                        name=comic.name,
                        author=author,
                        key=comic.key,
                        book_hash=comic.book_hash,
                        extension=comic.book_extension,
                        type=self.type,
                        is_folder=comic.is_folder
                    )
                    self.flowLayout.addWidget(card)
        self._layoutCards()

    # 窗口宽度变化时，卡片每行 2 个、宽度自适应
    def _layoutCards(self):
        n = 2
        lm = self.vBoxLayout.contentsMargins()
        fm = self.flowLayout.contentsMargins()
        avail = self.width() - lm.left() - lm.right() - fm.left() - fm.right()
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

    # 右键菜单
    def contextMenuEvent(self, event):
        menu = RoundMenu()
        menu.addAction(
            Action(FluentIcon.FOLDER, '添加文件夹', triggered=lambda: self.addFolder()))
        # 显示右键菜单
        menu.exec_(event.globalPos())

    # 添加文件夹
    def addFolder(self):
        w = CustomMessageBox(self)
        if w.exec():
            # 保存到数据库
            name = w.urlLineEdit.text()
            print('当前文件夹id=' + str(self.folder_id))
            with SQLiteDatabase() as db:
                db.insert_data('comic_collection_folder',
                               {'name': name, 'type': self.type, 'parent_id': self.folder_id,
                                'add_time': get_current_time()})

            current_widget = self.parent()
            while current_widget is not None:
                if isinstance(current_widget, CollectInterface):
                    current_widget.updateComicRecords(self.type)
                    return
                current_widget = current_widget.parent()  # 继续向上查找


# 自定义对话框
class CustomMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('添加文件夹', self)
        self.urlLineEdit = LineEdit(self)

        self.urlLineEdit.setPlaceholderText('请输入文件夹名称')
        self.urlLineEdit.setClearButtonEnabled(True)

        self.warningLabel = CaptionLabel()
        self.warningLabel.setTextColor("#cf1010", QColor(255, 28, 32))

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.urlLineEdit)
        self.viewLayout.addWidget(self.warningLabel)
        self.warningLabel.hide()

        self.yesButton.setText('确定')
        self.cancelButton.setText('取消')

        self.widget.setMinimumWidth(350)

    def validate(self):
        name = self.urlLineEdit.text()
        isValid = True
        if name == '' or name is None:
            self.warningLabel.setText("文件夹名称不能为空")
            isValid = False
        else:
            with SQLiteDatabase() as db:
                count = db.count_data('comic_collection_folder', {'name': name, 'type': self.parent().type})
                if count > 0:
                    self.warningLabel.setText("已有重复文件夹")
                    isValid = False

        self.warningLabel.setHidden(isValid)
        self.urlLineEdit.setError(not isValid)
        return isValid


# 收藏卡片
class CollectCard(CardWidget):
    def __init__(self, id, cover, name, author, key, book_hash=None, extension=None, type=1, is_folder=None,
                 parent=None):
        super().__init__(parent)
        self.type = type
        self.id = id
        self.name = name
        self.is_folder = is_folder

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(45, 55)
        self.load_image(cover)

        self.titleLabel = BodyLabel(truncate_string(name, 15), self)
        self.titleLabel.setToolTip(name)
        self.contentLabel = CaptionLabel(author, self)
        self.contentLabel.setToolTip(author)

        self.hBoxLayout = QHBoxLayout(self)
        self.setFixedWidth(385)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        # 按钮区域
        self.vBtnBoxLayout = QHBoxLayout()
        self.vBtnBoxLayout.addStretch()
        self.vBtnBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBtnBoxLayout.setAlignment(Qt.AlignRight)
        if self.is_folder != 'folder':
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
                self.operateBtn.clicked.connect(
                    lambda: self.downloadBook(cover, name, author, key, book_hash, extension))
        else:
            # 删除按钮
            self.operateBtn = TransparentToolButton(FluentIcon.DELETE)
            self.operateBtn.clicked.connect(self.deleteFolder)

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

    # 刷新记录
    def refresh(self):
        current_widget = self.parent()
        while current_widget is not None:
            if isinstance(current_widget, CollectInterface):
                current_widget.updateComicRecords(self.type)
                return
            current_widget = current_widget.parent()  # 继续向上查找

    # 删除文件夹
    def deleteFolder(self):
        title = '确认要删除这个文件夹?'
        content = "删除文件夹下的子文件夹和所有收藏"
        w = MessageBox(title, content, self.parent())
        w.setClosableOnMaskClicked(True)
        if w.exec():
            with SQLiteDatabase() as db:
                # 先取消文件下的所有收藏
                db.delete_data('cmbok_collection_record', {'folder_id': self.id})
                # 删除文件夹
                db.delete_data('comic_collection_folder', {'id': self.id})

            self.refresh()

    # 加载网络图片
    def load_image(self, image_url):
        # 设置默认加载中的图片
        self.load_loading_gif(':/cmbok/images/loading.gif')

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
            image = ':/cmbok/images/folder.png' if self.is_folder == 'folder' else ':/cmbok/images/comic_cover.png' if self.type == 1 else ':/cmbok/images/book_cover.png'
            self.load_fallback_image(image)  # 加载备用图片
            logging.info(f"错误: {reply.errorString()}")  # 打印错误信息

    def load_loading_gif(self, gif_path):
        """加载 GIF 动画"""
        movie = QMovie(gif_path)
        self.iconWidget.setMovie(movie)  # 将 GIF 设置到 QLabel
        movie.start()  # 启动 GIF 动画

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
            show_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self.parent().parent())

    # 显示漫画信息
    def showComicInfo(self, icon, title, author, path_word):
        Flyout.make(DownloadFlyoutView(icon, title, author, path_word), self.operateBtn, self,
                    aniType=FlyoutAnimationType.PULL_UP)

    # 下载图书
    def downloadBook(self, cover, name, author, key, book_hash, extension):
        # 内置账号模式：下载前检查今日是否已达上限，超过则提示并不再下载
        if cfg.get(cfg.use_zlibrary_builtin_account):
            from service.cmbok_service import get_builtin_download_count, BUILTIN_DAILY_LIMIT
            if get_builtin_download_count() >= BUILTIN_DAILY_LIMIT:
                MessageBox('提示', f'今日内置账号下载已达 {BUILTIN_DAILY_LIMIT} 本上限，请明天再试或改用自有账号下载。',
                           self.window()).exec()
                return
        else:
            from service.cmbok_service import get_logged_download_count, LOGGED_DAILY_LIMIT
            if get_logged_download_count(cfg.get(cfg.zlibrary_remix_userid)) >= LOGGED_DAILY_LIMIT:
                MessageBox('提示', f'今日下载已达 {LOGGED_DAILY_LIMIT} 本上限，请明天再试。',
                           self.window()).exec()
                return
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

    # 右键菜单
    def contextMenuEvent(self, event):
        menu = RoundMenu()

        menu.addAction(
            Action(FluentIcon.MOVE, '移动', triggered=self.openTreeFolder))

        # 显示右键菜单
        menu.exec_(event.globalPos())

    # 双击文件夹打开
    def mouseDoubleClickEvent(self, event):
        if self.is_folder == 'folder':
            # 更新数据
            current_widget = self.parent()
            while current_widget is not None:
                if isinstance(current_widget, CollectWidget):
                    current_widget.folder_id = self.id
                    current_widget.addBreadcrumbBar(str(self.id), self.name)
                    return
                current_widget = current_widget.parent()  # 继续向上查找

    # 移动收藏记录
    def openTreeFolder(self):
        w = TreeMessageBox(self.parent())
        if w.exec():
            # 遍历树节点获取选中的节点
            selected_items = w.treeFrame.tree.selectedItems()
            if selected_items:
                # 如果有选中的项，获取第一个选中项并输出名称
                selected_item = selected_items[0]
                folder_name = selected_item.text(0)  # 获取第一列的文本

                with SQLiteDatabase() as db:
                    # 通过名称查询文件夹id
                    folder = db.query_data('comic_collection_folder', {'name': folder_name, 'type': self.type})
                    folder_id = 0 if folder_name == '首页' else folder[0].id
                    # 更新记录到文件夹下
                    if self.is_folder == 'folder':
                        db.update_data('comic_collection_folder', {'parent_id': folder_id}, {'id': self.id})
                    else:
                        db.update_data('cmbok_collection_record', {'folder_id': folder_id}, {'id': self.id})

                    self.refresh()


# 树形菜单
class TreeMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 从父元素找到当前类型
        type = 1
        current_widget = self.parent()
        while current_widget is not None:
            if isinstance(current_widget, CollectWidget):
                type = current_widget.type
            current_widget = current_widget.parent()  # 继续向上查找

        self.treeFrame = TreeFrame(type)
        self.viewLayout.addWidget(self.treeFrame)

        self.yesButton.setText('确定')
        self.cancelButton.setText('取消')

        self.widget.setMinimumWidth(350)

    def validate(self):
        isValid = True
        selected_items = self.treeFrame.tree.selectedItems()
        if not selected_items:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请选择一个文件夹', self)
            isValid = False
        return isValid

    # 收藏窗口
