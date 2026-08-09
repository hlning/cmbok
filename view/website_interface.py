# coding:utf-8
import json
import logging
import math
import os
import re
import time
import traceback
import uuid
from functools import partial

from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer, QEvent, QRectF, QSize, QObject
from PyQt5.QtGui import QPixmap, QMovie, QCursor, QIcon, QColor, QPainter, QDesktopServices, QPainterPath
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineDownloadItem
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QMainWindow, \
    QDesktopWidget, QFrame, QFileDialog
from qfluentwidgets import ScrollArea, CardWidget, ElevatedCardWidget, BodyLabel, FlowLayout, SearchLineEdit, SegmentedToolWidget, \
    FluentIcon, InfoBarPosition, Flyout, \
    FlyoutAnimationType, InfoBarIcon, PipsPager, PipsScrollButtonDisplayMode, FlyoutViewBase, PrimaryPushButton, \
    SingleDirectionScrollArea, CheckBox, StateToolTip, MessageBox, MessageBoxBase, TransparentToolButton, LineEdit, ComboBox, \
    Theme, PrimaryToolButton, themeColor, isDarkTheme, ThemeColor

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicWebsiteChapterImages, EpubThread, WebsiteChapterFetchThread
from utils.base_utils import truncate_string, get_current_time, get_directories, deal_url, get_file_extension
from utils.image_restore import restore_image
from utils.client_util import get_system_proxy
from utils.utils_files_and_folders import del_folder, move_files
from view.components.auto_flow_layout import AutoFlowLayout
from view.components.detail_dialog_base import present_detail_dialog, content_parent
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
        # 站点列表脏标记：首次访问需渲染；站点增删改后已自行立即 search(None) 刷新，
        # 故切回网站页时仅在脏（首次未渲染）时重建，避免每次切换都 takeAllWidgets+重建卡片
        self._website_dirty = True

        self.titleLabel = QLabel('🖥️漫画站点', self)
        self.titleLabel.setObjectName('viewTitleLabel')

        self.vBoxLayout = QVBoxLayout(self)

        # 漫画站点
        self.comicAreaInterface = WebsiteAreaInterface('请输入名称搜索', 1)

        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.comicAreaInterface, 1)
        self.vBoxLayout.setContentsMargins(36, 20, 36, 15)
        self.vBoxLayout.setSpacing(12)
        StyleSheet.SAMPLE_CARD.apply(self)

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

        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        # 透明滚动条，避免占用右侧边距（与漫画搜索 resultScrollArea 一致）
        self.verticalScrollBar().setStyleSheet(
            'QScrollBar:vertical { background: transparent; width: 3px; margin: 0; }'
            'QScrollBar::handle:vertical { background: rgba(128, 128, 128, 120); '
            'border-radius: 4px; min-height: 30px; }'
            'QScrollBar::handle:vertical:hover { background: rgba(128, 128, 128, 200); }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
            'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }')


# 漫画站点记录窗口
class WebsitWidget(QWidget):
    success = pyqtSignal()

    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.type = type
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(10)

        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setFixedHeight(40)
        self.lineEdit.searchButton.setIconSize(QSize(14, 14))
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
            self.addBtn.setFixedSize(36, 36)
            self.addBtn.setToolTip('新增站点')
            self.addBtn.clicked.connect(self.addWebsite)
            self.searchLayout.addWidget(self.addBtn)

            self.importBtn = PrimaryToolButton(FluentIcon.DOWN)
            self.importBtn.setFixedSize(36, 36)
            self.importBtn.setToolTip('导入站点')
            self.importBtn.clicked.connect(self.importWebsite)
            self.searchLayout.addWidget(self.importBtn)

            self.exportBtn = PrimaryToolButton(FluentIcon.UP)
            self.exportBtn.setFixedSize(36, 36)
            self.exportBtn.setToolTip('导出站点')
            self.exportBtn.clicked.connect(self.exportWebsite)
            self.searchLayout.addWidget(self.exportBtn)

            self.downloadMgrBtn = PrimaryToolButton(FluentIcon.DOWNLOAD)
            self.downloadMgrBtn.setFixedSize(36, 36)
            self.downloadMgrBtn.setToolTip('下载管理（跨域站点）')
            self.downloadMgrBtn.clicked.connect(self.openDownloadManager)
            self.searchLayout.addWidget(self.downloadMgrBtn)
        self.searchLayout.addStretch()
        self.vBoxLayout.addLayout(self.searchLayout)

        # 站点卡片容器：flowLayout 放入 flowContainer，再由 resultStack 与空状态切换
        self.flowContainer = QWidget(self)
        self.flowLayout = AutoFlowLayout(self.flowContainer)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
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
        win = self.window()
        dlg = WebsiteEditDialog(content_parent(win))
        def _on_accepted():
            with SQLiteDatabase() as db:
                db.insert_data('comic_website', dlg.get_data())
            self.search(None)
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '新增成功', win, InfoBarPosition.TOP)
        dlg.accepted.connect(_on_accepted)
        present_detail_dialog(dlg)

    # 导出站点：弹窗勾选要导出的站点，序列化为 JSON 写入用户选择的文件
    def exportWebsite(self):
        with SQLiteDatabase() as db:
            websites = db.query_data('comic_website')
        if not websites:
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '暂无站点可导出', self.window(), InfoBarPosition.TOP)
            return
        dlg = WebsiteExportDialog(websites, self.window())
        if not dlg.exec():
            return
        selected = dlg.get_selected()
        if not selected:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请至少选择一个站点', self.window(), InfoBarPosition.TOP)
            return
        default_name = f'comic_websites_{get_current_time("%Y%m%d_%H%M%S")}.json'
        path, _ = QFileDialog.getSaveFileName(self.window(), '选择导出位置', default_name, '站点配置文件 (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        # 导出全字段（含 UI 未暴露的 comic_author_dom 等），动态取 Row 全部属性，去 id
        payload = {
            'version': 1,
            'export_time': get_current_time(),
            'sites': [{k: v for k, v in w.__dict__.items() if k != 'id'} for w in selected]
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', f'导出成功：{len(selected)} 个站点',
                     self.window(), InfoBarPosition.TOP)
        except Exception:
            logging.info('导出站点失败: ' + traceback.format_exc())
            show_tip(InfoBarIcon.ERROR, '温馨提示', '导出失败，请重试', self.window(), InfoBarPosition.TOP)

    # 导入站点：选择 JSON 文件，同名站点覆盖更新，其余新增
    def importWebsite(self):
        path, _ = QFileDialog.getOpenFileName(self.window(), '选择导入文件', '', '站点配置文件 (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '文件读取失败或格式错误', self.window(), InfoBarPosition.TOP)
            return
        # 兼容裸数组格式：{"sites":[...]} 或 [...] 均可
        sites = payload.get('sites') if isinstance(payload, dict) else payload
        if not isinstance(sites, list) or not sites:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '文件中没有可导入的站点', self.window(), InfoBarPosition.TOP)
            return
        inserted = 0
        updated = 0
        with SQLiteDatabase() as db:
            # 动态取表的所有合法列，过滤掉非法字段，兼容未来加列
            db.cursor.execute('PRAGMA table_info(comic_website)')
            valid_cols = {row[1] for row in db.cursor.fetchall()} - {'id'}
            for site in sites:
                if not isinstance(site, dict) or not site.get('name'):
                    continue
                data = {k: v for k, v in site.items() if k in valid_cols}
                if not data:
                    continue
                # 同名站点覆盖更新（与项目"不覆盖用户改过的站点"不同：导入是用户显式操作，按覆盖处理）
                if db.query_first_data('comic_website', {'name': site['name']}):
                    db.update_data('comic_website', data, {'name': site['name']})
                    updated += 1
                else:
                    db.insert_data('comic_website', data)
                    inserted += 1
        self.search(None)
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', f'导入完成：新增 {inserted} 个，覆盖更新 {updated} 个',
                 self.window(), InfoBarPosition.TOP)

    # 打开下载管理窗口（跨域站点的下载任务）
    def openDownloadManager(self):
        from view.website_download_manager import WebsiteDownloadManagerWindow
        # 单例：已打开则激活，否则新建并持有引用防 GC
        dm = getattr(self, '_downloadManager', None)
        if dm is None or not dm.isVisible():
            self._downloadManager = WebsiteDownloadManagerWindow(self.window())
            self._downloadManager.show()
        else:
            # 最小化时 raise_/activateWindow 不会取消最小化，需先恢复窗口状态
            if dm.isMinimized():
                dm.setWindowState(dm.windowState() & ~Qt.WindowMinimized)
            dm.raise_()
            dm.activateWindow()

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
                        cross_origin=website.cross_origin,
                        restore_algorithm=website.restore_algorithm,
                        chapter_order=website.chapter_order,
                        img_load_mode=website.img_load_mode,
                        next_page_selector=website.next_page_selector,
                        page_label_selector=website.page_label_selector,
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
        # 留 1px 余量，避免 AutoFlowLayout 换行判断把第 n 个卡片挤到下一行
        card_w = max(int((avail - (n - 1) * hs - 1) / n), 100)
        for i in range(self.flowLayout.count()):
            item = self.flowLayout.itemAt(i)
            if item and item.widget():
                item.widget().setFixedWidth(card_w)
        self.flowLayout.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layoutCards()


