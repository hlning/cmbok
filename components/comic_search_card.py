# coding:utf-8
import logging
import math
import re
import traceback

from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtNetwork import QNetworkRequest, QNetworkAccessManager
from PyQt5.QtWidgets import QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget
from qfluentwidgets import TextWrap, FlowLayout, CardWidget, SearchLineEdit, StateToolTip, PipsPager, \
    PipsScrollButtonDisplayMode, FluentIcon, TransparentToolButton, Flyout, \
    CheckBox, FlyoutViewBase, BodyLabel, PrimaryPushButton, FlyoutAnimationType, SegmentedWidget, \
    SingleDirectionScrollArea, InfoBarPosition, InfoBarIcon

from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from common.util import truncate_string, get_current_time
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicSearch, ComicChapters, ComicChapterImages


# 搜索区域
class ComicSearchCardView(QWidget):
    """ Sample card view """
    success = pyqtSignal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent=parent)
        self.titleLabel = QLabel(title, self)
        self.lineEdit = SearchLineEdit()
        self.lineEdit.setPlaceholderText('请输入漫画名')
        self.lineEdit.searchSignal.connect(lambda text: self.searchComic(text, 0))
        self.lineEdit.returnPressed.connect(self.enter)

        self.comic_list = []
        self.comic_name = ''
        self.is_search = True

        # 分页器
        self.pager = PipsPager(Qt.Horizontal)
        # 设置页数
        self.pager.setPageNumber(0)
        # 设置当前页码
        self.pager.setCurrentIndex(0)
        # 设置圆点数量
        self.pager.setVisibleNumber(6)
        # 始终显示前进和后退按钮
        self.pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        # 页码切换
        self.pager.currentIndexChanged.connect(lambda index: self.getComics(index))

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
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignRight | Qt.AlignVCenter)

        self.titleLabel.setObjectName('viewTitleLabel')
        StyleSheet.SAMPLE_CARD.apply(self)

    # 回车搜索
    def enter(self):
        self.searchComic(self.lineEdit.text(), 0)

    # 搜索漫画
    def searchComic(self, text, offset, is_search=True):
        if text is not None and text != '' and self.stateTooltip is None:
            self.comic_name = text
            self.is_search = is_search

            self.stateTooltip = StateToolTip('正在加载', '请耐心等待~~', self)
            self.stateTooltip.move(320, 25)
            self.stateTooltip.show()

            self.comicSearch = ComicSearch(comic_name=text, offset=offset)
            self.comicSearch.success.connect(self.loadComicCard)
            self.comicSearch.start()
        elif text is not None and text == '':
            info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '请输入漫画名称进行搜索o(￣▽￣)ｄ', self)

    # 加载漫画搜索结果区域
    def loadComicCard(self, status, comic):
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

                if comic is not None:
                    # 清空流布局中的所有控件
                    self.flowLayout.takeAllWidgets()
                    comics = comic['list']
                    if len(comics) > 0:
                        if self.is_search:
                            self.comic_list = comics

                            # 显示分页器
                            total = int(comic['total'])
                            pageNumber = math.ceil(comic['total'] / 9)

                            if pageNumber > 1:
                                # 设置页数
                                self.pager.setPageNumber(pageNumber)
                            else:
                                # 设置页数
                                self.pager.setPageNumber(1)
                            # 设置圆点数量
                            self.pager.setVisibleNumber(6 if pageNumber > 6 else pageNumber)

                            self.titleLabel.setText(
                                f'搜索结果（“{self.comic_name}”共{total}条结果，共{pageNumber}页，当前第1页）')
                            self.stateTooltip.setContent('加载完成啦，(*^▽^*)')
                        else:
                            self.comic_list.extend(comics)
                            page_index = self.pager.currentIndex()
                            index = int(comic['limit']) / int(int(comic['offset']))
                            self.getComics(page_index if page_index != index else index)

                else:
                    self.stateTooltip.setContent('一本漫画都没有搜索到，o(╥﹏╥)o')
        except Exception as e:
            self.stateTooltip.setContent('系统异常，o(╥﹏╥)o')
            logging.info(traceback.format_exc())
            logging.info('渲染漫画查询结果失败')
        finally:
            self.stateTooltip.setState(True)
            self.stateTooltip = None

    # 从缓存中直接获取图书
    def getComics(self, index):
        comic_size = len(self.comic_list)
        if comic_size > 0:
            comic_page = math.ceil(comic_size / 9)
            # 查询新的图书
            if index + 1 > comic_page:
                self.searchComic(self.comic_name, int(comic_size / 27), False)
            else:
                # 清空流布局中的所有控件
                self.flowLayout.takeAllWidgets()
                for comic in self.comic_list[index * 9:(index + 1) * 9]:
                    self.addSampleCard(comic)
            # 更新当前页码
            page_info = self.titleLabel.text()
            self.titleLabel.setText(re.sub(r'当前第(\d+)页', f'当前第{index + 1}页', page_info))

    def addSampleCard(self, comic):
        """ add sample card """
        card = ComicCard(comic, self)
        self.flowLayout.addWidget(card)


