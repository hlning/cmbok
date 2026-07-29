# coding:utf-8
import logging
import time
import traceback
from pathlib import Path

import requests
from PyQt5.QtCore import Qt, QSize, QUrl, QTimer
from PyQt5.QtGui import QIcon, QImage, QDesktopServices
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QApplication, QDesktopWidget
from qfluentwidgets import FluentIcon as FIF, SplashScreen, InfoBarIcon, InfoBarPosition, TeachingTip, \
    TeachingTipTailPosition
from qfluentwidgets import NavigationItemPosition, FluentWindow, SubtitleLabel, setFont, NavigationAvatarWidget, \
    MessageBox, toggleTheme, isDarkTheme, qconfig, NavigationDisplayMode

from common.sqlite_util import SQLiteDatabase
from common.signal_bus import signalBus
from resource import resource
from common.config import VERSION_NO, LOG_PATH, cfg, GITHUBURL, GITHUB_RELEASE_API, NOTIFICATION_URL
from custom.my_fluent_icon import MyFluentIcon
from utils.komga_utils import start_komga, stop_komga
from utils.utils_files_and_folders import clean_file
from view.book_interface import BookInterface
from view.components.account_avatar_widget import AccountAvatarWidget
from view.components.zlibrary_login_dialog import ZlibraryLoginDialog
from view.collect_interface import CollectInterface
from view.comic_interface import ComicInterface
from view.components.info_bar_tip import show_tip
from view.download_interface import DownloadInterface, download_signals
from view.file_manager_interface import FileManagerInterface
from view.setting_interface import SettingInterface
from view.tool_interface import ToolInterface
from view.website_interface import WebsiteInterface


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
        # 漫画网站窗口
        self.websiteInterface = WebsiteInterface(self)
        # 文件管理窗口
        self.fileManagerInterface = FileManagerInterface(self)
        # 收藏记录窗口
        self.collectInterface = CollectInterface(self)
        # 下载记录窗口
        self.downloadInterface = DownloadInterface(self)
        # 工具窗口
        self.toolInterface = ToolInterface(self)
        # 设置窗口
        self.settingInterface = SettingInterface(self)
        # 初始化侧边栏
        self.initNavigation()
        # 监听 z-library 登录态变化，更新左下角头像
        signalBus.zlibraryLoginChanged.connect(self._onZlibraryLoginChanged)
        # 监听毛玻璃开关变化，即时应用/取消 Mica 效果
        signalBus.micaEnableChanged.connect(self.setMicaEffectEnabled)
        # 下载完成/失败后刷新头像的下载计数显示
        download_signals.success.connect(self._refreshAvatarDisplay)
        # 监听当前导航项变化的信号
        self.stackedWidget.currentChanged.connect(self.on_navigation_changed)
        # 更新配置文件中的版本号
        cfg.set(cfg.version, VERSION_NO)
        # 配置日志记录
        self.setup_logging()
        # 清理日志文件
        clean_file(LOG_PATH)
        # 检测komga是否随应用启动运行
        self.run_komga()
        # 加点时间，看起来有动画
        time.sleep(0.5)
        # 隐藏启动页面
        self.splashScreen.finish()
        # 看是否有新版本或公告
        self.get_version()

    # 运行komga
    def run_komga(self):
        # 配置了自定义 Komga 地址则不启动内置 Komga
        if cfg.get(cfg.customKomgaUrl):
            return
        if cfg.get(cfg.isRunKomga):
            start_komga()

    # 检查版本（GitHub Releases）
    def get_version(self):
        try:
            if cfg.get(cfg.checkUpdateAtStartUp):
                response = requests.get(GITHUB_RELEASE_API, timeout=10)
                if response.status_code == 200:
                    release = response.json()
                    tag = release.get('tag_name', '')
                    if tag and tag != cfg.get(cfg.version):
                        body = release.get('body') or '发现新版本，是否前往下载？'
                        html_url = release.get('html_url') or GITHUBURL
                        w = MessageBox("检测到新版本，是否更新？", body, self.window())
                        if w.exec():
                            QDesktopServices.openUrl(QUrl(html_url))
                        return
            # 无新版本/未开启检测/请求失败：显示公告
            self.get_notification()
        except Exception:
            logging.info(traceback.format_exc())
            self.get_notification()

    # 检查公告（jsDelivr 拉取仓库 notification.json）
    def get_notification(self):
        try:
            response = requests.get(NOTIFICATION_URL, timeout=10)
            if response.status_code == 200:
                notification = response.json().get('notification', '')
                if notification:
                    show_tip(InfoBarIcon.INFORMATION, '公告信息', notification, self,
                             InfoBarPosition.TOP, duration=15 * 1000)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('服务器已关闭')

    # 监听侧边栏改变事件
    def on_navigation_changed(self, index):
        if index == 0:
            # 切回漫画搜索：重排卡片宽度自适应（窗口宽度可能已在其他界面变化）
            QTimer.singleShot(0, self.comicInterface.refreshCards)
        if index == 1:
            QTimer.singleShot(0, self.bookInterface.refreshCards)
        if index == 2:
            # 默认更新站点记录
            self.websiteInterface.updateWebsiteRecords(1)
            self.websiteInterface.updateWebsiteRecords(2)
        if index == 4:
            # 默认更新收藏记录
            self.collectInterface.updateComicRecords(1)
            self.collectInterface.updateComicRecords(2)
        if index == 5:
            # 默认更新下载记录
            self.downloadInterface.updateComicRecords(1)
            self.downloadInterface.updateComicRecords(2)
            QTimer.singleShot(0, self.downloadInterface.refreshTableSize)

    # 初始化侧边栏
    def initNavigation(self):
        self.addSubInterface(self.comicInterface, MyFluentIcon.COMIC, '漫画')
        self.addSubInterface(self.bookInterface, MyFluentIcon.BOOK, '图书')
        self.addSubInterface(self.websiteInterface, MyFluentIcon.WEBSITE, '网站')
        self.navigationInterface.addItem(
            routeKey='Komga',
            icon=MyFluentIcon.KOGMA,
            text='Komga',
            onClick=self.onKomga,
            selectable=False,
            tooltip='Komga',
            position=NavigationItemPosition.TOP
        )
        self.addSubInterface(self.fileManagerInterface, MyFluentIcon.FILE_MANAGER, '文件管理')
        self.addSubInterface(self.collectInterface, MyFluentIcon.COLLECT, '收藏')
        self.addSubInterface(self.downloadInterface, FIF.DOWNLOAD, '下载')
        self.addSubInterface(self.toolInterface, MyFluentIcon.TOOL, '工具箱')
        self.navigationInterface.addSeparator()

        # 左下角 z-library 登录状态头像
        is_zlibrary_logged = bool(cfg.get(cfg.zlibrary_email))
        self.avatarWidget = AccountAvatarWidget(
            cfg.get(cfg.zlibrary_email) if is_zlibrary_logged else '未登录',
            self._avatarImage(is_zlibrary_logged))
        self.navigationInterface.addWidget(
            routeKey='avatar',
            widget=self.avatarWidget,
            onClick=self.onZlibraryLogin,
            position=NavigationItemPosition.BOTTOM,
        )
        # 主题变化时刷新未登录图标（黑/白变体）
        qconfig.themeChanged.connect(self._updateAvatarImage)

        self.navigationInterface.addItem(
            routeKey='theme',
            text='主题',
            icon=self._themeIcon(),
            onClick=self.onToggleTheme,
            position=NavigationItemPosition.BOTTOM,
        )
        # 主题切换后更新图标
        qconfig.themeChanged.connect(self._updateThemeIcon)

        self.addSubInterface(
            self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

        # 导航展开宽度缩短一半（默认 312 -> 156）
        self.navigationInterface.setExpandWidth(156)
        # 启动时按配置设置导航展开/折叠
        panel = self.navigationInterface.panel
        is_expanded = panel.displayMode in (NavigationDisplayMode.MENU, NavigationDisplayMode.EXPAND)
        if cfg.get(cfg.navigationExpanded) and not is_expanded:
            self.navigationInterface.expand()
        elif not cfg.get(cfg.navigationExpanded) and is_expanded:
            self.navigationInterface.toggle()
        # 监听导航展开/折叠，同步到配置
        self.navigationInterface.displayModeChanged.connect(self._onNavigationDisplayChanged)
        # 初始化头像下载计数显示
        self._refreshAvatarDisplay()

    def onKomga(self):
        # 配置了自定义地址则打开自定义地址，否则打开内置 Komga
        custom = cfg.get(cfg.customKomgaUrl)
        url = custom if custom else 'http://127.0.0.1:25600/'
        QDesktopServices.openUrl(QUrl(url))

    # 主题切换图标：明亮模式显示月亮，暗黑模式显示太阳
    def _themeIcon(self):
        return MyFluentIcon.SUN if isDarkTheme() else MyFluentIcon.MOON

    def _updateThemeIcon(self):
        w = self.navigationInterface.widget('theme')
        if w is not None:
            w.setIcon(self._themeIcon())

    def onToggleTheme(self):
        toggleTheme(save=True)  # save=True 保存到 config.json，重启后保持

    def initWindow(self):
        # 窗口宽高可拖动调整，范围限定在设置项允许的 [最小, 最大] 之间（与 RangeValidator 一致）
        min_w = cfg.windowWidth.validator.min
        max_w = cfg.windowWidth.validator.max
        min_h = cfg.windowHeight.validator.min
        max_h = cfg.windowHeight.validator.max

        # 最大不超过屏幕可用区，避免超出屏幕
        desktop = QApplication.desktop().availableGeometry()
        max_w = min(max_w, desktop.width())
        max_h = min(max_h, desktop.height() - 50)

        self.setMinimumWidth(min_w)
        self.setMaximumWidth(max_w)
        self.setMinimumHeight(min_h)
        self.setMaximumHeight(max_h)

        # 初始尺寸用配置值（且不超出当前最大限制）
        self.resize(min(cfg.get(cfg.windowWidth), max_w),
                    min(cfg.get(cfg.windowHeight), max_h))

        self.setWindowIcon(QIcon(':/cmbok/images/logo.png'))
        self.setWindowTitle('Cmbok，来找点漫画和图书看看吧(✧◡✧)')
        # 应用毛玻璃效果（Mica，受个性化开关控制；仅 Windows 11 生效）
        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        # 拖动调整尺寸后，防抖写回配置（避免拖动过程中频繁写文件）
        self._resizeTimer = QTimer(self)
        self._resizeTimer.setSingleShot(True)
        self._resizeTimer.timeout.connect(self._saveWindowSize)

        # create splash screen
        self.splashScreen = SplashScreen(self.windowIcon(), self)

        self.splashScreen.setIconSize(QSize(200, 200))
        self.splashScreen.raise_()

        self.move(desktop.width() // 2 - self.width() // 2,
                  desktop.height() // 2 - self.height() // 2)
        self.show()
        QApplication.processEvents()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 拖动过程中持续重置定时器，停止拖动 300ms 后才写回配置
        if hasattr(self, '_resizeTimer'):
            self._resizeTimer.start(300)

    def _saveWindowSize(self):
        # 尺寸与配置不同才写回，避免初始 show 时空写
        w, h = self.width(), self.height()
        if w != cfg.get(cfg.windowWidth) or h != cfg.get(cfg.windowHeight):
            cfg.set(cfg.windowWidth, w)
            cfg.set(cfg.windowHeight, h)

    def onZlibraryLogin(self):
        # 左下角头像点击：内置账号模式无需登录；已登录提示登出；未登录弹登录框
        if cfg.get(cfg.use_zlibrary_builtin_account):
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '当前为内置账号模式，无需登录', self,
                     InfoBarPosition.TOP, duration=3000)
            return
        if cfg.get(cfg.zlibrary_email):
            # 已登录 -> 提示登出
            w = MessageBox('提示', '是否退出当前账号？', self)
            w.yesButton.setText('确定')
            w.cancelButton.setText('取消')
            if w.exec():
                cfg.set(cfg.zlibrary_email, '')
                cfg.set(cfg.zlibrary_username, '')
                cfg.set(cfg.zlibrary_remix_userid, '')
                cfg.set(cfg.zlibrary_remix_userkey, '')
                self._onZlibraryLoginChanged('')
                show_tip(InfoBarIcon.INFORMATION, '温馨提示', '已退出登录', self,
                         InfoBarPosition.TOP, duration=3000)
        else:
            # 未登录 -> 弹登录框（登录成功由 signalBus 触发 _onZlibraryLoginChanged）
            dlg = ZlibraryLoginDialog(self)
            action = {'register': False}
            dlg.registerRequested.connect(lambda: action.__setitem__('register', True))
            if dlg.exec():
                pass
            elif action['register']:
                from view.components.zlibrary_register_dialog import ZlibraryRegisterDialog
                ZlibraryRegisterDialog(self).exec()

    def _onZlibraryLoginChanged(self, email):
        # 登录态变化时更新左下角头像名称、计数、图标，并提示
        self._refreshAvatarDisplay()
        self.avatarWidget.setAvatar(self._avatarImage(bool(email)))
        if email:
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '登录成功', self,
                     InfoBarPosition.TOP, duration=3000)

    # 刷新头像显示：名称 + 当日下载计数（未登录用内置账号 5，已登录按账号 10）
    def _refreshAvatarDisplay(self, *args):
        from service.cmbok_service import (get_builtin_download_count, BUILTIN_DAILY_LIMIT,
                                           get_logged_download_count, LOGGED_DAILY_LIMIT)
        email = cfg.get(cfg.zlibrary_email)
        if email:  # 已登录：显示用户名 + 该账号当日下载 /10
            name = cfg.get(cfg.zlibrary_username) or email
            userid = cfg.get(cfg.zlibrary_remix_userid)
            count = get_logged_download_count(userid)
            limit = LOGGED_DAILY_LIMIT
        else:  # 未登录：显示内置账号限额 /5
            name = '未登录'
            count = get_builtin_download_count()
            limit = BUILTIN_DAILY_LIMIT
        self.avatarWidget.setName(name)
        self.avatarWidget.setSubText(f'当日下载：{count}/{limit}')

    # 导航展开/折叠同步到配置
    def _onNavigationDisplayChanged(self, mode):
        is_expanded = mode in (NavigationDisplayMode.MENU, NavigationDisplayMode.EXPAND)
        cfg.set(cfg.navigationExpanded, is_expanded)
        # 导航展开/收缩改变内容区宽度，立即+动画结束后刷新下载表格列宽自适应
        QTimer.singleShot(0, self.downloadInterface.refreshTableSize)
        QTimer.singleShot(400, self.downloadInterface.refreshTableSize)

    # 头像图标：未登录用 no-login 黑/白变体随主题切换，已登录用 login.png
    def _avatarImage(self, logged_in):
        # 走 qrc 资源路径（:/cmbok/...），打包后由 resource.py 内嵌提供，避免相对路径找不到
        if logged_in:
            return QImage(':/cmbok/images/login.png')
        return QImage(':/cmbok/images/no-login-white.png' if isDarkTheme()
                      else ':/cmbok/images/no-login-black.png')

    def _updateAvatarImage(self):
        self.avatarWidget.setAvatar(self._avatarImage(bool(cfg.get(cfg.zlibrary_email))))

    def setup_logging(self):
        file_path = Path(LOG_PATH)
        if not file_path.exists():
            file_path.touch()  # 创建文件，什么内容都不写
        # 创建日志器
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)  # 设置全局日志等级

        # 创建日志文件处理器
        file_handler = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # 设置日志处理器的等级

        # 日志格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)

        # 添加处理器到日志器
        logger.addHandler(file_handler)
        logging.info("应用程序启动")

    def closeEvent(self, event):
        with SQLiteDatabase() as db:
            historys = db.query_data('cmbok_download_history', {'status': 1})
            if len(historys) > 0:
                w = MessageBox("提示信息", "确认退出吗？所有未完成的任务都会失败", self)
                if w.exec():
                    # 更新下载任务
                    db.update_data('cmbok_download_history', {'status': -3}, {'status': 1})
                    stop_komga()  # 确认退出才关闭 Komga
                    self._cleanup_info_bars()  # 清理 InfoBar，避免退出时 eventFilter 访问已销毁对象
                    event.accept()  # 允许关闭
                else:
                    event.ignore()  # 忽略关闭事件，Komga 保持运行
            else:
                stop_komga()  # 无未完成任务，关闭 Komga
                self._cleanup_info_bars()
                event.accept()

    def _cleanup_info_bars(self):
        """退出前移除 InfoBar manager 安装的 eventFilter 并清空，
        避免 C++ 对象销毁后 eventFilter 仍被调用导致 RuntimeError"""
        try:
            from qfluentwidgets.components.widgets.info_bar import InfoBarManager
            for mgr_cls in InfoBarManager.managers.values():
                mgr = mgr_cls()
                for p in list(mgr.infoBars.keys()):
                    try:
                        p.removeEventFilter(mgr)
                    except Exception:
                        pass
                mgr.infoBars.clear()
        except Exception:
            logging.info(traceback.format_exc())

    def handle_exception(self, e):
        # 更新下载任务
        with SQLiteDatabase() as db:
            db.update_data('cmbok_download_history', {'status': -3}, {'status': 1})
