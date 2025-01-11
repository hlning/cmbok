import logging
import sys
import time
import traceback
from pathlib import Path

import requests
from PyQt5.QtCore import Qt, QTranslator, QSize, QUrl
from PyQt5.QtGui import QIcon, QImage, QDesktopServices
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QApplication
from qfluentwidgets import FluentIcon as FIF, SplashScreen, InfoBarIcon, InfoBarPosition, TeachingTip, \
    TeachingTipTailPosition
from qfluentwidgets import NavigationItemPosition, FluentWindow, SubtitleLabel, setFont, NavigationAvatarWidget, \
    MessageBox, FluentTranslator, toggleTheme

from common.config import cfg, LOG_PATH
from common.sqlite_util import SQLiteDatabase
from common.util import check_url, clean_file
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon
from view.book_interface import BookInterface
from view.collect_interface import CollectInterface
from view.comic_interface import ComicInterface
from view.download_interface import DownloadInterface
from view.setting_interface import SettingInterface
from resource import resource


class Widget(QFrame):

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.label = SubtitleLabel(text, self)
        self.hBoxLayout = QHBoxLayout(self)

        setFont(self.label, 24)
        self.label.setAlignment(Qt.AlignCenter)
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignCenter)

        # 必须给子界面设置全局唯一的对象名
        self.setObjectName(text.replace(' ', '-'))


class Window(FluentWindow):
    """ 主界面 """

    def __init__(self):
        super().__init__()

        self.initWindow()
        # 创建子界面，实际使用时将 Widget 换成自己的子界面
        # 漫画搜索窗口
        self.comicInterface = ComicInterface(self)
        # 图书搜索窗口
        self.bookInterface = BookInterface(self)
        # 收藏记录窗口
        self.collectInterface = CollectInterface(self)
        # 下载记录窗口
        self.downloadInterface = DownloadInterface()
        # 设置窗口
        self.settingInterface = SettingInterface(self)
        # 初始化侧边栏
        self.initNavigation()
        # 监听当前导航项变化的信号
        self.stackedWidget.currentChanged.connect(self.on_navigation_changed)
        # 配置日志记录
        self.setup_logging()
        # 清理日志文件
        clean_file(LOG_PATH)

        # 加点时间，看起来有动画
        time.sleep(0.5)
        # 隐藏启动页面
        self.splashScreen.finish()
        # 看是否有新版本或公告
        self.get_version()

    # 检查版本
    def get_version(self):
        try:
            # 是否检查版本更新
            is_update = cfg.get(cfg.checkUpdateAtStartUp)
            if is_update:
                url = 'https://bluemood.xiaomy.net/cmbok/version/version'
                # 检查状态码
                if check_url(url):
                    response = requests.get(url)
                    response.raise_for_status()
                    if response.status_code == 200:
                        results = response.json()
                        version = results['version']
                        if version is not None and version != '':
                            w = MessageBox("检测到新版本，是否更新？", version['content'], self.window())
                            if w.exec():
                                url = QUrl(version['url'])  # 要打开的链接
                                QDesktopServices.openUrl(url)
                            else:
                                logging.info('取消')
                        else:
                            self.get_notification()
            else:
                self.get_notification()
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('服务器已关闭')

    # 检查公告
    def get_notification(self):
        try:
            url = 'https://bluemood.xiaomy.net/cmbok/notification/notification'
            if check_url(url):
                response = requests.get(url)
                response.raise_for_status()
                if response.status_code == 200:
                    results = response.json()
                    if results['notification'] != '':
                        info_bar_tip(InfoBarIcon.INFORMATION, '公告信息', results['notification'], self,
                                     InfoBarPosition.TOP, duration=-1)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('服务器已关闭')

    # 监听侧边栏改变事件
    def on_navigation_changed(self, index):
        if index == 2:
            # 默认更新收藏记录
            self.collectInterface.updateComicRecords(1)
            self.collectInterface.updateComicRecords(2)
        if index == 3:
            # 默认更新下载记录
            self.downloadInterface.updateComicRecords(1)
            self.downloadInterface.updateComicRecords(2)

    # 初始化侧边栏
    def initNavigation(self):
        self.addSubInterface(self.comicInterface, MyFluentIcon.COMIC, '漫画')
        self.addSubInterface(self.bookInterface, MyFluentIcon.BOOK, '图书')
        self.addSubInterface(self.collectInterface, MyFluentIcon.COLLECT, '收藏')
        self.addSubInterface(self.downloadInterface, FIF.DOWNLOAD, '下载')

        self.navigationInterface.addSeparator()

        self.navigationInterface.addWidget(
            routeKey='avatar',
            widget=NavigationAvatarWidget('甜甜的王甜甜', QImage(':/cmbok/images/me.jpg')),
            onClick=self.showMessageBox,
            position=NavigationItemPosition.BOTTOM,
        )

        self.navigationInterface.addItem(
            routeKey='theme',
            text='主题',
            icon=FIF.CONSTRACT,
            onClick=toggleTheme,
            position=NavigationItemPosition.BOTTOM,
        )

        self.addSubInterface(
            self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

    def initWindow(self):
        self.setFixedSize(950, 900)
        self.setWindowIcon(QIcon(':/cmbok/images/logo.png'))
        self.setWindowTitle('Cmbok，来找点漫画和图书看看吧(✧◡✧)')

        # create splash screen
        self.splashScreen = SplashScreen(self.windowIcon(), self)

        self.splashScreen.setIconSize(QSize(200, 200))
        self.splashScreen.raise_()

        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)
        self.show()
        QApplication.processEvents()

    def showMessageBox(self):
        w = MessageBox(
            '我是甜甜🥰',
            '个人开发不易，如果这个项目帮助到了您，可以考虑请我喝一杯奶茶🍵。您的支持就是作者开发和维护项目的动力🚀',
            self
        )
        w.yesButton.setText('来啦')
        w.cancelButton.setText('下次一定')

        if w.exec():
            TeachingTip.create(
                target=self.navigationInterface,
                image=":/cmbok/images/wx.png",
                title='',
                content="您的支持是我最大的动力！",
                isClosable=True,
                tailPosition=TeachingTipTailPosition.LEFT_BOTTOM,
                duration=-1,
                parent=w
            )

    def setup_logging(self):
        file_path = Path(LOG_PATH)
        if not file_path.exists():
            file_path.touch()  # 创建文件，什么内容都不写
        logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')
        logging.info("应用程序启动")

    def closeEvent(self, event):
        with SQLiteDatabase() as db:
            historys = db.query_data('cmbok_download_history', {'status': 1})
            if len(historys) > 0:
                w = MessageBox("提示信息", "确认退出吗？所有未完成的任务都会失败", self)
                if w.exec():
                    # 更新下载任务
                    db.update_data('cmbok_download_history', {'status': -3}, {'status': 1})
                    event.accept()  # 允许关闭
                else:
                    event.ignore()  # 忽略关闭事件
            else:
                event.accept()

    def handle_exception(self, e):
        # 更新下载任务
        with SQLiteDatabase() as db:
            db.update_data('cmbok_download_history', {'status': -3}, {'status': 1})


if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # 初始化数据库
    sqlite_util = SQLiteDatabase()
    sqlite_util.init()

    app = QApplication(sys.argv)
    # internationalization
    locale = cfg.get(cfg.language).value
    translator = FluentTranslator(locale)
    galleryTranslator = QTranslator()
    galleryTranslator.load(locale, "cmbok", ".", ":/cmbok/i18n")

    app.installTranslator(translator)
    app.installTranslator(galleryTranslator)

    w = Window()
    w.show()
    app.exec()
