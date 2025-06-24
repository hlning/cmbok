# coding:utf-8
import datetime
import logging
import math
import re
import traceback

from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap, QMovie
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout
from qfluentwidgets import FlowLayout, CardWidget, SearchLineEdit, StateToolTip, PipsPager, \
    PipsScrollButtonDisplayMode, FluentIcon, TransparentToolButton, BodyLabel, InfoBarPosition, InfoBarIcon, \
    CaptionLabel, MessageBoxBase, ComboBox, PrimaryPushButton

from common.const import language_item
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import BookSearch, Book, BookDownload
from utils.base_utils import truncate_string, get_current_time
from view.components.folder_tree import TreeFrame
from view.components.info_bar_tip import show_tip


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
        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(700)
        self.lineEdit.setPlaceholderText('请输入图书名')
        self.lineEdit.searchSignal.connect(lambda text: self.searchBook(text, 0))
        self.lineEdit.returnPressed.connect(self.enter)

        # 重置按钮
        self.resetBtn = PrimaryPushButton(FluentIcon.SYNC, '重置')
        self.resetBtn.clicked.connect(self.reset)

        self.hBoxLayout1.addWidget(self.lineEdit)
        self.hBoxLayout1.addWidget(self.resetBtn)

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

        self.hBoxLayout2.addWidget(self.startDateComboBox)
        self.hBoxLayout2.addWidget(self.endDateComboBox)
        self.hBoxLayout2.addWidget(self.languageComboBox)
        self.hBoxLayout2.addWidget(self.extensionsComboBox)
        self.vBoxLayout.addLayout(self.hBoxLayout2)

        # 分页器
        self.pager = PipsPager(Qt.Horizontal)
        # 设置当前页
        self.pager.setCurrentIndex(0)
        # 始终显示前进和后退按钮
        self.pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        # 页码切换
        self.pager.currentIndexChanged.connect(lambda index: self.getBooks(index))

        self.flowLayout = FlowLayout()

        self.vBoxLayout.setContentsMargins(15, 0, 36, 0)
        self.vBoxLayout.setSpacing(10)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setHorizontalSpacing(12)
        self.flowLayout.setVerticalSpacing(12)
        self.vBoxLayout.addLayout(self.flowLayout, 1)
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignCenter | Qt.AlignVCenter)

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

            self.stateTooltip = StateToolTip('正在加载', '请耐心等待~~', self)
            self.stateTooltip.move(270, 25)
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
            else:
                self.stateTooltip.setTitle('加载完成')

                if results is not None:
                    pagination = results['pagination']
                    books = results['books']
                    if len(books) > 0:
                        if self.is_search:
                            self.book_list = books

                            # 更新分页器
                            total = pagination['total_items']
                            pageNumber = math.ceil(total / 8)

                            if pageNumber > 1:
                                # 设置页数
                                self.pager.setPageNumber(pageNumber)
                                # 设置圆点数量
                                self.pager.setVisibleNumber(10 if pageNumber > 10 else pageNumber)
                            else:
                                # 设置页数
                                self.pager.setPageNumber(1)
                            # 设置圆点数量
                            self.pager.setVisibleNumber(10 if pageNumber > 10 else pageNumber)

                            self.titleLabel.setText(
                                f'搜索结果（“{truncate_string(self.book_name, 15)}”共{total}条结果，共{pageNumber}页，当前第1页）')
                            self.stateTooltip.setContent('加载完成啦，(*^▽^*)')
                        else:
                            self.book_list.extend(books)
                            page_index = self.pager.currentIndex()
                            index = int(40 / 8 * (pagination['current'] - 1))
                            self.getBooks(page_index if page_index != index else index)
                    else:
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
            book_page = math.ceil(book_size / 8)
            # 查询新的图书
            if index + 1 > book_page:
                self.searchBook(self.book_name, int(book_size / 40), False)
            else:
                # 清空流布局中的所有控件
                self.flowLayout.takeAllWidgets()
                for book in self.book_list[index * 8:(index + 1) * 8]:
                    self.addSampleCard(book)
            # 更新当前页码
            page_info = self.titleLabel.text()
            self.titleLabel.setText(re.sub(r'当前第(\d+)页', f'当前第{index + 1}页', page_info))

    def addSampleCard(self, book):
        """ add sample card """
        card = BookCard(book, self)
        self.flowLayout.addWidget(card)


# 图书卡片
class BookCard(CardWidget):
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

        self.nameLabel = BodyLabel(truncate_string(self.name, 35), self)
        self.nameLabel.setToolTip(self.name)
        self.authorLabel = CaptionLabel(truncate_string(self.author, 36), self)
        self.authorLabel.setToolTip(self.author)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedSize(750, 73)
        self.authorLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
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
                w = TreeMessageBox(self.parent().parent())
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