# 表单滚动区：sizeHint 高度跟随内容，对话框窗口够高时撑开全显示，窗口矮时压缩并内部滚动
class _FormScrollArea(ScrollArea):
    def sizeHint(self):
        w = super().sizeHint().width()
        h = self.widget().sizeHint().height() if self.widget() else super().sizeHint().height()
        return QSize(w, h)


# 站点新增/编辑对话框
class WebsiteEditDialog(MessageBoxBase):
    # (key, 标签, 控件类型, 是否必填, 默认值)  控件类型: line=文本框, check=复选框
    FIELDS = [
        ('name', '站点名称', 'line', True, ''),
        ('url', '站点地址', 'line', True, ''),
        ('icon', '站点图标地址', 'line', False, ''),
        ('comic_cover_dom', '漫画封面选择器', 'line', False, ''),
        ('comic_name_dom', '漫画名称选择器', 'line', True, ''),
        ('chapter_name_dom', '章节名称选择器', 'line', True, ''),
        ('chapter_link_dom', '章节链接选择器', 'line', True, ''),
        ('img_dom', '图片选择器（可选，留空取全部img）', 'line', False, ''),
        ('img_attr', '图片懒加载属性（如data-src，留空自动检测）', 'line', False, ''),
        ('img_script', 'iframe取图脚本（可选，用变量ifr，需return数组）', 'line', False, ''),
        ('use_frame', '是否用iframe加载（直连取不到图时勾选）', 'check', False, 0),
        ('cross_origin', '是否跨域（图片与站点不同域时勾选）', 'check', False, 0),
        ('restore_algorithm', '图片恢复算法', 'combo', False, '', [('无', ''), ('腐漫', '腐漫')]),
        ('chapter_order', '章节倒序（最新话在前，配合合并成卷）', 'check', False, 1),
        ('img_load_mode', '图片加载方式', 'combo', False, 2, [('滚动加载', 1), ('滚到底部加载', 2), ('下一页加载', 3)]),
        ('next_page_selector', '下一页按钮选择器（留空则点击图片右侧翻页；上下页同 class 时加 :eq(n) 取第 n 个，如 .pager:eq(2)）', 'line', False, ''),
        ('page_label_selector', '页码标签选择器（可选，指向 5/30 这类文本用于判断末页）', 'line', False, ''),
    ]

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.edits = {}
        self._labels = {}  # key -> BodyLabel，用于联动显隐
        data = data or {}
        form = QVBoxLayout()
        form.setSpacing(4)
        for field in self.FIELDS:
            key, label, ctype = field[0], field[1], field[2]
            required = field[3]
            default = field[4]
            options = field[5] if len(field) > 5 else None
            val = data.get(key, default)
            if ctype == 'check':
                cb = CheckBox(label, self)
                cb.setChecked(val in (1, '1', True))
                form.addWidget(cb)
                self.edits[key] = cb
            elif ctype == 'combo':
                lbl = BodyLabel(label, self)
                lbl.setFixedHeight(20)
                form.addWidget(lbl)
                self._labels[key] = lbl
                cb = ComboBox(self)
                for text, v in options:
                    cb.addItem(text, userData=v)
                idx = next((i for i in range(cb.count()) if cb.itemData(i) == val), 0)
                cb.setCurrentIndex(idx)
                form.addWidget(cb)
                self.edits[key] = cb
            else:
                title = label + (' *' if required else '（可选）')
                lbl = BodyLabel(title, self)
                lbl.setFixedHeight(20)
                form.addWidget(lbl)
                self._labels[key] = lbl
                edit = LineEdit(self)
                edit.setText(str(val) if val not in (None, '') else '')
                form.addWidget(edit)
                self.edits[key] = edit
        # 联动：图片加载方式=下一页加载(3)时才显示下一页按钮选择器/页码标签选择器
        self._toggle_load_mode_fields()
        self.edits['img_load_mode'].currentIndexChanged.connect(self._toggle_load_mode_fields)
        # 用滚动区包裹表单：主窗口高度不足时滚动，避免标题被挤压到输入框
        scroll = _FormScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget(self)
        containerLayout = QVBoxLayout(container)
        containerLayout.setContentsMargins(0, 0, 0, 0)
        containerLayout.addLayout(form)
        scroll.setWidget(container)
        scroll.enableTransparentBackground()
        self.viewLayout.addWidget(scroll)
        self.yesButton.setText('保存')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(560)

    def _toggle_load_mode_fields(self):
        """图片加载方式=下一页加载时才显示 next_page_selector/page_label_selector"""
        is_next = self.edits['img_load_mode'].currentData() == 3
        for k in ('next_page_selector', 'page_label_selector'):
            lbl = self._labels.get(k)
            w = self.edits.get(k)
            if lbl is not None:
                lbl.setVisible(is_next)
            if w is not None:
                w.setVisible(is_next)

    def validate(self):
        for field in self.FIELDS:
            key, label, ctype, required = field[0], field[1], field[2], field[3]
            if ctype == 'line' and required and not self.edits[key].text().strip():
                show_tip(InfoBarIcon.WARNING, '温馨提示', f'请填写{label}', self)
                return False
        return True

    def get_data(self):
        result = {}
        for field in self.FIELDS:
            key, ctype = field[0], field[2]
            w = self.edits[key]
            if ctype == 'check':
                result[key] = 1 if w.isChecked() else 0
            elif ctype == 'combo':
                result[key] = w.currentData()
            else:
                result[key] = w.text().strip()
        return result


