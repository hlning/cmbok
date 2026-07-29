# coding:utf-8
import logging
import math
import os
import time
import traceback
import uuid
from functools import partial

from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer, QEvent, QRectF
from PyQt5.QtGui import QPixmap, QMovie, QCursor, QIcon, QColor, QPainter, QDesktopServices, QPainterPath
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QMainWindow, \
    QDesktopWidget, QFrame
from qfluentwidgets import ScrollArea, CardWidget, ElevatedCardWidget, BodyLabel, FlowLayout, SearchLineEdit, SegmentedToolWidget, \
    FluentIcon, InfoBarPosition, Flyout, \
    FlyoutAnimationType, InfoBarIcon, PipsPager, PipsScrollButtonDisplayMode, FlyoutViewBase, PrimaryPushButton, \
    SingleDirectionScrollArea, CheckBox, StateToolTip, MessageBox, MessageBoxBase, TransparentToolButton, LineEdit, \
    Theme, PrimaryToolButton, themeColor, isDarkTheme, ThemeColor

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicWebsiteChapterImages, EpubThread, WebsiteChapterFetchThread
from utils.base_utils import truncate_string, get_current_time, get_directories
from utils.utils_files_and_folders import del_folder, move_files
from view.components.auto_flow_layout import AutoFlowLayout
from view.components.empty_state_widget import EmptyStateWidget
from view.components.info_bar_tip import show_tip


def _tinted_icon(fluent_icon, color):
    """将 FluentIcon 渲染为指定颜色的图标（用于红色删除按钮等）"""
    pix = QPixmap(fluent_icon.path(Theme.LIGHT))
    if pix.isNull():
        return QIcon(fluent_icon)
    tinted = QPixmap(pix.size())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.fillRect(tinted.rect(), QColor(color))
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawPixmap(0, 0, pix)
    p.end()
    return QIcon(tinted)


class FlatColorToolButton(PrimaryToolButton):
    """扁平实色按钮：自绘背景，无圆角/边框/阴影，不受主题切换 QSS 覆盖"""

    def _normalColor(self):
        raise NotImplementedError

    def _hoverColor(self):
        return self._normalColor()

    def _pressedColor(self):
        return self._normalColor()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        if not self.isEnabled():
            color = self._normalColor()
            painter.setOpacity(0.5)
        elif self.isPressed:
            color = self._pressedColor()
        elif self.isHover:
            color = self._hoverColor()
        else:
            color = self._normalColor()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        # 左圆角、右直角
        r = 5
        rect = self.rect()
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top() + r)
        path.arcTo(QRectF(rect.left(), rect.top(), 2 * r, 2 * r), 180, -90)
        path.lineTo(rect.right(), rect.top())
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left() + r, rect.bottom())
        path.arcTo(QRectF(rect.left(), rect.bottom() - 2 * r, 2 * r, 2 * r), 270, -90)
        path.closeSubpath()
        painter.drawPath(path)
        if self._icon is not None:
            if not self.isEnabled():
                painter.setOpacity(0.786)
            w, h = 14, 14
            x = (self.width() - w) / 2
            y = (self.height() - h) / 2
            self._drawIcon(self._icon, painter, QRectF(x, y, w, h))


class PrimaryFlatToolButton(FlatColorToolButton):
    """主题色扁平按钮（编辑）"""

    def _normalColor(self):
        return themeColor()

    def _hoverColor(self):
        return ThemeColor.DARK_1.color() if not isDarkTheme() else ThemeColor.LIGHT_1.color()

    def _pressedColor(self):
        return ThemeColor.DARK_2.color() if not isDarkTheme() else ThemeColor.LIGHT_3.color()


class RedFlatToolButton(FlatColorToolButton):
    """红色扁平按钮（删除）"""

    def _normalColor(self):
        return QColor(201, 79, 79)

    def _hoverColor(self):
        return QColor(197, 47, 47)

    def _pressedColor(self):
        return QColor(168, 38, 38)


class WebsiteInterface(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('WebsiteInterface')

        self.pivot = SegmentedToolWidget(self)
        self.stackedWidget = QStackedWidget(self)

        self.hBoxLayout = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        # 顶部导航
        # 漫画站点
        self.comicAreaInterface = WebsiteAreaInterface('请输入名称搜索', 1)
        self.addSubInterface(self.comicAreaInterface, '漫画站点', MyFluentIcon.COMIC)
        # 图书站点
        # self.bookAreaInterface = WebsiteAreaInterface('请输入名称搜索', 2)
        # self.addSubInterface(self.bookAreaInterface, '图书站点', MyFluentIcon.BOOK)

        self.hBoxLayout.addWidget(self.pivot, 0, Qt.AlignCenter)
        self.vBoxLayout.addLayout(self.hBoxLayout)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

        self.stackedWidget.setCurrentWidget(self.comicAreaInterface)
        self.pivot.setCurrentItem(self.comicAreaInterface.objectName())
        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

        self.stackedWidget.currentChanged.connect(lambda index: self.updateWebsiteRecords(index + 1))

    def addSubInterface(self, widget: QLabel, objectName, icon):
        widget.setObjectName(objectName)
        widget.setAlignment(Qt.AlignCenter)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, icon=icon)

    # 更新漫画站点记录
    def updateWebsiteRecords(self, type=1):
        if type == 1:
            self.comicAreaInterface.banner.search(None)


# 漫画站点窗口
class WebsiteAreaInterface(ScrollArea):
    success = pyqtSignal(object)

    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.banner = WebsitWidget(name, type)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('websiteInterface')
        StyleSheet.COMIC_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.setAlignment(Qt.AlignTop)