# 漫画卡片
class ComicCard(CardWidget):
    """ Sample card """

    def __init__(self, comic, parent=None):
        super().__init__(parent=parent)
        # 漫画信息
        self.cover = comic['cover']
        self.name = comic["name"]
        self.author = comic['author'][0]['name']
        self.path_word = comic['path_word']

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(60, 85)
        self.load_image(self.cover)
        self.titleLabel = QLabel(truncate_string(self.name, 8), self)
        if len(self.name) > 8:
            self.titleLabel.setToolTip(self.name)
        self.authorLabel = QLabel(TextWrap.wrap(self.author, 30, False)[0], self)
        if len(self.author) > 30:
            self.authorLabel.setToolTip(self.author)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedSize(268, 90)

        self.hBoxLayout.setSpacing(28)
        self.hBoxLayout.setContentsMargins(20, 0, 0, 0)
        self.vBoxLayout.setSpacing(2)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)

        self.hBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.iconWidget)
        self.hBoxLayout.addLayout(self.vBoxLayout)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.authorLabel)

        # 按钮区域
        self.vBtnBoxLayout = QHBoxLayout()
        self.vBtnBoxLayout.addStretch()
        self.vBtnBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBtnBoxLayout.setAlignment(Qt.AlignRight)
        # 是否收藏
        self.is_collect = False
        sqlite_util = SQLiteDatabase()
        comics = sqlite_util.query_data('cmbok_collection_record', {'key': self.path_word, 'type': 1})
        if len(comics) > 0:
            self.is_collect = True
            collect_icon = MyFluentIcon.HAVE_COLLECT
        else:
            collect_icon = MyFluentIcon.COLLECT
        self.collectBtn = TransparentToolButton(collect_icon)
        self.collectBtn.setFixedWidth(30)
        self.collectBtn.clicked.connect(self.collectComic)

        self.vBtnBoxLayout.addWidget(self.collectBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 获取章节
        self.comicInfoBtn = TransparentToolButton(FluentIcon.SEND)
        self.comicInfoBtn.setFixedWidth(30)
        self.comicInfoBtn.clicked.connect(self.showComicInfo)
        self.vBtnBoxLayout.addWidget(self.comicInfoBtn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        # 按钮区域

        self.vBoxLayout.addLayout(self.vBtnBoxLayout)

        self.vBoxLayout.addStretch(1)

        self.titleLabel.setObjectName('titleLabel')
        self.authorLabel.setObjectName('authorLabel')

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
            self.load_fallback_image(':/cmbok/images/comic_cover.png')  # 加载备用图片
            logging.info(f"错误: {reply.errorString()}")  # 打印错误信息

    def load_fallback_image(self, fallback_image_path):
        """加载备用本地图片"""
        pixmap = QPixmap(fallback_image_path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)  # 设置标签的备用图片
        else:
            logging.info("备用图片加载失败")  # 处理备用图片加载失败的情况

    def showComicInfo(self):
        Flyout.make(DownloadFlyoutView(self.cover, self.name, self.author, self.path_word), self.comicInfoBtn, self,
                    aniType=FlyoutAnimationType.PULL_UP)

    def collectComic(self):
        sqlite_util = SQLiteDatabase()
        try:
            if not self.is_collect:
                self.collectBtn.setIcon(MyFluentIcon.HAVE_COLLECT)
                # 收藏
                sqlite_util.insert_data('cmbok_collection_record', {'cover': self.cover,
                                                                    'name': self.name, 'author': self.author,
                                                                    'key': self.path_word, 'type': 1,
                                                                    'collection_time': get_current_time()})
                self.is_collect = True
                info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', '收藏成功', self.parent())
            else:
                self.collectBtn.setIcon(MyFluentIcon.COLLECT)
                # 取消收藏
                sqlite_util.delete_data('cmbok_collection_record', {'key': self.path_word, 'type': 1})
                self.is_collect = False
                info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self.parent())
        except Exception:
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常', self.parent(), InfoBarPosition.TOP)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('收藏漫画异常')
        finally:
            sqlite_util.close()


# 下载自定义窗口
comic_name = ''
comic_path_word = ''
comic_author = ''


class DownloadFlyoutView(FlyoutViewBase):
    def __init__(self, icon, title, author, path_word, parent=None):
        super().__init__(parent)

        global comic_name
        global comic_path_word
        global comic_author
        comic_name = title
        comic_path_word = path_word
        comic_author = author

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.label = BodyLabel(title + '——' + author + '')
        self.label.setFixedWidth(500)

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(200, 280)
        self.load_image(icon)

        self.hBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addWidget(self.label)

        # 目录类型导航栏
        # 获取目录
        self.comicChapters = ComicChapters(path_word=path_word)
        self.comicChapters.success.connect(self.loadComicChapters)
        self.comicChapters.start()
        # 目录类型导航栏

        self.hBoxLayout.addLayout(self.vBoxLayout)

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
            self.load_fallback_image(':/cmbok/images/comic_cover.png')  # 加载备用图片
            logging.info(f"错误: {reply.errorString()}")  # 打印错误信息

    def load_fallback_image(self, fallback_image_path):
        """加载备用本地图片"""
        pixmap = QPixmap(fallback_image_path)
        if not pixmap.isNull():
            self.iconWidget.setPixmap(pixmap)  # 设置标签的备用图片
        else:
            logging.info("备用图片加载失败")  # 处理备用图片加载失败的情况

    def addSubInterface(self, widget, objectName, text):
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text)

    def loadComicChapters(self, status, results):
        try:
            if status == 'fail':
                info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '网络异常，o(╥﹏╥)o', self.parent(),
                             InfoBarPosition.TOP_RIGHT)
            elif status == 'timeout':
                info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '请求超时了，(。・＿・。)ﾉI’m sorry~', self.parent(),
                             InfoBarPosition.TOP_RIGHT)
            elif status == 'error':
                info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常，(。・＿・。)ﾉI’m sorry~', self.parent(),
                             InfoBarPosition.TOP_RIGHT)
            else:
                self.vBoxLayout.addWidget(ChapterGroupView(results))
        except Exception as e:
            logging.info(traceback.format_exc())
            logging.info('渲染漫画查询结果失败')


