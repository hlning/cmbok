# coding:utf-8
import datetime
import logging
import math
import traceback

from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt5.QtGui import QPixmap, QMovie, QPainter, QColor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QStackedWidget
from qfluentwidgets import FlowLayout, CardWidget, ElevatedCardWidget, SearchLineEdit, StateToolTip, \
    FluentIcon, TransparentToolButton, BodyLabel, InfoBarPosition, InfoBarIcon, \
    CaptionLabel, MessageBoxBase, ComboBox, PrimaryPushButton, PushButton, MessageBox, isDarkTheme

from common.config import cfg
from common.const import language_item
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import BookSearch, Book, BookDownload
from utils.base_utils import truncate_string, get_current_time
from view.components.folder_tree import TreeFrame
from view.components.auto_flow_layout import AutoFlowLayout
from view.components.info_bar_tip import show_tip
from view.components.pagination_bar import PaginationBar
from view.components.empty_state_widget import EmptyStateWidget


class ElideLabel(QLabel):
    """单行文字，超出宽度自动省略（ElideRight），不换行；保证卡片高度统一"""
    def __init__(self, text='', parent=None, light_color=None, dark_color=None):
        super().__init__(parent)
        self._full_text = text or ''
        self._light = light_color
        self._dark = dark_color
        self.setWordWrap(False)
        self.setText(text)

    def setFullText(self, text):
        self._full_text = text or ''
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setFont(self.font())
        if self._light or self._dark:
            painter.setPen(QColor(self._dark if isDarkTheme() else self._light))
        else:
            painter.setPen(self.palette().windowText().color())
        fm = painter.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, elided)