# 漫画站点记录窗口
class WebsitWidget(QWidget):
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

        # 搜索框 + 新增按钮
        self.searchLayout = QHBoxLayout()
        self.searchLayout.setSpacing(8)
        self.searchLayout.addStretch()
        self.searchLayout.addWidget(self.lineEdit)
        if self.type == 1:
            self.addBtn = PrimaryToolButton(FluentIcon.ADD)
            self.addBtn.setFixedSize(44, 33)
            self.addBtn.setToolTip('新增站点')
            self.addBtn.clicked.connect(self.addWebsite)
            self.searchLayout.addWidget(self.addBtn)
        self.searchLayout.addStretch()
        self.vBoxLayout.addLayout(self.searchLayout)

        # 站点卡片容器：flowLayout 放入 flowContainer，再由 resultStack 与空状态切换
        self.flowContainer = QWidget(self)
        self.flowLayout = AutoFlowLayout(self.flowContainer)
        self.resultStack = QStackedWidget(self)
        self.resultStack.addWidget(self.flowContainer)  # 页0：站点卡片
        self.emptyWidget = EmptyStateWidget(FluentIcon.FOLDER, '没有站点请添加~', self)
        self.resultStack.addWidget(self.emptyWidget)  # 页1：空状态
        self.resultStack.setCurrentWidget(self.emptyWidget)
        self.vBoxLayout.addWidget(self.resultStack, 1)

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

    # 新增站点
    def addWebsite(self):
        dlg = WebsiteEditDialog(self.window())
        if dlg.exec():
            with SQLiteDatabase() as db:
                db.insert_data('comic_website', dlg.get_data())
            self.search(None)
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '新增成功', self.window(), InfoBarPosition.TOP)

    # 设置页码
    def setPage(self, text):
        if self.type == 1:
            with SQLiteDatabase() as db:
                websites = db.query_data('comic_website')
                count = len(websites)
                pageNumber = math.ceil(count / 16)
                # 设置当前页码
                if pageNumber == 0:
                    self.pager.setCurrentIndex(0)
                # 设置页数
                self.pager.setPageNumber(pageNumber)
                # 设置圆点数量
                self.pager.setVisibleNumber(10 if pageNumber > 10 else pageNumber)

    # 获取站点记录
    def getRecords(self, text, index):
        # 清空流动布局内容
        self.flowLayout.takeAllWidgets()
        origin_text = text  # 原始搜索词（None/空=未搜索，查全部）
        text = text or 'None'
        if self.type == 1:
            with SQLiteDatabase() as db:
                websites = db.query_data('comic_website', conditions={'name': f'%{text}%'})
                for website in websites:
                    card = WebsiteCard(
                        id=website.id,
                        name=website.name,
                        icon=website.icon,
                        url=website.url,
                        comic_cover_dom=website.comic_cover_dom,
                        comic_name_dom=website.comic_name_dom,
                        chapter_name_dom=website.chapter_name_dom,
                        chapter_link_dom=website.chapter_link_dom,
                        img_dom=website.img_dom,
                        use_frame=website.use_frame,
                        img_attr=website.img_attr,
                        img_script=website.img_script,
                        type=self.type
                    )
                    self.flowLayout.addWidget(card)
        # 有卡片显示列表，无卡片显示空状态
        if self.flowLayout.count() > 0:
            self.resultStack.setCurrentWidget(self.flowContainer)
        else:
            # 未搜索=没有站点；有搜索词=没搜到
            if not origin_text:
                self.emptyWidget.setIcon(FluentIcon.FOLDER)
                self.emptyWidget.setText('没有站点请添加~')
            else:
                self.emptyWidget.setIcon(FluentIcon.FOLDER)
                self.emptyWidget.setText('没有搜索到站点')
            self.resultStack.setCurrentWidget(self.emptyWidget)
        self._layoutCards()

    # 窗口宽度变化时，卡片每行 3 个、宽度自适应
    def _layoutCards(self):
        n = 3
        fm = self.flowLayout.contentsMargins()
        avail = self.flowContainer.width() - fm.left() - fm.right()
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


# 站点新增/编辑对话框
class WebsiteEditDialog(MessageBoxBase):
    # (key, 标签, 是否必填)
    FIELDS = [
        ('name', '站点名称', True),
        ('url', '站点地址', True),
        ('icon', '站点图标地址', False),
        ('comic_cover_dom', '漫画封面选择器', False),
        ('comic_name_dom', '漫画名称选择器', True),
        ('chapter_name_dom', '章节名称选择器', True),
        ('chapter_link_dom', '章节链接选择器', True),
        ('img_dom', '图片选择器（可选，留空取全部img）', False),
        ('img_attr', '图片懒加载属性（如data-src，留空自动检测）', False),
        ('use_frame', '是否用iframe加载（1是/0否，默认0）', False),
        ('img_script', 'iframe取图脚本（可选，用变量ifr，需return数组）', False),
    ]

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.edits = {}
        form = QVBoxLayout()
        form.setSpacing(4)
        for key, label, required in self.FIELDS:
            title = label + (' *' if required else '（可选）')
            form.addWidget(BodyLabel(title, self))
            edit = LineEdit(self)
            val = (data or {}).get(key, '')
            edit.setText(str(val) if val else '')
            form.addWidget(edit)
            self.edits[key] = edit
        self.viewLayout.addLayout(form)
        self.yesButton.setText('保存')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(440)

    def validate(self):
        for key, label, required in self.FIELDS:
            if required and not self.edits[key].text().strip():
                show_tip(InfoBarIcon.WARNING, '温馨提示', f'请填写{label}', self)
                return False
        return True

    def get_data(self):
        return {key: edit.text().strip() for key, edit in self.edits.items()}


