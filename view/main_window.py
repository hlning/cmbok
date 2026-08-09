# coding:utf-8
import hashlib
import json
import logging
import time
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QUrl, QTimer
from PyQt5.QtGui import QIcon, QImage, QDesktopServices
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QApplication, QDesktopWidget, QStackedWidget
from qfluentwidgets import FluentIcon as FIF, SplashScreen, InfoBarIcon, InfoBarPosition, TeachingTip, \
    TeachingTipTailPosition
from qfluentwidgets import NavigationItemPosition, FluentWindow, SubtitleLabel, setFont, NavigationAvatarWidget, \
    MessageBox, toggleTheme, isDarkTheme, qconfig, NavigationDisplayMode

from common.sqlite_util import SQLiteDatabase
from common.signal_bus import signalBus
from resource import resource
from common.config import VERSION_NO, LOG_PATH, cfg
from service.startup_check_service import StartupCheckThread, ZlibraryHealthCheckThread
from custom.my_fluent_icon import MyFluentIcon
from utils.komga_utils import start_komga, stop_komga
from utils.utils_files_and_folders import clean_file
from view.book_interface import BookInterface
from view.components.account_avatar_widget import AccountAvatarWidget
from view.components.zlibrary_login_dialog import ZlibraryLoginDialog
from view.components.update_dialog import show_new_version_dialog
from view.collect_interface import CollectInterface
from view.comic_interface import ComicInterface
from view.components.info_bar_tip import show_tip
from view.download_interface import DownloadInterface, download_signals
from view.file_manager_interface import FileManagerInterface
from view.setting_interface import SettingInterface
from view.tool_interface import ToolInterface
from view.peer_transfer_interface import PeerTransferInterface
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
        # 在线传书窗口
        self.peerTransferInterface = PeerTransferInterface(self)
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
        # 导航切换刷新防抖：连续切换只刷新最后一次，且延迟到切换过渡完成后刷新
        self._navIndex = -1
        self._navTimer = QTimer(self)
        self._navTimer.setSingleShot(True)
        self._navTimer.setInterval(150)
        self._navTimer.timeout.connect(self._doNavRefresh)
        # 禁用导航切换的弹出动画（原 300ms 位置动画在内容多时掉帧），改为瞬时切换。
        # 直接调用 QStackedWidget 原生 setCurrentIndex：无动画、无 ani.finished 连接，
        # 仍触发 currentChanged（导航高亮 / on_navigation_changed 刷新照常）；
        # 避免 duration=0 动画在快速切换时 ani.finished 连接异步泄漏、随切换次数累积卡顿
        self.stackedWidget.setCurrentWidget = lambda widget, popOut=False: QStackedWidget.setCurrentIndex(
            self.stackedWidget.view, self.stackedWidget.view.indexOf(widget))
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
        # 启动检测（版本/公告/地址配置）放后台线程异步执行，不阻塞主线程；
        # 检测完成后通过信号回主线程提示/更新配置。持有引用避免运行中线程被 GC
        self._startupCheckThread = StartupCheckThread(self)
        self._startupCheckThread.versionFound.connect(self._onVersionFound)
        self._startupCheckThread.notificationReady.connect(self._onNotificationReady)
        self._startupCheckThread.urlConfigUpdated.connect(self._onUrlConfigUpdated)
        self._startupCheckThread.zlibraryUnavailable.connect(self._onZlibraryUnavailable)
        self._startupCheckThread.start()
        # zlibrary 可用状态（启动检测后修正；定时健康检查据此做状态变化通知）
        self._zlibrary_available = True
        # 当前 zlibrary 状态 InfoBar（持久提示需状态变化时主动关闭，避免恢复/不可用交替时堆叠）
        self._zlibrary_status_bar = None
        # 定时健康检查：每 30 分钟重新探测 zlibrary 多节点，状态变化时通知用户
        self._health_threads = set()
        self._zlibraryHealthTimer = QTimer(self)
        self._zlibraryHealthTimer.setInterval(30 * 60 * 1000)
        self._zlibraryHealthTimer.timeout.connect(self._check_zlibrary_health)
        self._zlibraryHealthTimer.start()

    # 运行komga
    def run_komga(self):
        # 配置了自定义 Komga 地址则不启动内置 Komga
        if cfg.get(cfg.customKomgaUrl):
            return
        if cfg.get(cfg.isRunKomga):
            start_komga()

    # 发现新版本：弹框询问是否前往下载
    def _onVersionFound(self, tag, body, html_url):
        show_new_version_dialog(self.window(), body, html_url)

    # 公告检测完成：有内容则顶部 InfoBar 提示
    # 仅用户主动点 X 关闭才记录为已读，下次启动同内容不再弹；
    # 15s 自动消失不记录，下次仍会提示
    def _onNotificationReady(self, notification):
        if not notification:
            return
        nid = hashlib.md5(notification.encode('utf-8')).hexdigest()
        if nid == cfg.get(cfg.lastNotificationId):
            return  # 该公告用户已主动关闭过，不再重复弹出
        bar = show_tip(InfoBarIcon.INFORMATION, '公告信息', notification, self,
                       InfoBarPosition.TOP, duration=15 * 1000)
        # 仅用户主动点 X 关闭才记录已读；15s 自动消失不记录，下次仍提示
        bar.closeButton.clicked.connect(lambda *args: self._markNotificationRead(nid))

    # 用户主动关闭公告：记录已读标识，下次启动不再弹同一条
    def _markNotificationRead(self, nid):
        cfg.set(cfg.lastNotificationId, nid)

    # 地址配置检测完成：更新 copy_url/zlibrary_url 及候选列表
    def _onUrlConfigUpdated(self, updates):
        if updates.get('copy_url'):
            cfg.set(cfg.copy_url, updates['copy_url'])
        if updates.get('zlibrary_url'):
            cfg.set(cfg.zlibrary_url, updates['zlibrary_url'])
        if updates.get('zlibrary_url_candidates'):
            cfg.set(cfg.zlibrary_url_candidates, json.dumps(updates['zlibrary_url_candidates']))
        # 探测到可用 zlibrary 最优节点 -> 标记可用（候选列表更新不代表可用，不据此设状态）
        if updates.get('zlibrary_url'):
            self._zlibrary_available = True

    # zlibrary_url 本地与云端候选全部不可用：提示图书功能受限（不拦截搜索，仅提示）
    def _onZlibraryUnavailable(self):
        self._zlibrary_available = False
        # 关闭旧的持久提示（如恢复后又变不可用），避免堆叠
        self._close_zlibrary_status_bar()
        self._zlibrary_status_bar = show_tip(
            InfoBarIcon.WARNING, '图书功能受限',
            '图书搜索/下载暂不可用，请等待恢复后再重试~', self,
            InfoBarPosition.TOP, duration=-1)

    # 定时健康检查：创建临时探测线程，持有引用防 GC，finished 后清理
    def _check_zlibrary_health(self):
        thread = ZlibraryHealthCheckThread(self)
        thread.available.connect(self._onHealthAvailable)
        thread.unavailable.connect(self._onHealthUnavailable)
        self._health_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._health_threads.discard(t))
        thread.start()

    # 定时检测发现可用节点：更新配置（若有更新）；之前不可用则通知已恢复
    def _onHealthAvailable(self, updates):
        was_available = self._zlibrary_available
        if updates:
            self._onUrlConfigUpdated(updates)  # 含设 available=True
        else:
            self._zlibrary_available = True  # 本地已最优，仅需标记可用
        if not was_available:
            # 恢复：关闭之前的「暂不可用」持久提示，再弹 5s 恢复提示（自动消失，不持有引用）
            self._close_zlibrary_status_bar()
            show_tip(InfoBarIcon.INFORMATION, '图书功能已恢复',
                     '节点已恢复可用~', self, InfoBarPosition.TOP, duration=5000)

    # 定时检测全部候选不可用：之前可用则通知暂不可用
    def _onHealthUnavailable(self):
        if self._zlibrary_available:
            self._zlibrary_available = False
            # 关闭旧持久提示（一般无，防御），避免堆叠
            self._close_zlibrary_status_bar()
            self._zlibrary_status_bar = show_tip(
                InfoBarIcon.WARNING, '图书功能受限',
                '图书功能暂不可用，请等待恢复~', self,
                InfoBarPosition.TOP, duration=-1)

    # 关闭并清理当前 zlibrary 状态 InfoBar（持久提示在状态变化时主动关闭，避免堆叠）
    def _close_zlibrary_status_bar(self):
        bar = self._zlibrary_status_bar
        if bar is not None:
            self._zlibrary_status_bar = None
            try:
                bar.close()
                bar.deleteLater()
            except Exception:
                pass

    # 监听侧边栏改变事件
    def on_navigation_changed(self, index):
        # 防抖：连续切换只保留最后一次，延迟到切换过渡完成后刷新
        self._navIndex = index
        self._navTimer.start(150)

    def _doNavRefresh(self):
        idx = self._navIndex
        # 已切到其他页面则跳过，避免刷新非当前页造成卡顿
        if self.stackedWidget.currentIndex() != idx:
            return
        if idx == 0:
            # 切回漫画搜索：重排卡片宽度自适应（窗口宽度可能已在其他界面变化）
            self.comicInterface.refreshCards()
        elif idx == 1:
            self.bookInterface.refreshCards()
        elif idx == 2:
            # 站点增删改已自行立即刷新列表，切回时仅在脏（首次未渲染）时重建，避免冗余重建
            if self.websiteInterface._website_dirty:
                self.websiteInterface.updateWebsiteRecords(1)
                self.websiteInterface._website_dirty = False
        elif idx == 4:
            # 仅在收藏数据变化（collectChanged 置脏）时刷新当前子界面
            ci = self.collectInterface
            i = ci.stackedWidget.currentIndex()
            if getattr(ci, '_dirty', [False, False])[i]:
                ci.updateComicRecords(i + 1)
                ci._dirty[i] = False
        elif idx == 5:
            # 下载页只调整表格列宽，数据刷新由 downloadFinish 处理
            self.downloadInterface.refreshTableSize()

    # 初始化侧边栏
    def initNavigation(self):
        self.addSubInterface(self.comicInterface, MyFluentIcon.COMIC, '漫画')
        self.addSubInterface(self.bookInterface, MyFluentIcon.BOOK, '图书')
        self.addSubInterface(self.websiteInterface, MyFluentIcon.WEBSITE, '站点')
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
        self.addSubInterface(self.peerTransferInterface, FIF.SYNC, '在线传书')
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
                                           get_logged_download_count, LOGGED_DAILY_LIMIT,
                                           get_profile_downloads)
        email = cfg.get(cfg.zlibrary_email)
        if email:  # 已登录：显示用户名 + 该账号当日下载 /10
            name = cfg.get(cfg.zlibrary_username) or email
            userid = cfg.get(cfg.zlibrary_remix_userid)
            # 自登账号优先用 profile 实际下载量（含外部消耗，区别于软件本地计数）；
            # 无缓存（如刚切换账号尚未搜索/下载）则回退本地计数
            pd = get_profile_downloads(userid)
            if pd is not None:
                count, limit = (pd[0] or 0), (pd[1] or LOGGED_DAILY_LIMIT)
            else:
                count, limit = get_logged_download_count(userid), LOGGED_DAILY_LIMIT
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
        # 噪音库降级到 WARNING：httpx/httpcore/urllib3 等默认 DEBUG，下载时每步 TCP/TLS 都同步
        # 写日志文件（一张图几十条 connect_tcp/start_tls），阻塞 asyncio 事件循环拖慢下载且刷屏。
        # 应用自身 logging.info/debug 不受影响。
        for _name in ('httpx', 'httpcore', 'httpcore.http1', 'httpcore.http2',
                      'urllib3', 'asyncio'):
            logging.getLogger(_name).setLevel(logging.WARNING)
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