# 搜索区域
class BookSearchCardView(QWidget):
    """ Sample card view """
    success = pyqtSignal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent=parent)

        self.book_list = []
        self.book_name = ''
        self.is_search = True
        self.stateTooltip = None

        self.vBoxLayout = QVBoxLayout(self)

        self.titleLabel = QLabel(title, self)
        self.vBoxLayout.addWidget(self.titleLabel)

        # 搜索输入框
        self.hBoxLayout1 = QHBoxLayout()
        self.hBoxLayout1.setSpacing(6)
        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setPlaceholderText('请输入图书名')
        self.lineEdit.searchSignal.connect(lambda text: self.searchBook(text, 0))
        self.lineEdit.returnPressed.connect(self.enter)

        # 重置按钮
        self.resetBtn = PrimaryPushButton(FluentIcon.SYNC, '重置')
        self.resetBtn.clicked.connect(self.reset)

        self.hBoxLayout1.addStretch()
        self.hBoxLayout1.addWidget(self.lineEdit)
        self.hBoxLayout1.addWidget(self.resetBtn)
        self.hBoxLayout1.addStretch()

        self.vBoxLayout.addLayout(self.hBoxLayout1)

        # 精确搜索
        self.hBoxLayout2 = QHBoxLayout()
        # 年份数组
        # 获取当前年份
        current_year = datetime.datetime.now().year
        # 从1800年到当前年份，添加到数组中
        # 生成从 1800 到当前年份的列表
        years = list(range(1800, current_year + 1))
        # 倒序添加到新数组
        reversed_years = [str(year) for year in reversed(years)]

        # 起始年份
        self.startDateComboBox = ComboBox()
        # 添加选项
        items = ['起始年份'] + reversed_years
        self.startDateComboBox.addItems(items)

        # 截止年份
        self.endDateComboBox = ComboBox()
        # 添加选项
        items = ['截止年份'] + reversed_years
        self.endDateComboBox.addItems(items)

        # 语言
        self.languageComboBox = ComboBox()

        # 添加选项
        for key, value in language_item.items():
            self.languageComboBox.addItem(value, userData=key)

        # 格式
        self.extensionsComboBox = ComboBox()
        # 添加选项
        items = ['格式', 'EPUB', 'AZW', 'AZW3', 'MOBI', 'PDF', 'TXT', 'CBZ', 'DJV', 'DJVU', 'FB2', 'LIT', 'RTF']
        self.extensionsComboBox.addItems(items)

        # 下拉列表最多显示 20 项，避免年份过多导致下拉超出软件高度
        for box in (self.startDateComboBox, self.endDateComboBox, self.languageComboBox, self.extensionsComboBox):
            box.setMaxVisibleItems(20)

        self.hBoxLayout2.addStretch()
        self.hBoxLayout2.addWidget(self.startDateComboBox)
        self.hBoxLayout2.addWidget(self.endDateComboBox)
        self.hBoxLayout2.addWidget(self.languageComboBox)
        self.hBoxLayout2.addWidget(self.extensionsComboBox)
        self.hBoxLayout2.addStretch()
        self.vBoxLayout.addLayout(self.hBoxLayout2)

        # 分页栏
        self._pageSize = 10
        self._total = 0
        self._pendingPage = 0
        self.pager = PaginationBar(parent=self)
        self.pager.pageChanged.connect(self.getBooks)
        self.pager.pageSizeChanged.connect(self._onPageSizeChanged)
        self.pager.setVisible(False)

        # 搜索结果滚动区（搜索区固定顶部、分页固定底部，仅结果区滚动）
        self.resultScrollArea = QScrollArea(self)
        self.resultScrollArea.setWidgetResizable(True)
        self.resultScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resultScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.resultScrollArea.setFrameShape(QFrame.NoFrame)
        # 透明背景 + 细滚动条
        self.resultScrollArea.setStyleSheet(
            'QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget '
            '{ background: transparent; border: none; }'
            'QScrollBar:vertical { background: transparent; width: 3px; margin: 0; }'
            'QScrollBar::handle:vertical { background: rgba(128, 128, 128, 120); '
            'border-radius: 4px; min-height: 30px; }'
            'QScrollBar::handle:vertical:hover { background: rgba(128, 128, 128, 200); }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
            'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }')
        self.resultScrollWidget = QWidget(self.resultScrollArea)
        self.resultScrollWidget.setStyleSheet('background: transparent;')
        self.flowLayout = AutoFlowLayout(self.resultScrollWidget)
        self.resultScrollArea.setWidget(self.resultScrollWidget)

        # 结果区：搜索结果 / 空状态占位（初始提示输入关键字搜索）
        self.resultStack = QStackedWidget(self)
        self.resultStack.addWidget(self.resultScrollArea)  # 页0：搜索结果
        self.emptyWidget = EmptyStateWidget(FluentIcon.SEARCH, '输入图书关键字进行搜索~', self)
        self.resultStack.addWidget(self.emptyWidget)  # 页1：空状态
        self.resultStack.setCurrentWidget(self.emptyWidget)

        self.vBoxLayout.setContentsMargins(15, 0, 36, 0)
        self.vBoxLayout.setSpacing(10)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setHorizontalSpacing(12)
        self.flowLayout.setVerticalSpacing(12)
        self.vBoxLayout.addWidget(self.resultStack, 1)
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignRight)

        self.titleLabel.setObjectName('viewTitleLabel')
        StyleSheet.SAMPLE_CARD.apply(self)

    # 重置搜索条件
    def reset(self):
        self.lineEdit.setText('')
        self.startDateComboBox.setCurrentIndex(0)
        self.endDateComboBox.setCurrentIndex(0)
        self.languageComboBox.setCurrentIndex(0)
        self.extensionsComboBox.setCurrentIndex(0)

    # 回车搜索
    def enter(self):
        self.searchBook(self.lineEdit.text(), 0)

    # 搜索图书
    def searchBook(self, text, index, is_search=True):
        if text is not None and text != '' and self.stateTooltip is None:
            self.book_name = text
            self.is_search = is_search
            # 内置账号模式不需登录；自有账号模式需登录
            if not cfg.get(cfg.use_zlibrary_builtin_account) and not self._is_logged_in():
                show_tip(InfoBarIcon.WARNING, '温馨提示', '请先登录，或者到设置中开启内置账号', self, InfoBarPosition.TOP)
                return

            self.stateTooltip = StateToolTip('正在加载', '请耐心等待~~', self)
            sh = self.stateTooltip.sizeHint()
            # 居中于所在界面的可视区中心（view 宽度中心），而非卡片自身宽度
            view = self.parent()
            cx = view.width() // 2 - self.x() - 125
            self.stateTooltip.move(max(0, cx - sh.width() // 2), 5)
            self.stateTooltip.show()

            # 获取精确搜索条件
            # 起始年份
            start_date = self.startDateComboBox.text()
            # 截止年份
            end_date = self.endDateComboBox.text()
            # 语言
            language = self.languageComboBox.itemData(self.languageComboBox.currentIndex())
            # 格式
            extensions = self.extensionsComboBox.text()

            book = Book(book_name=text, start_date=start_date, end_date=end_date, language=language,
                        extensions=extensions)
            self.bookSearch = BookSearch(book=book, index=index + 1)
            self.bookSearch.success.connect(self.loadBookCard)
            self.bookSearch.start()
        elif text is not None and text == '':
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请输入图书名称进行搜索o(￣▽￣)ｄ', self)

    # 是否已登录 z-library
    def _is_logged_in(self):
        return bool(cfg.get(cfg.zlibrary_remix_userid)) and bool(cfg.get(cfg.zlibrary_remix_userkey))

    # 加载图书搜索结果区域
    def loadBookCard(self, status, results):
        try:
            self.stateTooltip.setTitle('加载失败')
            if status == 'fail':
                self.stateTooltip.setContent('网络异常，o(╥﹏╥)o')
            elif status == 'timeout':
                self.stateTooltip.setContent('请求超时了，(。・＿・。)ﾉI’m sorry~')
            elif status == 'error':
                self.stateTooltip.setContent('系统异常，(。・＿・。)ﾉI’m sorry~')
            elif status == 'no_login':
                cfg.set(cfg.zlibrary_remix_userid, '')
                cfg.set(cfg.zlibrary_remix_userkey, '')
                self.stateTooltip.setContent('登录已失效，请重新搜索并登录')
            elif status == 'no_account':
                self.stateTooltip.setContent('没有可用的内置账号，o(╥﹏╥)o')
            elif status == 'no_num':
                self.stateTooltip.setContent('今日内置账号下载已达上限（5本），明天再试吧o(╥﹏╥)o')
            else:
                self.stateTooltip.setTitle('加载完成')

                if results is not None:
                    pagination = results['pagination']
                    books = results['books']
                    if len(books) > 0:
                        self.resultStack.setCurrentWidget(self.resultScrollArea)
                        self.pager.setVisible(True)
                        if self.is_search:
                            self.book_list = books
                            total = pagination['total_items']
                            self._total = total
                            self.pager.setPage(0, math.ceil(total / self._pageSize), total)
                            self.getBooks(0)
                            self.stateTooltip.setContent('加载完成啦，(*^▽^*)')
                        else:
                            self.book_list.extend(books)
                            self.getBooks(self._pendingPage)
                    else:
                        self.pager.setVisible(False)
                        self.emptyWidget.setIcon(FluentIcon.FOLDER)
                        self.emptyWidget.setText('一本图书都没有搜索到，o(╥﹏╥)o')
                        self.resultStack.setCurrentWidget(self.emptyWidget)
                        self.stateTooltip.setContent('一本图书都没有搜索到，o(╥﹏╥)o')
        except Exception:
            self.stateTooltip.setContent('系统异常，o(╥﹏╥)o')
            logging.info(traceback.format_exc())
            logging.info('渲染图书查询结果失败')
        finally:
            self.stateTooltip.setState(True)
            self.stateTooltip = None

    # 从缓存中直接获取图书
    def getBooks(self, index):
        book_size = len(self.book_list)
        if book_size > 0:
            book_page = math.ceil(book_size / self._pageSize)
            # 查询新的图书
            if index + 1 > book_page:
                self._pendingPage = index
                self.searchBook(self.book_name, int(book_size / 60), False)
            else:
                # 清空流布局中的所有控件
                self.flowLayout.takeAllWidgets()
                for book in self.book_list[index * self._pageSize:(index + 1) * self._pageSize]:
                    self.addSampleCard(book)
                # 更新分页栏当前页
                self.pager.setPage(index, math.ceil(self._total / self._pageSize), self._total)
                # 卡片宽度刷新（首次渲染时宽度可能未就绪，确保每行一条）
                QTimer.singleShot(0, self.refreshCardWidth)

    # 每页条数变化
    def _onPageSizeChanged(self, size):
        self._pageSize = size
        if self.book_list:
            self.pager.setPage(0, math.ceil(self._total / self._pageSize), self._total)
            self.getBooks(0)

    def _cardWidth(self):
        # 卡片宽度=结果区宽，每行只显示一条，随窗口自适应
        lm = self.vBoxLayout.contentsMargins()
        vw = self.width() - lm.left() - lm.right()
        return max(200, vw - 5)

    def addSampleCard(self, book):
        """ add sample card """
        card = BookCard(book, self)
        card.setFixedWidth(self._cardWidth())
        self.flowLayout.addWidget(card)

    def refreshCardWidth(self):
        # 窗口宽度变化时，已存在的搜索结果卡片跟随结果区宽度自适应（每行一条）
        if self.flowLayout.count() > 0:
            w = self._cardWidth()
            for i in range(self.flowLayout.count()):
                item = self.flowLayout.itemAt(i)
                if item and item.widget():
                    item.widget().setFixedWidth(w)
            self.flowLayout.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 延迟到布局完成后再重排，确保取到最新结果区宽度
        QTimer.singleShot(0, self.refreshCardWidth)


# 图书卡片
class BookCard(ElevatedCardWidget):
    def __init__(self, book, parent=None):
        super().__init__(parent=parent)
        # 图书信息
        self.cover = book['cover']
        self.name = book['title']
        self.author = book['author']
        self.book_id = book['id']
        self.book_hash = book['hash']
        self.year = book['year']
        self.language = book['language']
        self.extension = book['extension']
        self.filesizeString = book['filesizeString']

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(40, 50)
        self.load_image(self.cover)

        self.nameLabel = ElideLabel(self.name, self, light_color='#000000', dark_color='#ffffff')
        self.nameLabel.setStyleSheet("font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';")
        self.nameLabel.setToolTip(self.name)
        self.authorLabel = ElideLabel(self.author, self, light_color='#606060', dark_color='#d2d2d2')
        self.authorLabel.setStyleSheet("font: 12px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';")
        self.authorLabel.setToolTip(self.author)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(4)
        self.vBoxLayout.addWidget(self.nameLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.authorLabel, 0, Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)

        # 按钮区域
        self.vBtnBoxLayout = QHBoxLayout()
        self.vBtnBoxLayout.addStretch()
        self.vBtnBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBtnBoxLayout.setAlignment(Qt.AlignRight)
        # 文件大小
        self.fileSizeLabel = CaptionLabel(
            f'年份：{self.year} / 语言：{self.language} / 文件：{self.extension} {self.filesizeString}', self)
        self.fileSizeLabel.setTextColor("#606060", "#d2d2d2")
        self.vBtnBoxLayout.addWidget(self.fileSizeLabel, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 收藏图书
        # 是否收藏
        self.is_collect = False
        sqlite_util = SQLiteDatabase()
        records = sqlite_util.query_data('cmbok_collection_record', {'key': self.book_id, 'type': 2})
        if len(records) > 0:
            self.is_collect = True
            collect_icon = MyFluentIcon.HAVE_COLLECT
        else:
            collect_icon = MyFluentIcon.COLLECT
        self.collectBtn = TransparentToolButton(collect_icon)
        self.collectBtn.setFixedWidth(30)
        self.collectBtn.clicked.connect(self.collectBook)
        self.vBtnBoxLayout.addWidget(self.collectBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 下载图书
        self.downloadBtn = TransparentToolButton(FluentIcon.DOWNLOAD)
        self.downloadBtn.setFixedWidth(30)
        self.downloadBtn.clicked.connect(lambda: self.downloadBook(book))
        self.vBtnBoxLayout.addWidget(self.downloadBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 按钮区域

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addLayout(self.vBtnBoxLayout)

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
            self.load_fallback_image('resource/images/book_cover.png')  # 加载备用图片
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

    # 下载图书
    def downloadBook(self, book):
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
        self.bookDownload = BookDownload(book=book)
        self.bookDownload.success.connect(self.downloadBookStatus)
        self.bookDownload.start()

    def downloadBookStatus(self, status):
        current_widget = self.parent()
        while current_widget is not None:
            if isinstance(current_widget, BookSearchCardView):
                current_widget.success.emit(status)
                return
            current_widget = current_widget.parent()  # 继续向上查找

    # 收藏图书
    def collectBook(self):
        sqlite_util = SQLiteDatabase()
        try:
            if not self.is_collect:
                # 收藏
                w = TreeMessageBox(self.window())
                if w.exec():
                    # 遍历树节点获取选中的节点
                    selected_items = w.treeFrame.tree.selectedItems()
                    if selected_items:
                        # 如果有选中的项，获取第一个选中项并输出名称
                        selected_item = selected_items[0]
                        folder_name = selected_item.text(0)  # 获取第一列的文本
                        # 通过名称查询文件夹id
                        folder = sqlite_util.query_data('comic_collection_folder', {'name': folder_name, 'type': 2})
                        folder_id = 0 if folder_name == '首页' else folder[0].id

                        sqlite_util.insert_data('cmbok_collection_record', {'cover': self.cover,
                                                                            'name': self.name, 'author': self.author,
                                                                            'key': self.book_id,
                                                                            'book_hash': self.book_hash,
                                                                            'book_extension': self.extension, 'type': 2,
                                                                            'collection_time': get_current_time(),
                                                                            'folder_id': folder_id})
                        self.collectBtn.setIcon(MyFluentIcon.HAVE_COLLECT)
                        self.is_collect = True
                        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '收藏成功', self.parent(), InfoBarPosition.TOP)
            else:
                self.collectBtn.setIcon(MyFluentIcon.COLLECT)
                # 取消收藏
                sqlite_util.delete_data('cmbok_collection_record', {'key': self.book_id, 'type': 2})
                self.is_collect = False
                show_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self.parent(), InfoBarPosition.TOP)
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常', self.parent(), InfoBarPosition.TOP)
            sqlite_util.rollback()
            logging.info('收藏图书异常')
            logging.info(traceback.format_exc())
        finally:
            sqlite_util.close()


# 树形菜单
class TreeMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.treeFrame = TreeFrame(2)
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