# 站点卡片
class WebsiteCard(ElevatedCardWidget):
    def __init__(self, id, name, icon, url, comic_cover_dom=None, comic_name_dom=None,
                 chapter_name_dom=None, chapter_link_dom=None, img_dom=None, use_frame=None,
                 img_attr=None, img_script=None, type=1, parent=None):
        super().__init__(parent)
        self.type = type
        self.site_id = id
        self.site_data = {
            'name': name, 'icon': icon, 'url': url,
            'comic_cover_dom': comic_cover_dom or '', 'comic_name_dom': comic_name_dom or '',
            'chapter_name_dom': chapter_name_dom or '', 'chapter_link_dom': chapter_link_dom or '',
            'img_dom': img_dom or '', 'use_frame': use_frame, 'img_attr': img_attr or '',
            'img_script': img_script or ''
        }

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(150, 55)
        self.load_image(icon)

        self.titleLabel = BodyLabel(truncate_string(name, 15), self)
        self.titleLabel.setToolTip(name)

        self.editBtn = PrimaryFlatToolButton(FluentIcon.EDIT)
        self.editBtn.setFixedSize(28, 22)
        self.editBtn.setToolTip('编辑')
        self.editBtn.clicked.connect(self.editWebsite)
        self.deleteBtn = RedFlatToolButton(FluentIcon.DELETE)
        self.deleteBtn.setFixedSize(28, 22)
        self.deleteBtn.setToolTip('删除')
        self.deleteBtn.clicked.connect(self.deleteWebsite)

        # 左右两块：左侧封面+名称，右侧上编辑下删除
        self.mainLayout = QHBoxLayout(self)
        self.setFixedWidth(260)
        self.setFixedHeight(110)

        self.mainLayout.setContentsMargins(15, 10, 0, 10)
        self.mainLayout.setSpacing(12)

        # 左侧：封面 + 名称（水平居中）
        self.leftLayout = QVBoxLayout()
        self.leftLayout.setContentsMargins(0, 0, 0, 0)
        self.leftLayout.setSpacing(6)
        self.leftLayout.addWidget(self.iconWidget, 0, Qt.AlignHCenter)
        self.leftLayout.addWidget(self.titleLabel, 0, Qt.AlignHCenter)
        self.mainLayout.addLayout(self.leftLayout, 1)

        # 右侧：编辑（上）/ 删除（下）
        self.rightLayout = QVBoxLayout()
        self.rightLayout.setContentsMargins(0, 0, 0, 0)
        self.rightLayout.setSpacing(6)
        self.rightLayout.addStretch(1)
        self.rightLayout.addWidget(self.editBtn, 0, Qt.AlignHCenter)
        self.rightLayout.addWidget(self.deleteBtn, 0, Qt.AlignHCenter)
        self.rightLayout.addStretch(1)
        self.mainLayout.addLayout(self.rightLayout)

        self.iconWidget.mousePressEvent = partial(self.go_website, url, comic_cover_dom, comic_name_dom,
                                                  chapter_name_dom, chapter_link_dom, img_dom,
                                                  img_attr, img_script, use_frame)

        # 用于保存打开的新窗口实例
        self.new_windows = []

    # 编辑站点
    def editWebsite(self):
        dlg = WebsiteEditDialog(self.window(), self.site_data)
        if dlg.exec():
            with SQLiteDatabase() as db:
                db.update_data('comic_website', dlg.get_data(), {'id': self.site_id})
            self.refresh()
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '修改成功', self.window(), InfoBarPosition.TOP)

    # 删除站点
    def deleteWebsite(self):
        w = MessageBox('确认删除', '确认要删除这个站点吗？', self.window())
        if w.exec():
            with SQLiteDatabase() as db:
                db.delete_data('comic_website', {'id': self.site_id})
            self.refresh()
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '删除成功', self.window(), InfoBarPosition.TOP)

    # 刷新列表
    def refresh(self):
        current = self.parent()
        while current is not None:
            if isinstance(current, WebsitWidget):
                current.search(None)
                return
            current = current.parent()

        # 用于保存打开的新窗口实例
        self.new_windows = []

    def go_website(self, url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                   img_dom, img_attr, img_script, use_frame, event):
        try:
            window = Browser(url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                             img_dom, img_attr, img_script, use_frame)
            window.show()
            # 保存新窗口的实例
            self.new_windows.append(window)
        except Exception:
            logging.info(traceback.format_exc())

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
            self.load_fallback_image(
                ':/cmbok/images/comic_cover.png' if self.type == 1 else ':/cmbok/images/book_cover.png')  # 加载备用图片
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


# 站点窗口


