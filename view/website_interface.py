# coding:utf-8
import logging
import math
import os
import time
import traceback
import uuid
from functools import partial

import requests
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap, QMovie, QCursor, QIcon, QColor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QMainWindow, \
    QDesktopWidget, QFrame
from qfluentwidgets import ScrollArea, CardWidget, BodyLabel, FlowLayout, SearchLineEdit, SegmentedToolWidget, \
    FluentIcon, InfoBarPosition, Flyout, \
    FlyoutAnimationType, InfoBarIcon, PipsPager, PipsScrollButtonDisplayMode, FlyoutViewBase, PrimaryPushButton, \
    SingleDirectionScrollArea, CheckBox, StateToolTip

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from common.util import truncate_string, check_url, del_folder, \
    get_directories, move_files, get_current_time
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import CMBOK_WEBSITE, ComicWebsiteChapterImages, EpubThread


class WebsiteInterface(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('WebsiteInterface')
        self.resize(400, 400)

        self.pivot = SegmentedToolWidget(self)
        self.stackedWidget = QStackedWidget(self)

        self.hBoxLayout = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        # 顶部导航
        # 漫画站点
        self.comicAreaInterface = WebsiteAreaInterface('请输入名称搜索', 1)
        self.addSubInterface(self.comicAreaInterface, '漫画站点', MyFluentIcon.COMIC)
        # 图书站点
        self.bookAreaInterface = WebsiteAreaInterface('请输入名称搜索', 2)
        self.addSubInterface(self.bookAreaInterface, '图书站点', MyFluentIcon.BOOK)

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
        else:
            self.bookAreaInterface.banner.search(None)


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

        self.vBoxLayout.addWidget(self.lineEdit, alignment=Qt.AlignCenter)

        self.flowLayout = FlowLayout()
        # 查询站点记录
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

        # else:
        #    url = f'{CMBOK_WEBSITE}cmbok/book_website/website_count/{text}'

    # 获取站点记录
    def getRecords(self, text, index):
        # 清空流动布局内容
        self.flowLayout.takeAllWidgets()
        text = text or 'None'
        if self.type == 1:
            with SQLiteDatabase() as db:
                websites = db.query_data('comic_website', conditions={'name': f'%{text}%'})
                for website in websites:
                    card = WebsiteCard(
                        name=website.name,
                        icon=website.icon,
                        url=website.url,
                        comic_cover_dom=website.comic_cover_dom,
                        comic_name_dom=website.comic_name_dom,
                        chapter_name_dom=website.chapter_name_dom,
                        chapter_link_dom=website.chapter_link_dom,
                        img_dom=website.img_dom,
                        type=self.type
                    )
                    self.flowLayout.addWidget(card)
        # else:
        #    url = f'{CMBOK_WEBSITE}cmbok/book_website/website_count/{text}'


# 站点卡片
class WebsiteCard(CardWidget):
    def __init__(self, name, icon, url, comic_cover_dom=None, comic_name_dom=None,
                 chapter_name_dom=None, chapter_link_dom=None, img_dom=None, type=1,
                 parent=None):
        super().__init__(parent)
        self.type = type

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(150, 55)
        self.load_image(icon)

        self.titleLabel = BodyLabel(truncate_string(name, 15), self)
        if len(name) > 15:
            self.titleLabel.setToolTip(name)

        self.hBoxLayout = QHBoxLayout(self)
        self.setFixedWidth(260)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.iconWidget.mousePressEvent = partial(self.go_website, url, comic_cover_dom, comic_name_dom,
                                                  chapter_name_dom, chapter_link_dom, img_dom)

        # 用于保存打开的新窗口实例
        self.new_windows = []

    def go_website(self, url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                   img_dom, event):
        try:
            window = Browser(url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                             img_dom)
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


class Browser(QMainWindow):
    def __init__(self, url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                 img_dom):
        try:
            super().__init__()
            self.setWindowTitle("漫画站点")
            self.setGeometry(100, 100, 1280, 800)
            # 创建QWebEngineView对象
            self.url = url
            self.browser = QWebEngineView()
            self.setCentralWidget(self.browser)

            self.checked_chapters = []

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
            self.load_page()

    def get_chapters(self, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                     img_dom):

        # 使用 setTimeout 延迟执行 JavaScript 代码
        self.browser.page().runJavaScript("""
            setTimeout(() => {
                let links = [];
                let names = [];
                //漫画封面
                let comic_cover_dom = document.querySelector('""" + comic_cover_dom + """');
                let comic_cover = ''
                if(!!comic_cover_dom){
                    comic_cover = comic_cover_dom.src;
                }
                
                //漫画名称
                let comic_name_dom = document.querySelector('""" + comic_name_dom + """');
                let comic_name = ''
                if(!!comic_name_dom){
                    comic_name = comic_name_dom.innerText;
                }
                
                //章节地址
                let link_items = document.querySelectorAll('""" + chapter_link_dom + """');
                link_items.forEach(item => {
                    links.push(item.href);
                });
                
                //章节名称
                let name_items = document.querySelectorAll('""" + chapter_name_dom + """');
                name_items.forEach(item => {
                    names.push(item.innerText);
                });
                
                // 将链接和名称作为对象返回
                chapters = []
                let len = links.length
                for (let i = 0; i < len; i++) {
                  chapters.push({'name':names[i],'link':links[i]})
                }
                window.comicResult = {
                    'comic_cover':comic_cover,
                    'comic_name':comic_name,
                    'chapters':chapters
                }
            }, 200);  // 延迟200毫秒（0.2秒）
        """, self.get_python_links)

    def get_python_links(self, result):
        # 从 JavaScript 中获取链接
        time.sleep(0.5)
        self.browser.page().runJavaScript("window.comicResult", self.handle_results)

    def handle_results(self, result):
        if result is not None and len(result['chapters']) == 0:
            info_bar_tip(InfoBarIcon.WARNING, '温馨提示', '没有找到章节信息，o(╥﹏╥)o', self,
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
                    chapter['name'] = str(num) + '_' + chapter['name']
                    self.add_iframe(comic_name, chapter)
                else:
                    break
            else:
                break
        sqlite_util.close()

    def add_iframe(self, comic_name, chapter):
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

        iframe_url = chapter['link']
        iframe_id = "ifr" + str(uuid.uuid1()).lower().replace('-', '')
        js_code = """
            var iframe_id = '""" + iframe_id + """'
            window.""" + iframe_id + """ = {
                'iframe_id':iframe_id,
                'comic_name':'""" + comic_name + """',
                'chapter_name':'""" + chapter['name'] + """',
                'imgSrcs':[]
            }
            setTimeout(() => {
                var iframe = document.createElement('iframe');
                iframe.id = '""" + iframe_id + """';
                iframe.src = '""" + iframe_url + """';
                iframe.width = '100%';  // 设置宽度
                iframe.height = '500px'; // 设置高度
                iframe.style.visibility = 'hidden'
                document.body.appendChild(iframe);

                // 监听 iframe 加载完成事件
                iframe.onload = function() {
                    // 每次滚动一小段，直到达到页面底部
                    var scrollStep = 1000;  // 每次滚动的高度
                    var intervalTime = 100; // 滚动的时间间隔（毫秒）

                    function scrollToBottom() {
                        if (iframe.contentDocument.body.scrollHeight - iframe.contentWindow.scrollY > iframe.clientHeight+50) {
                            iframe.contentWindow.scrollBy(0, scrollStep);  // 向下滚动
                        } else {
                            clearInterval(scrollInterval); // 如果已经滚动到底部，则停止滚动
                            // 在滚动完成后获取图片
                            var imgElements = iframe.contentDocument.querySelectorAll('img'); // 获取所有图片
                            var imgSrcs = Array.from(imgElements).map(img => img.dataset.src || img.src).filter(src => !['https://www.rumanhua.com/static/images/logo.png', 'https://www.rumanhua.com/static/images/load.gif', 'https://www.rumanhua.com/static/images/off-l.png', 'https://www.rumanhua.com/static/images/next1.png', 'https://www.rumanhua.com/static/images/prev1.png'].includes(src)); // 提取图片的 src
                            window.""" + iframe_id + """['imgSrcs'] = imgSrcs // 返回图片的 src 列表
                            document.getElementById('""" + iframe_id + """').remove()
                        }
                    }

                    var scrollInterval = setInterval(scrollToBottom, intervalTime); // 开始定时滚动
                };
            }, 200);  // 延迟200毫秒（0.2秒）
            iframe_id
        """

        # 逐章节下载
        self.browser.page().runJavaScript(js_code, self.load_images)

    def load_images(self, iframe_id):
        # 从 JavaScript 中获取链接
        self.browser.page().runJavaScript("window." + iframe_id, self.get_images)

    def get_images(self, result):
        if isinstance(result['imgSrcs'], list) and len(result['imgSrcs']) > 0:
            self.comicWebsiteChapterImages = ComicWebsiteChapterImages(comic_name=result['comic_name'],
                                                                       chapter_name=result['chapter_name'],
                                                                       chapter_images=result['imgSrcs'])
            self.comicWebsiteChapterImages.success.connect(self.downloadComicStatus)
            self.comicWebsiteChapterImages.start()
        else:
            self.load_images(result['iframe_id'])

    def downloadComicStatus(self, comic_name):
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
        logging.info(str(record.chapter_num) + '===' + str(record.downloaded_num))
        if record.chapter_num == record.downloaded_num:
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
            self.epubThread.success.connect(self.download_finish)
            self.epubThread.start()
        else:
            self.stateTooltip.setContent(
                '已完成' + str(int(record.downloaded_num / record.chapter_num * 100)) + '%,请耐心等待~~')
            self.launch_iframes(comic_name)

    def download_finish(self):
        self.stateTooltip.hide()
        self.toggle_mask(1)
        self.chapter_button.setDisabled(False)


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