# 目录分组导航窗口
class ChapterGroupView(QWidget):

    def __init__(self, data, parent=None):
        super().__init__(parent)

        self.pivot = SegmentedWidget(self)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)

        groups = data['groups']
        for key in groups:
            group = groups[key]
            groupInterface = ChapterTypeView(group['chapters'])
            self.addSubInterface(groupInterface, group['name'], group['name'])

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)

        # 获取第一个分组
        first_key = next(iter(groups))
        first_group = groups[first_key]
        self.pivot.setCurrentItem(first_group['name'])

        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

    def addSubInterface(self, widget: QLabel, objectName, text):
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text)


# 目录类型导航窗口
class ChapterTypeView(QWidget):

    def __init__(self, chapters, parent=None):
        super().__init__(parent)
        self.pivot = SegmentedWidget(self)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)

        # type 1：话 2:卷 3:番外篇
        # 根据 type 字段分组
        grouped_data = {}
        chapters.sort(key=lambda t: t['type'])
        for item in chapters:
            type_name = '話' if item['type'] == 1 else '卷' if item['type'] == 2 else '番外篇'
            if type_name not in grouped_data:
                grouped_data[type_name] = []
            grouped_data[type_name].append(item)

        # 添加目录明细
        for type_name, chapter_list in grouped_data.items():
            typeInterface = ChapterDetailView(chapter_list)
            self.addSubInterface(typeInterface, type_name, type_name)

        # 获取第一个分组
        first_key = next(iter(grouped_data))
        self.pivot.setCurrentItem(first_key)

        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)

    def addSubInterface(self, widget, objectName, text):
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text)