# 站点导出选择对话框：勾选要导出的站点
class WebsiteExportDialog(MessageBoxBase):
    def __init__(self, websites, parent=None):
        super().__init__(parent)
        self.websites = websites
        self.checkboxes = []

        self.viewLayout.addWidget(BodyLabel('选择要导出的站点', self))

        # 全选
        self.selectAllCb = CheckBox('全选', self)
        self.selectAllCb.setChecked(True)
        self.selectAllCb.stateChanged.connect(self._toggle_all)
        self.viewLayout.addWidget(self.selectAllCb)

        # 站点列表（滚动，站点多时内部滚动避免对话框过高）
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedHeight(320)
        scroll.enableTransparentBackground()
        container = QWidget(self)
        vLayout = QVBoxLayout(container)
        vLayout.setContentsMargins(0, 0, 0, 0)
        vLayout.setSpacing(6)
        for w in websites:
            cb = CheckBox(w.name, self)
            cb.setChecked(True)
            self.checkboxes.append(cb)
            vLayout.addWidget(cb)
        vLayout.addStretch()
        scroll.setWidget(container)
        self.viewLayout.addWidget(scroll)

        self.yesButton.setText('导出')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(420)

    def _toggle_all(self, state):
        for cb in self.checkboxes:
            cb.setChecked(state == 2)

    def get_selected(self):
        return [self.websites[i] for i, cb in enumerate(self.checkboxes) if cb.isChecked()]


# 站点卡片
class WebsiteCard(ElevatedCardWidget):
    def __init__(self, id, name, icon, url, comic_cover_dom=None, comic_name_dom=None,
                 chapter_name_dom=None, chapter_link_dom=None, img_dom=None, use_frame=None,
                 cross_origin=None, restore_algorithm=None, chapter_order=None, img_load_mode=None, next_page_selector=None, page_label_selector=None,
                 img_attr=None, img_script=None, type=1, parent=None):
        super().__init__(parent)
        self.type = type
        self.site_id = id
        self.site_data = {
            'name': name, 'icon': icon, 'url': url,
            'comic_cover_dom': comic_cover_dom or '', 'comic_name_dom': comic_name_dom or '',
            'chapter_name_dom': chapter_name_dom or '', 'chapter_link_dom': chapter_link_dom or '',
            'img_dom': img_dom or '', 'use_frame': use_frame, 'cross_origin': cross_origin, 'restore_algorithm': restore_algorithm or '', 'chapter_order': chapter_order,
            'img_load_mode': img_load_mode, 'next_page_selector': next_page_selector or '',
            'page_label_selector': page_label_selector or '', 'img_attr': img_attr or '',
            'img_script': img_script or ''
        }

        self.iconWidget = QLabel(self)
        self.iconWidget.setScaledContents(True)  # 允许缩放
        self.iconWidget.setFixedSize(150, 55)
        self.load_image(icon)

        self._fullName = name
        self.titleLabel = BodyLabel(name, self)
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

        # 上下边距 8（原 10）：为两行名称留出空间（icon55+间距6+两行30≈91，边距8 内容94 可容）
        self.mainLayout.setContentsMargins(15, 8, 0, 8)
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
                                                  img_attr, img_script, use_frame, chapter_order,
                                                  img_load_mode, next_page_selector, page_label_selector, cross_origin, restore_algorithm)

        # 用于保存打开的新窗口实例
        self.new_windows = []

        self._elideTitle()

    def _elideTitle(self):
        """尽可能显示全名：一行放得下就一行；否则两行均衡切分（按字符中点，两行宽度接近、视觉对称）；
        超两行则第二行 … 省略。卡片高度恒定（setFixedHeight(110)），同一行高度一致。
        宽度按卡片几何推算（左列 ≈ 卡片宽 - 左边距15 - 右侧按钮列28 - 间距12），留 5px 余量避免贴边裁切。"""
        fm = self.titleLabel.fontMetrics()
        w = self.width() - 60
        if w <= 0:
            return
        full = self._fullName or ''
        if not full or fm.horizontalAdvance(full) <= w:
            self.titleLabel.setText(full)
            return
        # 两行均衡切分：按字符中点切，两行都 ≤ w 则全显示（视觉对称）
        mid = len(full) // 2
        line1, line2 = full[:mid], full[mid:]
        if fm.horizontalAdvance(line1) <= w and fm.horizontalAdvance(line2) <= w:
            self.titleLabel.setText(line1 + '\n' + line2)
            return
        # 超过两行：第一行逐字填满，第二行放得下则全显示，否则末尾 … 省略
        chars = list(full)
        n = len(chars)
        i = 0
        line1 = ''
        while i < n and fm.horizontalAdvance(line1 + chars[i]) <= w:
            line1 += chars[i]
            i += 1
        if not line1:
            # 兜底：极窄宽度下单行省略
            self.titleLabel.setText(fm.elidedText(full, Qt.ElideRight, w))
            return
        rest = full[i:]
        ell = '…'
        if fm.horizontalAdvance(rest) <= w:
            line2 = rest
        else:
            ellw = fm.horizontalAdvance(ell)
            line2 = ''
            j = 0
            m = len(rest)
            while j < m and fm.horizontalAdvance(line2 + rest[j]) + ellw <= w:
                line2 += rest[j]
                j += 1
            line2 += ell
        self.titleLabel.setText(line1 + '\n' + line2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elideTitle()

    # 编辑站点
    def editWebsite(self):
        win = self.window()
        site_id = self.site_id
        dlg = WebsiteEditDialog(content_parent(win), self.site_data)
        def _on_accepted():
            with SQLiteDatabase() as db:
                db.update_data('comic_website', dlg.get_data(), {'id': site_id})
            # 卡片可能已被新搜索重建（弹窗开着时在搜索框输入触发 takeAllWidgets），此时 refresh 无意义
            try:
                self.refresh()
            except RuntimeError:
                pass
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '修改成功', win, InfoBarPosition.TOP)
        dlg.accepted.connect(_on_accepted)
        present_detail_dialog(dlg)

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
                   img_dom, img_attr, img_script, use_frame, chapter_order,
                   img_load_mode, next_page_selector, page_label_selector, cross_origin, restore_algorithm, event):
        try:
            window = Browser(url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                             img_dom, img_attr, img_script, use_frame, chapter_order,
                             img_load_mode, next_page_selector, page_label_selector, cross_origin, restore_algorithm)
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


