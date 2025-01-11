# coding:utf-8
import logging
import math
import re
import traceback

from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout
from qfluentwidgets import FlowLayout, CardWidget, SearchLineEdit, StateToolTip, PipsPager, \
    PipsScrollButtonDisplayMode, FluentIcon, TransparentToolButton, BodyLabel, InfoBarPosition, InfoBarIcon, \
    CaptionLabel

from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from common.util import truncate_string, get_current_time
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import BookSearch, BookDownload


# 搜索区域
class BookSearchCardView(QWidget):
    """ Sample card view """
    success = pyqtSignal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent=parent)
        self.titleLabel = QLabel(title, self)
        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(700)
        self.lineEdit.setPlaceholderText('请输入图书名')
        self.lineEdit.searchSignal.connect(lambda text: self.searchBook(text, 0))
        self.lineEdit.returnPressed.connect(self.enter)

        self.book_list = []
        self.book_name = ''
        self.is_search = True

        # 分页器
        self.pager = PipsPager(Qt.Horizontal)
        # 设置当前页
        self.pager.setCurrentIndex(0)
        # 始终显示前进和后退按钮
        self.pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        # 页码切换
        self.pager.currentIndexChanged.connect(lambda index: self.getBooks(index))

        self.vBoxLayout = QVBoxLayout(self)
        self.flowLayout = FlowLayout()

        self.stateTooltip = None

        self.vBoxLayout.setContentsMargins(36, 0, 36, 0)
        self.vBoxLayout.setSpacing(10)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setHorizontalSpacing(12)
        self.flowLayout.setVerticalSpacing(12)

        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.lineEdit)
        self.vBoxLayout.addLayout(self.flowLayout, 1)
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignCenter | Qt.AlignVCenter)

        self.titleLabel.setObjectName('viewTitleLabel')
        StyleSheet.SAMPLE_CARD.apply(self)

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

            self.bookSearch = BookSearch(book_name=text, index=index + 1)
            self.bookSearch.success.connect(self.loadBookCard)
            self.bookSearch.start()
        elif text is not None and text == '':
            info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '请输入图书名称进行搜索o(￣▽￣)ｄ', self)

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

        self.nameLabel = BodyLabel(truncate_string(self.name, 15), self)
        if len(self.name) > 15:
            self.nameLabel.setToolTip(self.name)
        self.authorLabel = CaptionLabel(truncate_string(self.author, 16), self)
        if len(self.author) > 16:
            self.authorLabel.setToolTip(self.author)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedSize(700, 73)
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
                self.collectBtn.setIcon(MyFluentIcon.HAVE_COLLECT)
                # 收藏
                sqlite_util.insert_data('cmbok_collection_record', {'cover': self.cover,
                                                                    'name': self.name, 'author': self.author,
                                                                    'key': self.book_id, 'book_hash': self.book_hash,
                                                                    'book_extension': self.extension, 'type': 2,
                                                                    'collection_time': get_current_time()})
                self.is_collect = True
                info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', '收藏成功', self.parent(), InfoBarPosition.TOP)
            else:
                self.collectBtn.setIcon(MyFluentIcon.COLLECT)
                # 取消收藏
                sqlite_util.delete_data('cmbok_collection_record', {'key': self.book_id, 'type': 2})
                self.is_collect = False
                info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self.parent(), InfoBarPosition.TOP)
        except Exception:
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常', self.parent(), InfoBarPosition.TOP)
            sqlite_util.rollback()
            logging.info('收藏图书异常')
            logging.info(traceback.format_exc())
        finally:
            sqlite_util.close()