# 漫画目录明细窗口
class ChapterDetailView(QWidget):

    def __init__(self, chapters, parent=None):
        super().__init__(parent)
        # 创建主布局
        self.layout = QVBoxLayout()

        # 创建滚动区域
        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Vertical)
        self.scroll_area.setWidgetResizable(True)  # 使子部件在滚动区域内调整大小
        self.scroll_area.setFixedHeight(200)

        # 创建一个框架以容纳其他控件
        self.scroll_content = QFrame()
        self.scroll_layout = QVBoxLayout(self.scroll_content)  # 使用垂直布局
        # 设置滚动区域的样式表，使背景透明
        self.scroll_content.setStyleSheet("QFrame { background: transparent; border: none; }")  # 设置透明背景和无边框

        # 添加多个标签作为示例内容
        self.flowlayout = FlowLayout()
        # 获取目录
        # 存储复选框的列表
        self.checkboxes = []
        if chapters is not None:
            # 全选复选框
            select_all_checkbox = CheckBox("全选")
            select_all_checkbox.stateChanged.connect(self.toggle_all)  # 连接信号
            self.flowlayout.addWidget(select_all_checkbox)
            for obj in chapters:
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
        self.download_button.clicked.connect(lambda: self.downloadComic(chapters))
        self.hbox_layout.addWidget(self.download_button)

        # 将横向布局添加到垂直布局
        self.layout.addLayout(self.hbox_layout)

        # 设置主布局
        self.setLayout(self.layout)

    def toggle_all(self, state):
        # 根据全选复选框的状态来勾选或取消所有复选框
        for checkbox in self.checkboxes:
            checkbox.setChecked(state == 2)  # 2表示选中状态

    def downloadComic(self, chapters):
        # 获取选中复选框的状态
        checked_items = [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]

        if len(checked_items) > 0:
            checked_chapters = []
            if checked_items:
                checked_chapters = [obj for obj in chapters if obj['name'] in checked_items]
            # 逐章节下载
            global comic_name
            global comic_path_word
            global comic_author

            self.label.setText("")
            self.comicChapterImages = ComicChapterImages(comic_name=comic_name, comic_path_word=comic_path_word,
                                                         comic_author=comic_author, checked_chapters=checked_chapters)
            self.comicChapterImages.success.connect(self.downloadComicStatus)
            self.comicChapterImages.start()
        else:
            self.label.setText("请先选择章节再进行下载，o(￣▽￣)ｄ")

    def downloadComicStatus(self, status):
        from view.collect_interface import CollectAreaInterface
        current_widget = self.parent()
        while current_widget is not None:
            if isinstance(current_widget, ComicSearchCardView) or isinstance(current_widget, CollectAreaInterface):
                current_widget.success.emit(status)
                return
            current_widget = current_widget.parent()  # 继续向上查找