class _FrameFetchWorker(QObject):
    """iframe 取图工作单元：一个 QWebEngineView 串行处理队列中的章节。

    多个 worker 并发即多窗口并发取图（数量=下载线程数）。每个 worker 独立 page，
    window._fetchResult 互不串话。完成后回调 browser._on_worker_extracted(self, data)。
    QWebEngineView 必须在主线程，故走 Qt 事件循环（runJavaScript 回调 + QTimer）协作式并发。
    """

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.view = QWebEngineView(browser)
        self.view.setWindowTitle('章节取图（自动关闭，请勿关闭）')
        self.view.resize(900, 700)
        # 去掉关闭按钮，禁止用户交互（仅标题栏+最小化）
        self.view.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint)
        # 关闭取图窗口不应触发应用退出（与主窗口退出隔离）
        self.view.setAttribute(Qt.WA_QuitOnClose, False)
        self.view.loadFinished.connect(self._on_loaded)
        # 防抖定时器：章节页若有客户端重定向(loadFinished 多次触发)，等稳定后再提取
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._extract)
        try:
            self.view.page().setBackgroundColor(QColor('#1a1a1a'))
        except Exception:
            pass
        # 拦截窗口移动事件：拖动一个取图窗口时其他窗口跟随（Browser.eventFilter 处理）
        self.view.installEventFilter(browser)
        # 取图遮罩：独立半透明置顶窗口覆盖客户区，阻止用户操作页面（从打开到关闭全程在位）
        self.mask = QWidget(self.view, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.mask.setAttribute(Qt.WA_QuitOnClose, False)
        self.mask.setStyleSheet('background: rgba(26,26,26,0.85);')
        _ml = QVBoxLayout(self.mask)
        _ml.setContentsMargins(0, 0, 0, 0)
        _lbl = QLabel('正在取图，请勿操作...')
        _lbl.setStyleSheet('color:#ffffff;font-size:22px;font-family:sans-serif;')
        _lbl.setAlignment(Qt.AlignCenter)
        _ml.addWidget(_lbl)
        # worker 自身作 eventFilter：view 移动/缩放/显示时蒙版跟随对齐（browser 拖动跟随 filter 不受影响）
        self.view.installEventFilter(self)
        # 贴主窗口右上角（多窗口同一位置重叠）
        try:
            g = browser.frameGeometry()
            self.view.move(g.x() + g.width() - self.view.width(), g.y())
        except Exception:
            pass
        self.cur = None
        self.poll = 0

    def fetch(self, item):
        """加载一个章节页并取图，完成后回调 browser._on_worker_extracted"""
        self.cur = item
        self.poll = 0
        self.view.show()
        self.mask.show()
        self._align_mask()
        logging.info(f'[站点下载] 取图窗口加载: {item["chapter_name"]} | {item["link"]}')
        try:
            self.view.load(QUrl(item['link']))
        except Exception:
            logging.info('[站点下载] 取图窗口加载异常: ' + traceback.format_exc())
            self.browser._on_worker_extracted(self, {'comic_name': item['comic_name'], 'chapter_name': item['chapter_name'],
                                                      'imgs': [], 'note': '取图窗口加载异常'})

    def _align_mask(self):
        """遮罩窗口对齐覆盖取图窗口的客户区（留出标题栏）"""
        if self.view is not None and getattr(self, 'mask', None) is not None:
            try:
                self.mask.setGeometry(self.view.geometry())
                self.mask.raise_()
                self.mask.show()
            except Exception:
                pass

    def eventFilter(self, obj, event):
        # 取图窗口移动/缩放/显示时蒙版跟随对齐；最小化(Hide)时隐藏蒙版避免悬浮
        if obj is self.view:
            t = event.type()
            if t in (QEvent.Move, QEvent.Resize, QEvent.Show):
                self._align_mask()
            elif t == QEvent.Hide and getattr(self, 'mask', None) is not None:
                try:
                    self.mask.hide()
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def _on_loaded(self, ok):
        if self.view is None:
            return
        # 跳过初始蒙版页（about:blank 等非 http），只处理章节页
        url = self.view.url().toString()
        if not url.startswith('http'):
            return
        item = self.cur
        if not item:
            return
        if not ok:
            logging.info(f'[站点下载] 取图窗口加载失败: {item["chapter_name"]}')
            self.browser._on_worker_extracted(self, {'comic_name': item['comic_name'], 'chapter_name': item['chapter_name'],
                                                      'imgs': [], 'note': '取图窗口加载失败'})
            return
        # 防抖：每次 loadFinished 都重启定时器，等页面稳定(无重定向)后再提取
        self.timer.start(1500)

    def _extract(self):
        if self.view is None or not self.cur:
            return
        item = self.cur
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
            note += ' | 滚动诊断: ' + (window._scrollDiag || '无');
            window._fetchResult = JSON.stringify({ 'comic_name': META.comic_name, 'chapter_name': META.chapter_name, 'imgs': imgs, 'note': note, 'chapter_link': META.chapter_link });
        })();
        """
        self.view.page().runJavaScript(js_code)
        self.poll = 0
        self._poll()

    def _poll(self):
        if self.view is None:
            return
        self.poll += 1
        self.view.page().runJavaScript('window._fetchResult', self._on_poll)

    def _on_poll(self, result):
        if result:
            # 读到结果，清空全局，解析
            self.view.page().runJavaScript('window._fetchResult = null')
            import json as _json
            try:
                data = _json.loads(result) if isinstance(result, str) else result
            except Exception:
                logging.info(f'[站点下载] 提取回调JSON解析失败: {str(result)[:200]}')
                data = None
            logging.info(f'[站点下载] 提取回调原始: {str(data)[:200]}')
            self.browser._on_worker_extracted(self, data)
        elif self.poll < 12000:  # 下一页模式页数可能上百，每页含翻页等待+图片加载，给600s轮询
            QTimer.singleShot(500, self._poll)
        else:
            logging.info('[站点下载] 提取超时(600s)未拿到结果')
            self.browser._on_worker_extracted(self, None)

    def close(self):
        """取图完成/失败时关闭并清理本窗口"""
        try:
            self.timer.stop()
        except Exception:
            pass
        if self.view is not None:
            try:
                self.view.loadFinished.disconnect()
            except Exception:
                pass
            try:
                self.view.close()
                self.view.deleteLater()
            except Exception:
                pass
            self.view = None
        # 关闭并清理遮罩窗口
        if getattr(self, 'mask', None) is not None:
            try:
                self.mask.close()
                self.mask.deleteLater()
            except Exception:
                pass
            self.mask = None


class _CrossDownloadWorker(QObject):
    """跨域单章图片下载：浏览器加载章节页建立会话(cookie/JS/Cloudflare) -> 提取 cookie -> httpx 并发下载。

    每章一份独立 profile/view/cookies，多 worker 并发不串话（替代原 Browser 共享的 self._cross_*）。
    为何不用 a.click()+downloadRequested：a.download 对跨域资源被 Chromium 忽略、图片会变成页面导航；
    且 runJavaScript 触发的 a.click() 无用户手势，Chromium 拦截无手势的跨域下载。故浏览器仅用于建会话，取图仍交 httpx。
    """

    progress = pyqtSignal(int, int)   # (done, total) 当前章节图片粒度进度
    success = pyqtSignal(str)         # comic_name（章节下载完成）

    def __init__(self, browser, comic_name, chapter_name, urls, referer, restore_algorithm):
        super().__init__(browser)
        self.browser = browser
        self.comic_name = comic_name
        self.chapter_name = chapter_name
        self.urls = urls
        self.referer = referer
        self.restore_algorithm = restore_algorithm
        self.cookies = {}        # 浏览器加载章节页过程收集到的 cookie（name -> value）
        self.done = 0
        self.total = len(urls)
        self.profile = None
        self.page = None
        self.view = None
        self._dl = None          # ComicWebsiteChapterImages 引用（自持防 GC）

    def start(self):
        if not self.urls:
            # 0 图片章节：不建会话、不建目录，直接完成（与 0 图片兜底一致，避免 epub 合并空目录崩溃）
            self.success.emit(self.comic_name)
            return
        # 独立 profile 加载章节页建立会话；cookieAdded 收集全部 cookie（含 JS 设置的）
        self.profile = QWebEngineProfile(self.browser)
        self.profile.cookieStore().cookieAdded.connect(self._on_cookie)
        self.page = QWebEnginePage(self.profile, self.browser)
        self.view = QWebEngineView(self.browser)
        self.view.setPage(self.page)
        # QtWebEngine 需 widget 进入事件循环才会触发 load，用最小化窗口承载（不干扰用户），关闭不触发应用退出
        self.view.setWindowTitle('跨域图片下载（自动，请勿关闭）')
        self.view.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint)
        self.view.setAttribute(Qt.WA_QuitOnClose, False)
        self.view.resize(400, 300)
        self.view.showMinimized()
        # 加载章节页建立 cookie/referer，加载完成后提取 cookie 转 httpx 下载
        self.view.load(QUrl(self.referer))
        self.view.loadFinished.connect(self._on_loaded)

    def _on_cookie(self, cookie):
        """收集 cookieAdded 信号：浏览器加载章节页过程设置的全部 cookie（name -> value）。"""
        try:
            name = bytes(cookie.name()).decode('utf-8', 'ignore')
            value = bytes(cookie.value()).decode('utf-8', 'ignore')
            if name:
                self.cookies[name] = value
        except Exception:
            pass

    def _on_loaded(self, ok):
        # 章节页加载完成，cookie 已在 _on_cookie 收集；断开信号避免重定向多次触发
        try:
            self.view.loadFinished.disconnect(self._on_loaded)
        except Exception:
            pass
        # 兜底：loadAllCookies 重新枚举存储中全部 cookie（捕获 loadFinished 前已设置但信号未到的）
        try:
            self.profile.cookieStore().loadAllCookies()
        except Exception:
            pass
        # 留 500ms 让 cookieAdded 信号 + JS 设置的 cookie 落定，再开 httpx 下载
        QTimer.singleShot(500, self._start_download)

    def _start_download(self):
        logging.info(f'[站点下载] 跨域会话 cookie 提取完成({len(self.cookies)}条)，转 httpx 下载 {len(self.urls)} 张图片 | 章节: {self.chapter_name}')
        # cookie 已提取，浏览器视图不再需要，立即释放
        self._cleanup_view()
        self.done = 0
        self.total = len(self.urls)
        # 复用同域 httpx 下载线程（10 次重试 + restore_image + 文件名规则一致），带 cookie + referer
        # 跨域走显式代理（Windows 系统代理，与浏览器同源），None=无系统代理则直连
        self._dl = ComicWebsiteChapterImages(
            comic_name=self.comic_name, chapter_name=self.chapter_name, chapter_images=self.urls,
            referer=self.referer, cookies=self.cookies, restore_algorithm=self.restore_algorithm,
            proxy=get_system_proxy(), cross_origin=True)
        self._dl.progress.connect(self._on_img_progress)
        self._dl.success.connect(self._on_dl_success)
        self._dl.finished.connect(self._on_dl_finished)
        self._dl.start()

    def _on_img_progress(self, done, total):
        # 当前章节图片粒度进度
        self.done = done
        self.total = total
        self.progress.emit(done, total)

    def _on_dl_success(self, comic_name):
        self.success.emit(comic_name)

    def _on_dl_finished(self):
        # QThread 真正结束，丢弃引用
        self._dl = None

    def _cleanup_view(self):
        for attr in ('view', 'page', 'profile'):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.deleteLater()
                except Exception:
                    pass
        self.view = None
        self.page = None
        self.profile = None

    def cleanup(self):
        """整体清理（完成/中断）：仅清浏览器视图。
        _dl 由 QThread.finished(_on_dl_finished) 释放，不在此时清--success 早于 finished，
        过早丢引用会让未结束的下载线程被 GC（segfault）。"""
        self._cleanup_view()


class Browser(QMainWindow):
    # 下载管理（隐藏 Browser）触发下载时回传进度/完成/失败（task_id, ...）
    progress = pyqtSignal(object, int)    # task_id, process(0-100)
    finished = pyqtSignal(object, str)    # task_id, path
    failed = pyqtSignal(object)           # task_id

    def __init__(self, url, comic_cover_dom, comic_name_dom, chapter_name_dom, chapter_link_dom,
                 img_dom, img_attr=None, img_script=None, use_frame=None, chapter_order=None,
                 img_load_mode=None, next_page_selector=None, page_label_selector=None,
                 cross_origin=None, restore_algorithm=None, hidden=False, task_id=None):
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
            self.chapter_order = chapter_order
            self.img_load_mode = img_load_mode
            self.next_page_selector = (next_page_selector or '').strip()
            self.page_label_selector = (page_label_selector or '').strip()
            self.cross_origin = cross_origin or 0
            self.restore_algorithm = restore_algorithm or ''
            self.hidden = hidden
            self.task_id = task_id
            self.browser = BrowserView()
            self.setCentralWidget(self.browser)

            self.checked_chapters = []
            # iframe 模式专用：取图 worker 池（多窗口并发，数量=下载线程数）
            self._fetch_queue = []
            self._fetch_workers = []     # 所有创建的取图 worker（用于清理）
            self._idle_workers = []      # 空闲 worker（可复用，避免反复起停渲染进程）
            self._busy_workers = []      # 正在取图的 worker
            self._max_fetchers = 1       # 并发取图窗口数（launch_iframes 按下载线程数设置）
            # 跨域下图 worker 列表（每章一个，并发下图，进度聚合）
            self._cross_workers = []
            # 同域图片下载线程引用集（并发时防单引用被覆盖丢引用 -> GC segfault）
            self._chapter_image_threads = set()
            # 章节细分进度（隐藏/下载管理模式）：总章节数下载前已知，避免按图片总数会回退
            self._total_chapters = 0
            self._completed_chapters = 0
            self._syncing_fetchers = False  # 取图窗口跟随移动防递归标志

            # 创建悬浮按钮
            # 下载按钮
            if not self.hidden and chapter_name_dom is not None and chapter_name_dom != 'None' and chapter_name_dom != '':
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

            if not self.hidden:
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

    def get_site_config(self):
        """返回当前站点配置快照（供下载管理保存任务，下载时按此取图）"""
        return {
            'img_dom': self.img_dom, 'use_frame': self.use_frame, 'cross_origin': self.cross_origin,
            'restore_algorithm': self.restore_algorithm,
            'chapter_order': self.chapter_order, 'img_load_mode': self.img_load_mode,
            'next_page_selector': self.next_page_selector, 'page_label_selector': self.page_label_selector,
            'img_attr': self.img_attr, 'img_script': self.img_script,
        }

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

    def downloadComic(self, result, checked_chapters, task_id=None):
        if task_id is not None:
            self.task_id = task_id
        # 是否合并成卷
        isMergeChapte = cfg.get(cfg.isMergeChapte)
        if isMergeChapte:
            # 清空漫画目录
            download_folder = cfg.get(cfg.downloadFolder)
            path = f"{download_folder}/{result['comic_name']}"
            del_folder(path)

        if not self.hidden:
            self.stateTooltip.setContent('请耐心等待~~')
        with SQLiteDatabase() as db:
            db.delete_data('website_download_record', {'comic_name': result['comic_name']})
            db.insert_data('website_download_record',
                           {'comic_name': result['comic_name'], 'chapter_num': len(checked_chapters),
                            'downloaded_num': 0, 'downloading_num': 0, 'is_update': 0,
                            'start_time': get_current_time()})

        self.checked_chapters = checked_chapters
        # 章节细分进度：总章节数下载前已知（=选中章节数），当前章节图片进度实时回传、封顶99%、epub100
        self._total_chapters = len(checked_chapters)
        self._completed_chapters = 0
        # 按站点章节顺序配置决定是否倒序（倒序=章节阅读顺序，站点章节多为倒序排列；0=顺序）
        if self.chapter_order != 0:
            self.checked_chapters.reverse()
        for _i, _c in enumerate(self.checked_chapters):
            _c['_order'] = _i + 1
        self.launch_iframes(result['comic_name'])

    def launch_iframes(self, comic_name):
        # 获取最大线程配置（同域/跨域均按此并发；跨域下图已封装为每章独立 _CrossDownloadWorker，
        # 不再有共享 _cross_* 串行状态，故不再强制串行）
        downloadThreadNum = cfg.get(cfg.downloadThreadNum)
        self._max_fetchers = downloadThreadNum

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

    def _build_next_page_js(self, map_expr, _json):
        """下一页加载取图 JS：点击下一页按钮(配了选择器)或点图片右侧翻页，逐页提取去重，末尾 return collected。
        整页导航(URL 翻页)站点：collected 经 window.name 跨页持久化，点下一页触发导航后脚本随页面卸载销毁，
        新页 loadFinished 重新 _extract 读 window.name 续取；SPA 路由(URL 变不卸载)等 500ms 后继续提取。
        末页判断：①按钮不可用 ②页码标签 当前≥总数 ③无新图且URL未变 ④999页安全阀。"""
        btn_sel = self.next_page_selector
        label_sel = self.page_label_selector
        filter_js = ("s && s.indexOf('logo')===-1 && s.indexOf('load.gif')===-1 "
                     "&& s.indexOf('blank')===-1 && s.indexOf('data:image')===-1 && s.indexOf('placeholder')===-1")
        js = (
            "var btnSel = " + _json.dumps(btn_sel) + ", labelSel = " + _json.dumps(label_sel) + "; "
            "var collected = [], seen = {}; "
            "try { var saved = (window.name && window.name.charAt(0)==='{') ? JSON.parse(window.name) : null; "
            "  if (saved && saved.chap === META.chapter_link && Array.isArray(saved.collected)) { "
            "    collected = saved.collected.slice(); collected.forEach(function(u){ seen[u]=1; }); "
            "  } } catch(e) {} "
            "function saveName(){ try { window.name = JSON.stringify({chap: META.chapter_link, collected: collected}); } catch(e) {} } "
            "function good(s){ return " + filter_js + "; } "
            "function pickEl(sel){ "
            "  if(!sel) return null; "
            "  var m = sel.match(/:eq\\((\\d+)\\)\\s*$/); "
            "  try{ "
            "    if(m){ var idx=parseInt(m[1]); var base=sel.slice(0,m.index); var all=doc?doc.querySelectorAll(base):[]; return (idx>=1 && idx<=all.length)?all[idx-1]:null; } "
            "    return doc ? doc.querySelector(sel) : null; "
            "  }catch(e){ return null; } "
            "} "
            "function pageImgs(){ "
            "  var nodes = doc ? doc.querySelectorAll(sel) : []; "
            "  return Array.from(nodes).map(function(im){ return " + map_expr + "; }).filter(good); "
            "} "
            "function addFresh(){ pageImgs().forEach(function(u){ if(!seen[u]){seen[u]=1;collected.push(u);} }); saveName(); } "
            "function parseLabel(){ "
            "  if(!labelSel) return null; "
            "  var el = pickEl(labelSel); if(!el) return null; "
            "  var t = el.textContent || ''; "
            "  var m = t.match(/(\\d+)\\D+(\\d+)/); "
            "  return m ? [parseInt(m[1]), parseInt(m[2])] : null; "
            "} "
            "function goNext(){ "
            "  if(btnSel){ "
            "    var btn = pickEl(btnSel); "
            "    if(!btn || btn.disabled) return false; "
            "    var cls=(typeof btn.className==='string'?btn.className:'')+' '+(btn.getAttribute('class')||''); "
            "    if(/disabled|inactive|noreply|hide/i.test(cls)) return false; "
            "    if(btn.getAttribute('aria-disabled')==='true') return false; "
            "    try{ "
            "      var href = btn.tagName==='A' ? btn.getAttribute('href') : null; "
            "      if(href && href.charAt(0)!=='#' && href.indexOf('javascript:')!==0){ location.href = btn.href; } "
            "      else { "
            "        var r = btn.getBoundingClientRect(); "
            "        var cx = r.left + r.width/2, cy = r.top + r.height/2; "
            "        ['mousedown','mouseup','click'].forEach(function(t){ "
            "          btn.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window, clientX:cx, clientY:cy})); "
            "        }); "
            "      } "
            "    }catch(e){return false;} "
            "    return true; "
            "  } "
            "  var main=null, maxA=0; "
            "  Array.from(doc ? doc.querySelectorAll('img') : []).forEach(function(im){ "
            "    var r=im.getBoundingClientRect(); var a=r.width*r.height; "
            "    if(a>maxA && a>10000){maxA=a;main=im;} "
            "  }); "
            "  if(!main) return false; "
            "  var r=main.getBoundingClientRect(); "
            "  var x=r.left+r.width*0.75, y=r.top+r.height*0.5; "
            "  var el=doc.elementFromPoint(x,y)||main; "
            "  ['mousedown','mouseup','click'].forEach(function(t){ "
            "    el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:x,clientY:y})); "
            "  }); "
            "  return true; "
            "} "
            "function waitImgs(){ "
            "  var pendings=[]; "
            "  (doc ? doc.querySelectorAll('img') : []).forEach(function(im){ "
            "    if(!im.complete && im.src) pendings.push(new Promise(function(res){im.onload=im.onerror=function(){res();};setTimeout(res,5000);})); "
            "  }); "
            "  return pendings.length ? Promise.all(pendings) : Promise.resolve(); "
            "} "
            "if (doc && doc.defaultView) { "
            "  var pages = 0; "
            "  var noNewCount = 0; "
            "  var diag = []; "
            "  var reason = 'unknown'; "
            "  addFresh(); "
            "  while(pages < 999){ "
            "    pages++; "
            "    var gn = goNext(); "
            "    var btnInfo = '点图右'; "
            "    if(btnSel){ var b = pickEl(btnSel); btnInfo = b ? ('dis=' + !!b.disabled + ' tag=' + b.tagName + ' cls=' + String(b.className||'').slice(0,24) + ' href=' + String(b.getAttribute('href')||'').slice(0,30)) : '无按钮'; } "
            "    if(!gn){ reason='goNext失败[' + btnInfo + ']'; break; } "
            "    var lab = parseLabel(); "
            "    if(lab && lab[0] >= lab[1]){ reason='页码标签末页 ' + lab[0] + '/' + lab[1]; break; } "
            "    var beforeUrl = location.href, beforeCnt = collected.length, beforeImgs = doc.querySelectorAll('img').length; "
            "    var waited=0; "
            "    while(waited<2500){ await new Promise(function(r){setTimeout(r,100);}); waited+=100; "
            "      if(doc.querySelectorAll('img').length!==beforeImgs || location.href!==beforeUrl) break; "
            "    } "
            "    if(location.href !== beforeUrl){ "
            "      await new Promise(function(r){ setTimeout(r, 500); }); "
            "    } "
            "    await waitImgs(); "
            "    addFresh(); "
            "    var urlChg = location.href !== beforeUrl; "
            "    var added = collected.length - beforeCnt; "
            "    diag.push('p'+pages+' '+btnInfo+' wait='+waited+'ms imgs'+beforeImgs+'->'+doc.querySelectorAll('img').length+' +'+added+' urlChg='+urlChg+(lab?(' lab='+lab[0]+'/'+lab[1]):'')+' tail='+location.href.slice(-45)); "
            "    if(collected.length===beforeCnt && !urlChg){ "
            "      noNewCount++; "
            "      if(lab && lab[0] < lab[1] && noNewCount < 3){ continue; } "
            "      reason='无新图且URL未变 x'+noNewCount; break; "
            "    } "
            "    noNewCount = 0; "
            "  } "
            "  if(pages>=999) reason='达999安全阀'; "
            "  window._scrollDiag = 'mode=next_page pages='+pages+' reason='+reason+' 图片数='+collected.length+' || ' + diag.join(' | '); "
            "} "
            "try { window.name = ''; } catch(e) {} "
            "return collected; "
        )
        return js, False

    def _add_iframe_frame(self, comic_name, chapter):
        # iframe 模式（use_frame=1）：用独立 QWebEngineView 窗口加载章节页
        # 独立窗口是顶级窗口 top===self，frame-bust 的 top!==self 判断不成立，不会跳转主页面
        import json as _json
        # 取图函数体 = 滚动到底部触发懒加载（配置开启时） + 取图（img_script 或 DOM 提取）
        img_dom = self.img_dom or 'img'
        if self.img_attr:
            map_expr = "im.getAttribute(" + _json.dumps(self.img_attr) + ") || im.src"
        else:
            map_expr = ("im.dataset.src || im.dataset.original || im.dataset.url "
                        "|| im.dataset.lazySrc || im.dataset.originalSrc || im.src")
        # 图片加载方式：1=滚动加载 2=滚到底部加载 3=下一页加载
        load_mode = self.img_load_mode or 2
        logging.info(f'[站点下载] 取图模式: img_load_mode={self.img_load_mode!r} load_mode={load_mode} use_frame={bool(self.use_frame)} img_dom={self.img_dom!r}')
        need_extract = True
        if load_mode == 3:
            # 下一页加载：点击下一页按钮(配了选择器)或点图片右侧翻页，逐页提取去重（自带 return）
            load_js, need_extract = self._build_next_page_js(map_expr, _json)
        else:
            # 滚动触发懒加载；mode 2 须到底且数量稳定，mode 1 只需数量稳定
            if load_mode == 2:
                # 到底后数量连续 5 次不变才停
                term_js = "if (atBottom) { if (cnt === lastCnt) { stable++; if (stable >= 5) break; } else { stable = 0; } } else { stable = 0; }"
                mode_label = "scroll"
                step_expr = "Math.max(vw.innerHeight - 50, 300)"
            else:
                # 数量连续 5 次不变即停（不要求到底）
                term_js = "if (cnt === lastCnt) { stable++; if (stable >= 5) break; } else { stable = 0; }"
                mode_label = "stable"
                step_expr = "500"
            load_js = (
                "if (doc && doc.defaultView) { "
                "  var vw = doc.defaultView, lastCnt = -1, stable = 0, attempts = 0; "
                "  while (attempts < 200) { "
                "    attempts++; var cnt = doc.querySelectorAll('img').length; "
                "    var h = doc.body ? doc.body.scrollHeight : 0; "
                "    var atBottom = vw.innerHeight + vw.scrollY >= h - 5; "
                "    " + term_js + " "
                "    lastCnt = cnt; "
                "    for (var w = 0; w < 6; w++) { try { document.documentElement.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true })); } catch(e){} } "
                "    vw.scrollBy(0, " + step_expr + "); "
                "    await new Promise(function(r){ setTimeout(r, 400); }); "
                "    var pendings = []; "
                "    doc.querySelectorAll('img').forEach(function(im){ "
                "      if (!im.complete && im.src) { "
                "        pendings.push(new Promise(function(res){ im.onload = im.onerror = function(){ res(); }; setTimeout(res, 5000); })); "
                "      } "
                "    }); "
                "    if (pendings.length) await Promise.all(pendings); "
                "  } "
                "  window._scrollDiag = 'mode=" + mode_label + " attempts=' + attempts + ' stable=' + stable + ' atBottom=' + (vw.innerHeight + vw.scrollY >= (doc.body ? doc.body.scrollHeight : 0) - 5) + ' 图片数=' + doc.querySelectorAll('img').length; "
                "} "
            )
        # 取图：mode3 自带提取去重+return；mode1/2 用 img_script 或 DOM 提取
        if not need_extract:
            extract_js = ""
        elif self.img_script:
            extract_js = self.img_script
        else:
            extract_js = (
                "var nodes = doc ? doc.querySelectorAll(sel) : []; "
                "return Array.from(nodes).map(function(im){ return " + map_expr + "; })"
                ".filter(function(s){ return s && s.indexOf('logo')===-1 && s.indexOf('load.gif')===-1 "
                "&& s.indexOf('blank')===-1 && s.indexOf('data:image')===-1 && s.indexOf('placeholder')===-1; });"
            )
        body = (
            "var doc = ifr.contentDocument; var sel = " + _json.dumps(img_dom) + "; "
            + load_js + extract_js
        )
        meta = _json.dumps({'comic_name': comic_name, 'chapter_name': chapter['name'], 'chapter_link': chapter['link']})
        # 入队，由取图 worker 池并发处理（数量=下载线程数）
        self._fetch_queue.append({'link': chapter['link'], 'body': body, 'meta': meta,
                                  'comic_name': comic_name, 'chapter_name': chapter['name']})
        self._pump_fetchers()

    def _pump_fetchers(self):
        """派发队列中的章节到空闲取图 worker，最多并发 _max_fetchers 个；全部取图完成则关闭所有 worker。

        worker 复用：章节取图完成后归还空闲池，下一章直接复用，避免反复起停渲染进程。
        关闭时机：队列空 + 无在取 worker + checked_chapters 空（无更多章节将入队），此时下载仍异步进行。
        """
        while self._fetch_queue and len(self._busy_workers) < self._max_fetchers:
            item = self._fetch_queue.pop(0)
            if self._idle_workers:
                worker = self._idle_workers.pop()
            else:
                worker = _FrameFetchWorker(self)
                self._fetch_workers.append(worker)
            self._busy_workers.append(worker)
            worker.fetch(item)
        # 队列空 + 无在取 worker + 无待取章节 => 取图全部完成，关闭所有 worker（下载仍异步进行）
        if not self._fetch_queue and not self._busy_workers and not self.checked_chapters:
            self._close_all_fetchers()

    def _on_worker_extracted(self, worker, data):
        """单个取图 worker 完成一章：启动该章下载，归还 worker 并派发下一章。"""
        if worker in self._busy_workers:
            self._busy_workers.remove(worker)
        self._idle_workers.append(worker)
        self._on_frame_images(data)
        self._pump_fetchers()

    def _close_all_fetchers(self):
        """取图完成/失败时关闭并清理所有取图 worker"""
        for worker in self._fetch_workers:
            worker.close()
        self._fetch_workers.clear()
        self._idle_workers.clear()
        self._busy_workers.clear()
        logging.info('[站点下载] 取图窗口已全部关闭')

    def eventFilter(self, obj, event):
        # 取图窗口被拖动时，其他取图窗口跟随移动（保持重叠同一位置）
        if event.type() == QEvent.Move and not self._syncing_fetchers:
            for w in self._fetch_workers:
                if w.view is obj:
                    self._syncing_fetchers = True
                    try:
                        delta = event.pos() - event.oldPos()
                        for w2 in self._fetch_workers:
                            if w2.view is not None and w2.view is not obj:
                                w2.view.move(w2.view.pos() + delta)
                    except Exception:
                        pass
                    self._syncing_fetchers = False
                    break
        return super().eventFilter(obj, event)

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
        if img_count == 0:
            # 未提取到图片：记日志并推进进度，不再无限重试避免卡死
            logging.info(f'[站点下载] 未提取到图片，跳过该章节: {chapter_name}')
            self.downloadComicStatus(comic_name)
            return
        if self.cross_origin == 1:
            # 跨域：每章一个 _CrossDownloadWorker（自带 cookie 会话 + httpx），多章并发下图不串话
            bad = ('logo', 'data:image', 'blank', 'placeholder', 'loading.gif', 'load.gif', 'favicon')
            urls = [deal_url(u) for u in imgs if u and not any(b in u.lower() for b in bad)]
            if not urls:
                # 0 图片章节：不建会话、不建目录，直接推进（与 0 图片兜底一致，避免 epub 合并空目录崩溃）
                self.downloadComicStatus(comic_name)
                return
            worker = _CrossDownloadWorker(self, comic_name, chapter_name, urls,
                                           referer or self.url, self.restore_algorithm)
            worker.progress.connect(self._on_cross_progress)
            worker.success.connect(lambda cn=comic_name, w=worker: self._on_cross_worker_done(w, cn))
            self._cross_workers.append(worker)
            worker.start()
        else:
            # 同域：httpx 并发下载；引用集持有防并发覆盖丢引用 -> GC segfault
            cwci = ComicWebsiteChapterImages(comic_name=comic_name,
                                             chapter_name=chapter_name,
                                             chapter_images=imgs,
                                             referer=referer,
                                             restore_algorithm=self.restore_algorithm)
            cwci.success.connect(self.downloadComicStatus)
            cwci.finished.connect(lambda t=cwci: self._chapter_image_threads.discard(t))
            self._chapter_image_threads.add(cwci)
            cwci.start()

    def _on_cross_progress(self, done, total):
        # 跨域下图 worker 图片粒度进度：触发聚合重算（worker 已自存 done/total）
        self._emit_progress()

    def _on_cross_worker_done(self, worker, comic_name):
        # 跨域单章下图完成：移出在途列表（其 frac 不再计入聚合）并推进章节进度
        if worker in self._cross_workers:
            self._cross_workers.remove(worker)
        worker.cleanup()
        self.downloadComicStatus(comic_name)

    def _emit_progress(self):
        """实时进度（隐藏/下载管理模式）：(已完成章节 + Σ 各在途 worker 图片进度) / 总章节数 * 100，封顶99%。
        epub 合并完成才 100%。每张图下载完实时回传，进度单调递增不回退（总章节数下载前已知，
        避免按图片总数逐章累计会回退的问题）。worker 完成后移出 _cross_workers，其 frac(=1.0)
        由 completed(+1) 顶替，边界等价、不回退。"""
        if not self.hidden or self.task_id is None:
            return
        total = getattr(self, '_total_chapters', 0) or 1
        completed = getattr(self, '_completed_chapters', 0)
        # 聚合所有在途跨域 worker 的图片进度（每章 done/total 求和）
        frac = 0.0
        for w in self._cross_workers:
            if w.total:
                frac += w.done / w.total
        progress = min(int((completed + frac) / total * 100), 99)
        try:
            with SQLiteDatabase() as db:
                db.update_data('website_chapter_download', {'process': progress}, {'id': self.task_id})
        except Exception:
            logging.info('更新下载进度失败: ' + traceback.format_exc())
        self.progress.emit(self.task_id, progress)

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
        if self.hidden:
            # 下载管理（隐藏/跨域）：章节细分进度。该章 worker 已在 _on_cross_worker_done 移出在途列表，
            # 其 frac 不再计入聚合；此处计入已完成并刷新进度（completed/total，章节边界）。
            # 图片粒度实时进度由 _on_cross_progress（httpx 每张下完）的 _emit_progress 负责。
            self._completed_chapters = (getattr(self, '_completed_chapters', 0)) + 1
            self._emit_progress()
            logging.info(f'[站点下载] 章节完成: {self._completed_chapters}/{getattr(self, "_total_chapters", 0)}')
        else:
            # 同域（非隐藏）：保持章节维度进度（stateTooltip），不动同域路径
            progress = int(record.downloaded_num / record.chapter_num * 100) if record.chapter_num else 0
            logging.info(f'[站点下载] 进度: {record.downloaded_num}/{record.chapter_num} ({progress}%)')
        if record.chapter_num == record.downloaded_num:
            logging.info(f'[站点下载] 全部章节下载完成，开始合并epub: {comic_name}')
            # 下载完成合并epub
            # 先根据配置合并卷目录
            isMergeChapte = cfg.get(cfg.isMergeChapte)
            download_folder = cfg.get(cfg.downloadFolder)
            path = f"{download_folder}/{comic_name}"
            # 漫画目录不存在（所有章节均未提取到图片，无任何下载产物）：跳过合并、标记失败
            # 否则 get_directories 的 os.listdir 与 EpubThread 都会在缺失目录上 FileNotFoundError 崩溃
            if not os.path.isdir(path):
                logging.info(f'[站点下载] 漫画目录不存在，无下载产物，标记失败: {path}')
                if self.hidden:
                    # 下载管理：发 failed 信号，_onFailed 置 status=-1 + 刷新表格 + 失败提示
                    if self.task_id is not None:
                        self.failed.emit(self.task_id)
                else:
                    # 同域非隐藏：还原 UI + 失败提示（仅兜底崩溃，不动同域下载流程）
                    self.stateTooltip.hide()
                    self.toggle_mask(1)
                    self.chapter_button.setDisabled(False)
                    show_tip(InfoBarIcon.ERROR, '温馨提示', '未提取到任何图片，下载失败', self)
                return
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
            if not self.hidden:
                self.stateTooltip.setContent(
                    '已完成' + str(progress) + '%,请耐心等待~~')
            self.launch_iframes(comic_name)

    def download_finish(self, path):
        logging.info('[站点下载] epub合并完成')
        # 下载管理（隐藏模式）：更新任务状态完成 + 发信号，不弹对话框
        if self.hidden:
            if self.task_id is not None:
                with SQLiteDatabase() as db:
                    db.update_data('website_chapter_download',
                                   {'status': 2, 'process': 100, 'finish_time': get_current_time()},
                                   {'id': self.task_id})
            self.finished.emit(self.task_id, path)
            return
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
        if not checked_items:
            return
        checked_chapters = [obj for obj in result['chapters'] if obj['name'] in checked_items]
        # 跨域站点：保存到下载管理（不立即下载，到下载管理窗口触发浏览器下载）
        if getattr(self.parent, 'cross_origin', 0) == 1:
            first, last = checked_chapters[0]['name'], checked_chapters[-1]['name']
            chapter_range = first if first == last else f'{first} ~ {last}'
            site_config = self.parent.get_site_config()
            with SQLiteDatabase() as db:
                db.insert_data('website_chapter_download', {
                    'comic_name': result['comic_name'], 'site_name': '',
                    'chapter_count': len(checked_chapters), 'chapter_range': chapter_range,
                    'chapters_json': json.dumps(checked_chapters, ensure_ascii=False),
                    'site_config_json': json.dumps(site_config, ensure_ascii=False),
                    'status': 0, 'process': 0, 'start_time': get_current_time()})
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '已加入下载管理，可在站点页「下载管理」中开始下载',
                     self.parent.window(), InfoBarPosition.TOP)
            return
        # 同域站点：现状立即下载
        self.parent.toggle_mask(0)
        self.parent.chapter_button.setDisabled(True)
        self.download_button.setDisabled(True)

        self.parent.stateTooltip.show()

        self.parent.downloadComic(result, checked_chapters)