class BrowserView(QWebEngineView):
    """处理 target=_blank / window.open 新窗口请求。

    不能返回 self（QtWebEngine 会闪退）：用临时子视图捕获目标 URL，
    仅同源链接（如漫画 target=_blank）转回主视图加载，跨源弹窗（广告等）直接丢弃。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._child_views = []

    def createWindow(self, _type):
        try:
            child = BrowserView()
            self._child_views.append(child)
            child.urlChanged.connect(self._adoptChildUrl)
            return child
        except Exception:
            logging.info('createWindow异常: ' + traceback.format_exc())
            return QWebEngineView()  # 兜底返回普通视图，避免 None/self 导致闪退

    def _adoptChildUrl(self, url):
        child = self.sender()
        if child is None or child not in self._child_views:
            return  # 已处理或未知来源，跳过
        self._child_views.remove(child)
        try:
            from urllib.parse import urlparse
            url_str = url.toString() if hasattr(url, 'toString') else str(url)
            u = urlparse(url_str)
            cur = urlparse(self.url().toString())
            # 仅同源链接在主视图打开；跨源（广告弹窗）丢弃
            if u.netloc and u.netloc == cur.netloc:
                self.setUrl(url)
        except Exception:
            pass
        child.deleteLater()


class Browser(QMainWindow):
    def __init__(self, url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                 img_dom, img_attr=None, img_script=None, use_frame=None):
        try:
            super().__init__()
            self.setWindowTitle("漫画站点")
            self.setGeometry(100, 100, 1280, 800)
            # 创建QWebEngineView对象
            self.url = url
            self.img_dom = img_dom or ''
            self.img_attr = (img_attr or '').strip()
            self.img_script = (img_script or '').strip()
            self.use_frame = use_frame
            self.browser = BrowserView()
            self.setCentralWidget(self.browser)

            self.checked_chapters = []
            # iframe 模式专用：独立取图窗口（规避 frame-bust），串行处理章节
            self._fetcher = None
            self._fetcher_mask = None
            self._fetch_queue = []
            self._fetch_busy = False

            # 创建悬浮按钮
            # 下载按钮
            if chapter_name_dom is not None and chapter_name_dom != 'None' and chapter_name_dom != '':
                self.chapter_button = PrimaryPushButton(FluentIcon.SEND, '获取章节')
                self.chapter_button.setFixedSize(140, 30)  # 设置按钮大小

                self.chapter_button.setCursor(QCursor(Qt.PointingHandCursor))
                self.chapter_button.clicked.connect(
                    lambda: self.get_chapters(comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                                              img_dom))

                # 设置按钮位置
                self.chapter_button.setParent(self)  # 将按钮设置为主窗口的子对象
                # 计算按钮的位置，使其位于右下角
                button_x = self.width() - self.chapter_button.width() - 20  # 距离右边10像素
                button_y = self.height() - self.chapter_button.height() - 100  # 距离底部10像素
                self.chapter_button.move(button_x, button_y)  # 移动按钮到计算的位置

            self.stateTooltip = StateToolTip('正在下载', '请耐心等待~~', self)

            tip_width = self.stateTooltip.width()
            tip_height = self.stateTooltip.height()
            window_width = self.width()
            window_height = self.height()
            x = (window_width - tip_width) // 2
            y = (window_height - tip_height) // 2
            self.stateTooltip.move(x, y)
            self.stateTooltip.hide()

            # 打开指定的网址
            self.load_page()
            # 设置窗口图标
            self.setWindowIcon(QIcon(':/cmbok/images/logo.png'))  # 替换为您的图标文件路径
            # 获取屏幕的可用尺寸
            qr = self.frameGeometry()
            cp = QDesktopWidget().availableGeometry().center()  # 获取屏幕中心
            qr.moveCenter(cp)  # 将窗口移动到中心
            self.move(qr.topLeft())  # 设置窗口的位置
        except Exception:
            logging.info(traceback.format_exc())

    def load_page(self):
        self.browser.load(QUrl(self.url))
        self.browser.loadFinished.connect(self.on_load_finished)

    def on_load_finished(self, success):
        if not success:
            # 站点无法访问：提示并停止，避免无限重试导致卡死
            show_tip(InfoBarIcon.ERROR, '温馨提示', '站点无法访问，请检查网址或网络', self,
                     InfoBarPosition.TOP)
            return
        # 把 target=_blank 的链接改为当前视图打开（与 createWindow 双保险，覆盖动态注入的链接）
        self.browser.page().runJavaScript(
            "document.querySelectorAll('a[target=_blank]').forEach(function(a){ a.target='_self'; });"
        )

    def get_chapters(self, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                     img_dom):
        cn = comic_name_dom or ''
        cl = chapter_link_dom or ''
        cnd = chapter_name_dom or ''
        ccd = comic_cover_dom or ''
        js_code = """
            var attempts = 0;
            var maxAttempts = 10;
            var cn_css = '""" + cn + """';
            var cl_css = '""" + cl + """';
            var cnd_css = '""" + cnd + """';
            var ccd_css = '""" + ccd + """';

            function tryGetChapters() {
                attempts++;
                var links = [];
                var names = [];
                var comic_name = '';
                if (cn_css) {
                    var nameEl = document.querySelector(cn_css);
                    if (nameEl) comic_name = nameEl.innerText.trim();
                }
                if (cl_css) {
                    document.querySelectorAll(cl_css).forEach(function(item) {
                        if (item.href && item.href !== '' && item.href.indexOf('javascript') === -1) {
                            links.push(item.href);
                        }
                    });
                }
                if (cnd_css) {
                    document.querySelectorAll(cnd_css).forEach(function(item) {
                        names.push((item.innerText || '').trim());
                    });
                }
                if (links.length > 0 || attempts >= maxAttempts) {
                    var chapters = [];
                    for (var i = 0; i < links.length; i++) {
                        chapters.push({'name': names[i] || ('第' + (i+1) + '话'), 'link': links[i]});
                    }
                    window.comicResult = {
                        'comic_cover': '',
                        'comic_name': comic_name,
                        'chapters': chapters
                    };
                } else {
                    setTimeout(tryGetChapters, 1500);
                }
            }
            tryGetChapters();
        """
        self.browser.page().runJavaScript(js_code, self.get_python_links)

    def get_python_links(self, result):
        # 轮询读取 window.comicResult（JS 异步设置，避免 time.sleep 阻塞 UI）
        self._pollAttempts = 0
        self._pollMax = 10
        self._pollResult()

    def _pollResult(self):
        self._pollAttempts += 1
        self.browser.page().runJavaScript("window.comicResult", self._onPollResult)

    def _onPollResult(self, result):
        if result is not None or self._pollAttempts >= self._pollMax:
            self.handle_results(result)
        else:
            QTimer.singleShot(1500, self._pollResult)

    def handle_results(self, result):
        if result is not None and len(result['chapters']) == 0:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '没有找到章节信息，o(╥﹏╥)o', self,
                         InfoBarPosition.TOP)
        else:
            Flyout.make(CustomFlyoutView(result, self), self.chapter_button, self, aniType=FlyoutAnimationType.PULL_UP)

    def toggle_mask(self, mask_visible):
        js_code = """
            if (!""" + str(mask_visible) + """) {{
                const overlay = document.createElement('div');
                overlay.id = 'overlay';
                overlay.style.position = 'fixed';
                overlay.style.top = '0';
                overlay.style.left = '0';
                overlay.style.width = '100%';
                overlay.style.height = '100%';
                overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.5)'; // 半透明黑色
                overlay.style.zIndex = '9999'; // 确保在最上层
                document.body.appendChild(overlay);
            }} else {{
                const overlay = document.getElementById('overlay');
                overlay.remove();
            }}
        """
        self.browser.page().runJavaScript(js_code)

    def downloadComic(self, result, checked_chapters):
        # 是否合并成卷
        isMergeChapte = cfg.get(cfg.isMergeChapte)
        if isMergeChapte:
            # 清空漫画目录
            download_folder = cfg.get(cfg.downloadFolder)
            path = f"{download_folder}/{result['comic_name']}"
            del_folder(path)

        self.stateTooltip.setContent('请耐心等待~~')
        with SQLiteDatabase() as db:
            db.delete_data('website_download_record', {'comic_name': result['comic_name']})
            db.insert_data('website_download_record',
                           {'comic_name': result['comic_name'], 'chapter_num': len(checked_chapters),
                            'downloaded_num': 0, 'downloading_num': 0, 'is_update': 0,
                            'start_time': get_current_time()})

        self.checked_chapters = checked_chapters
        # 按复选框顺序倒序后依次下载合并（站点章节多为倒序排列，反转即章节阅读顺序）
        self.checked_chapters.reverse()
        for _i, _c in enumerate(self.checked_chapters):
            _c['_order'] = _i + 1
        self.launch_iframes(result['comic_name'])

    def launch_iframes(self, comic_name):
        # 获取最大线程配置
        downloadThreadNum = cfg.get(cfg.downloadThreadNum)

        sqlite_util = SQLiteDatabase()
        while True:
            record = sqlite_util.query_first_data('website_download_record', {'comic_name': comic_name})
            if record.downloading_num < downloadThreadNum:
                # 从待处理列表中取出一个 URL
                num = len(self.checked_chapters)
                logging.info('num:' + str(num))
                if num > 0:
                    chapter = self.checked_chapters.pop(0)
                    # 用预分配的章节顺序号作前缀（升序），natsort 后即章节阅读顺序
                    order = chapter.pop('_order', num)
                    chapter['name'] = str(order) + '_' + chapter['name']
                    self.add_iframe(comic_name, chapter)
                else:
                    break
            else:
                break
        sqlite_util.close()

    def add_iframe(self, comic_name, chapter):
        logging.info(f'[站点下载] 开始加载章节页: {chapter["name"]} | {chapter["link"]} | use_frame={bool(self.use_frame)}')
        sqlite_util = SQLiteDatabase()
        while True:
            record = sqlite_util.query_first_data('website_download_record', {'comic_name': comic_name})
            if record.is_update == 0:
                sqlite_util.update_data('website_download_record',
                                        {'is_update': 1, 'downloading_num': record.downloading_num + 1},
                                        {'comic_name': comic_name})
                sqlite_util.update_data('website_download_record',
                                        {'is_update': 0},
                                        {'comic_name': comic_name})
                break
        sqlite_util.close()

        # 按是否 iframe 加载分两条路径（对应油猴脚本 getImage 的 useFrame 分支）
        if self.use_frame:
            self._add_iframe_frame(comic_name, chapter)
        else:
            self._fetch_chapter_direct(comic_name, chapter)

    def _fetch_chapter_direct(self, comic_name, chapter):
        # 直连模式（use_frame=0）：requests 请求章节页 HTML + BeautifulSoup 按 img_dom 提取图片
        self.fetchThread = WebsiteChapterFetchThread(comic_name, chapter['name'], chapter['link'],
                                                       self.img_dom, self.img_attr)
        self.fetchThread.success.connect(self._on_direct_fetched)
        self.fetchThread.start()

    def _add_iframe_frame(self, comic_name, chapter):
        # iframe 模式（use_frame=1）：用独立 QWebEngineView 窗口加载章节页
        # 独立窗口是顶级窗口 top===self，frame-bust 的 top!==self 判断不成立，不会跳转主页面
        import json as _json
        # 构造取图函数体：有 img_script 用之（变量 ifr 可用，需 return 数组），否则回退 DOM 提取（带滚动触发懒加载）
        if self.img_script:
            body = self.img_script
        else:
            img_dom = self.img_dom or 'img'
            if self.img_attr:
                map_expr = "im.getAttribute(" + _json.dumps(self.img_attr) + ") || im.src"
            else:
                map_expr = ("im.dataset.src || im.dataset.original || im.dataset.url "
                            "|| im.dataset.lazySrc || im.dataset.originalSrc || im.src")
            body = (
                "var doc = ifr.contentDocument; "
                "if (doc && doc.defaultView) { "
                "  var lastH = 0, stable = 0, attempts = 0; "
                "  while (attempts < 25) { "
                "    attempts++; var h = doc.body ? doc.body.scrollHeight : 0; "
                "    if (h === lastH) { stable++; if (stable >= 2) break; } else { stable = 0; lastH = h; } "
                "    doc.defaultView.scrollBy(0, 1000); "
                "    await new Promise(function(r){ setTimeout(r, 300); }); "
                "  } "
                "  doc.defaultView.scrollTo(0, 0); "
                "} "
                "var nodes = doc ? doc.querySelectorAll(" + _json.dumps(img_dom) + ") : []; "
                "return Array.from(nodes).map(function(im){ return " + map_expr + "; })"
                ".filter(function(s){ return s && s.indexOf('logo')===-1 && s.indexOf('load.gif')===-1 "
                "&& s.indexOf('blank')===-1 && s.indexOf('data:image')===-1 && s.indexOf('placeholder')===-1; });"
            )
        meta = _json.dumps({'comic_name': comic_name, 'chapter_name': chapter['name'], 'chapter_link': chapter['link']})
        # 入队，串行处理（一个取图窗口依次加载各章节，符合"依次"）
        self._fetch_queue.append({'link': chapter['link'], 'body': body, 'meta': meta,
                                  'comic_name': comic_name, 'chapter_name': chapter['name']})
        if not self._fetch_busy:
            self._process_fetch_queue()

    def _process_fetch_queue(self):
        if not self._fetch_queue:
            self._fetch_busy = False
            self._close_fetcher()  # 所有章节取图完成（或失败），自动关闭取图窗口
            return
        self._fetch_busy = True
        item = self._fetch_queue.pop(0)
        if self._fetcher is None:
            self._fetcher = QWebEngineView(self)
            self._fetcher.setWindowTitle('章节取图（自动关闭，请勿关闭）')
            self._fetcher.resize(900, 700)
            # 去掉关闭按钮，禁止用户交互（仅标题栏+最小化）
            self._fetcher.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint)
            self._fetcher.loadFinished.connect(self._on_fetcher_loaded)
            # 防抖定时器：章节页若有客户端重定向(loadFinished 多次触发)，等稳定后再提取
            self._fetch_timer = QTimer(self)
            self._fetch_timer.setSingleShot(True)
            self._fetch_timer.timeout.connect(self._extract_from_fetcher)
            try:
                self._fetcher.page().setBackgroundColor(QColor('#1a1a1a'))
            except Exception:
                pass
            self._fetcher.show()
            # 蒙版：独立半透明置顶窗口，覆盖取图窗口阻止操作（不依赖页面JS，从打开到关闭全程在位）
            self._fetcher_mask = QWidget(self._fetcher, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self._fetcher_mask.setStyleSheet('background: rgba(26,26,26,0.85);')
            _ml = QVBoxLayout(self._fetcher_mask)
            _ml.setContentsMargins(0, 0, 0, 0)
            _lbl = QLabel('正在取图，请勿操作...')
            _lbl.setStyleSheet('color:#ffffff;font-size:22px;font-family:sans-serif;')
            _lbl.setAlignment(Qt.AlignCenter)
            _ml.addWidget(_lbl)
            self._fetcher_mask.show()
            self._align_fetcher_mask()
            # 跟随取图窗口移动/缩放
            self._fetcher.installEventFilter(self)
        self._fetcher._cur = item
        logging.info(f'[站点下载] 取图窗口加载: {item["chapter_name"]} | {item["link"]}')
        try:
            self._fetcher.load(QUrl(item['link']))
        except Exception:
            logging.info('[站点下载] 取图窗口加载异常: ' + traceback.format_exc())
            self._on_frame_images({'comic_name': item['comic_name'], 'chapter_name': item['chapter_name'],
                                   'imgs': [], 'note': '取图窗口加载异常'})
            self._process_fetch_queue()

    def eventFilter(self, obj, event):
        # 取图窗口移动/缩放时，蒙版窗口跟随对齐
        if obj == self._fetcher and event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show):
            self._align_fetcher_mask()
        return super().eventFilter(obj, event)

    def _align_fetcher_mask(self):
        """蒙版窗口对齐覆盖取图窗口的客户区"""
        if self._fetcher is not None and getattr(self, '_fetcher_mask', None) is not None:
            try:
                self._fetcher_mask.setGeometry(self._fetcher.geometry())
                self._fetcher_mask.raise_()
                self._fetcher_mask.show()
            except Exception:
                pass

    def _close_fetcher(self):
        """取图完成/失败时关闭并清理取图窗口"""
        if self._fetch_timer is not None:
            try:
                self._fetch_timer.stop()
            except Exception:
                pass
        if self._fetcher is not None:
            try:
                self._fetcher.removeEventFilter(self)
            except Exception:
                pass
            try:
                self._fetcher.loadFinished.disconnect()
            except Exception:
                pass
            try:
                self._fetcher.close()
                self._fetcher.deleteLater()
            except Exception:
                pass
            self._fetcher = None
            logging.info('[站点下载] 取图窗口已关闭')
        # 关闭蒙版窗口
        if getattr(self, '_fetcher_mask', None) is not None:
            try:
                self._fetcher_mask.close()
                self._fetcher_mask.deleteLater()
            except Exception:
                pass
            self._fetcher_mask = None

    def _on_fetcher_loaded(self, ok):
        view = self._fetcher
        if view is None:
            return
        # 跳过初始蒙版页（about:blank 等非 http），只处理章节页
        url = view.url().toString()
        if not url.startswith('http'):
            return
        item = getattr(view, '_cur', None)
        if not item:
            return
        if not ok:
            logging.info(f'[站点下载] 取图窗口加载失败: {item["chapter_name"]}')
            self._on_frame_images({'comic_name': item['comic_name'], 'chapter_name': item['chapter_name'],
                                   'imgs': [], 'note': '取图窗口加载失败'})
            self._process_fetch_queue()
            return
        # 蒙版由独立置顶窗口覆盖（_fetcher_mask），这里只做防抖提取
        # 防抖：每次 loadFinished 都重启定时器，等页面稳定(无重定向)后再提取
        self._fetch_timer.start(1500)

    def _extract_from_fetcher(self):
        view = self._fetcher
        if view is None:
            return
        item = getattr(view, '_cur', None)
        if not item:
            return
        body = item['body']
        meta = item['meta']
        logging.info(f'[站点下载] 开始提取图片: {item["chapter_name"]}')
        # runJavaScript 不等待 async Promise，故 JS 把结果写到 window._fetchResult，Python 轮询读取
        js_code = """
        (async function(){
            var META = """ + meta + """;
            window._fetchResult = null;
            var ifr = { contentWindow: window, contentDocument: document };
            var note = '';
            var imgs = [];
            try {
                var fn = (async function(ifr){
                    """ + body + """
                });
                var val = await fn(ifr);
                imgs = Array.isArray(val) ? val : (val ? [val] : []);
            } catch(e) { note = 'JS异常:' + String(e); }
            if (imgs.length === 0) {
                try {
                    note += ' | 标题=' + document.title + ' body长度=' + (document.body ? document.body.innerHTML.length : 0)
                        + ' img数=' + document.querySelectorAll('img').length + ' URL=' + window.location.href;
                    if (window.__NUXT__) note += ' | 含__NUXT__';
                    if (window.__NEXT_DATA__) note += ' | 含__NEXT_DATA__';
                } catch(e2) {}
            }
            window._fetchResult = JSON.stringify({ 'comic_name': META.comic_name, 'chapter_name': META.chapter_name, 'imgs': imgs, 'note': note, 'chapter_link': META.chapter_link });
        })();
        """
        view.page().runJavaScript(js_code)
        self._fetch_poll = 0
        self._poll_fetch_result()

    def _poll_fetch_result(self):
        view = self._fetcher
        if view is None:
            return
        self._fetch_poll += 1
        view.page().runJavaScript('window._fetchResult', self._on_poll_fetch_result)

    def _on_poll_fetch_result(self, result):
        if result:
            # 读到结果，清空全局，解析
            self._fetcher.page().runJavaScript('window._fetchResult = null')
            import json as _json
            try:
                data = _json.loads(result) if isinstance(result, str) else result
            except Exception:
                logging.info(f'[站点下载] 提取回调JSON解析失败: {str(result)[:200]}')
                data = None
            logging.info(f'[站点下载] 提取回调原始: {str(data)[:200]}')
            self._on_frame_images(data)
            self._process_fetch_queue()
        elif self._fetch_poll < 60:  # 最多轮询 30 秒（60 * 500ms）
            QTimer.singleShot(500, self._poll_fetch_result)
        else:
            logging.info('[站点下载] 提取超时(30s)未拿到结果')
            self._on_frame_images(None)
            self._process_fetch_queue()


    def _on_direct_fetched(self, comic_name, chapter_name, imgs, referer=''):
        self._start_chapter_download(comic_name, chapter_name, imgs, referer)

    def _on_frame_images(self, result):
        if not result or not isinstance(result, dict):
            logging.info('[站点下载] iframe取图回调返回空结果')
            return
        note = result.get('note') or ''
        if note:
            logging.info(f'[站点下载] iframe取图诊断: {note}')
        self._start_chapter_download(result.get('comic_name', ''), result.get('chapter_name', ''),
                                     result.get('imgs', []), result.get('chapter_link', ''))

    def _start_chapter_download(self, comic_name, chapter_name, imgs, referer=''):
        img_count = len(imgs or [])
        logging.info(f'[站点下载] 提取到 {img_count} 张图片 | 章节: {chapter_name}')
        if img_count > 0:
            self.comicWebsiteChapterImages = ComicWebsiteChapterImages(comic_name=comic_name,
                                                                       chapter_name=chapter_name,
                                                                       chapter_images=imgs,
                                                                       referer=referer)
            self.comicWebsiteChapterImages.success.connect(self.downloadComicStatus)
            self.comicWebsiteChapterImages.start()
        else:
            # 未提取到图片：记日志并推进进度，不再无限重试避免卡死
            logging.info(f'[站点下载] 未提取到图片，跳过该章节: {chapter_name}')
            self.downloadComicStatus(comic_name)

    def downloadComicStatus(self, comic_name):
        logging.info(f'[站点下载] 章节下载完成: {comic_name}')
        sqlite_util = SQLiteDatabase()
        record = sqlite_util.query_first_data('website_download_record', {'comic_name': comic_name})
        while True:
            if record.is_update == 0:
                sqlite_util.update_data('website_download_record',
                                        {'is_update': 1, 'downloading_num': record.downloading_num - 1,
                                         'downloaded_num': record.downloaded_num + 1},
                                        {'comic_name': comic_name})
                sqlite_util.update_data('website_download_record',
                                        {'is_update': 0},
                                        {'comic_name': comic_name})
                break

        # 最后生成epub
        record = sqlite_util.query_first_data('website_download_record', {'comic_name': comic_name})

        sqlite_util.close()
        progress = int(record.downloaded_num / record.chapter_num * 100) if record.chapter_num else 0
        logging.info(f'[站点下载] 进度: {record.downloaded_num}/{record.chapter_num} ({progress}%)')
        if record.chapter_num == record.downloaded_num:
            logging.info(f'[站点下载] 全部章节下载完成，开始合并epub: {comic_name}')
            # 下载完成合并epub
            # 先根据配置合并卷目录
            isMergeChapte = cfg.get(cfg.isMergeChapte)
            download_folder = cfg.get(cfg.downloadFolder)
            path = f"{download_folder}/{comic_name}"
            if isMergeChapte:
                mergeChapterNum = cfg.get(cfg.mergeChapterNum)

                directories = get_directories(path)
                for i in range(0, len(directories), mergeChapterNum):
                    current_directories = directories[i:i + mergeChapterNum]
                    # 创建一个新的目标目录
                    target_directory = os.path.join(path, f"第{i // mergeChapterNum + 1}卷")
                    os.makedirs(target_directory, exist_ok=True)
                    # 移动文件并删除原目录
                    move_files(path, current_directories, target_directory)

            # 生成epub
            self.epubThread = EpubThread(path=path,
                                         comic_name=comic_name)
            self.epubThread.success.connect(lambda p=path: self.download_finish(p))
            self.epubThread.start()
        else:
            self.stateTooltip.setContent(
                '已完成' + str(progress) + '%,请耐心等待~~')
            self.launch_iframes(comic_name)

    def download_finish(self, path):
        logging.info('[站点下载] epub合并完成')
        self.stateTooltip.hide()
        self.toggle_mask(1)
        self.chapter_button.setDisabled(False)
        # 下载完成提示：是否打开下载目录
        box = MessageBox('下载完成', '漫画下载完成，是否打开下载目录？', self)
        if box.exec():
            target = path if os.path.isdir(path) else cfg.get(cfg.downloadFolder)
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))


class CustomFlyoutView(FlyoutViewBase):

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.parent = parent
        # 创建主布局
        self.layout = QVBoxLayout()

        # 创建滚动区域
        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Vertical)
        self.scroll_area.setWidgetResizable(True)  # 使子部件在滚动区域内调整大小
        self.scroll_area.setFixedHeight(350)
        self.scroll_area.setFixedWidth(600)
        # 设置滚动区域的样式表，使背景透明
        self.scroll_area.setStyleSheet("QFrame { background: transparent; border: none; }")  # 设置透明背景和无边框

        # 创建一个框架以容纳其他控件
        self.scroll_content = QFrame()
        self.scroll_layout = QVBoxLayout(self.scroll_content)  # 使用垂直布局

        # 添加多个标签作为示例内容
        self.flowlayout = FlowLayout()
        # 获取目录
        # 存储复选框的列表
        self.checkboxes = []
        if result is not None:
            # 全选复选框
            select_all_checkbox = CheckBox("全选")
            select_all_checkbox.stateChanged.connect(self.toggle_all)  # 连接信号
            self.flowlayout.addWidget(select_all_checkbox)
            for obj in result['chapters']:
                checkBox = CheckBox(obj['name'], self)
                self.checkboxes.append(checkBox)  # 将复选框添加到列表中
                self.flowlayout.addWidget(checkBox)

        self.scroll_layout.addLayout(self.flowlayout)

        # 将框架设置为滚动区域的中心小部件
        self.scroll_area.setWidget(self.scroll_content)

        # 将滚动区域添加到主布局
        self.layout.addWidget(self.scroll_area)

        self.label = BodyLabel("")
        self.label.setTextColor(QColor(228, 101, 71), QColor(228, 101, 71))  # 浅色主题，深色主题
        self.layout.addWidget(self.label)

        # 创建横向布局
        self.hbox_layout = QHBoxLayout()
        # 创建按钮并添加到横向布局
        # 下载按钮
        self.download_button = PrimaryPushButton(FluentIcon.DOWNLOAD, '下载')
        self.download_button.setFixedWidth(140)
        self.download_button.clicked.connect(lambda: self.downloadComic(result))
        self.hbox_layout.addWidget(self.download_button)

        # 将横向布局添加到垂直布局
        self.layout.addLayout(self.hbox_layout)

        # 设置主布局
        self.setLayout(self.layout)

    def toggle_all(self, state):
        # 根据全选复选框的状态来勾选或取消所有复选框
        for checkbox in self.checkboxes:
            checkbox.setChecked(state == 2)  # 2表示选中状态

    def downloadComic(self, result):
        # 获取选中复选框的状态
        checked_items = [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]

        if len(checked_items) > 0:
            self.parent.toggle_mask(0)
            self.parent.chapter_button.setDisabled(True)
            self.download_button.setDisabled(True)

            self.parent.stateTooltip.show()

            checked_chapters = []
            if checked_items:
                checked_chapters = [obj for obj in result['chapters'] if obj['name'] in checked_items]

            self.parent.downloadComic(result, checked_chapters)
