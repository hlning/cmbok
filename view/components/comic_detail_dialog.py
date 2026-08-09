# coding:utf-8
"""漫画详情对话框：点击漫画卡片弹出，排版参考 app 端 comic_detail_page，
仅保留「收藏」与「下载」（章节勾选下载），不含在线阅读/书架/续读。"""
import logging
import re
import traceback

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QPixmap, QMovie
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import MessageBoxBase, FluentIcon, PrimaryPushButton, PushButton, \
    FlowLayout, IndeterminateProgressBar, InfoBarPosition, InfoBarIcon

from common.signal_bus import signalBus
from common.sqlite_util import SQLiteDatabase
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import ComicGroups
from utils.base_utils import get_current_time
from view.components.comic_search_card import ChapterGroupView
from view.components.folder_tree import TreeFrame
from view.components.info_bar_tip import show_tip


def _strip_html(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', str(text))
    return re.sub(r'\s+', ' ', text).strip()


def _to_float(v):
    try:
        return float(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _to_int(v):
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_author(value):
    """拷贝漫画 author 可能是 [{name}] / 字符串"""
    if not value:
        return ''
    if isinstance(value, list):
        names = [(x.get('name', '') if isinstance(x, dict) else str(x)) for x in value]
        return ', '.join(n for n in names if n)
    if isinstance(value, dict):
        return str(value.get('name', ''))
    return str(value)


def _parse_status(value):
    """status 可能是字符串或 {value, display} 对象"""
    if not value:
        return ''
    if isinstance(value, dict):
        return str(value.get('display') or value.get('value') or '').strip()
    return str(value).strip()


def _parse_tags(value):
    """tags/theme 可能是 [{name}]/[{tag}]/字符串数组"""
    if not value:
        return []
    if isinstance(value, list):
        out = []
        for x in value:
            n = (x.get('name') or x.get('tag') or '') if isinstance(x, dict) else str(x)
            if n:
                out.append(str(n))
        return out
    return [str(value)]


def _fmt_popular(p):
    return f'{p / 10000:.1f}万' if p >= 10000 else str(p)


class _Tag(QLabel):
    """状态/标签 chip：status 绿色，tag 灰色"""

    def __init__(self, text, kind='tag', parent=None):
        super().__init__(text, parent)
        if kind == 'status':
            self.setStyleSheet(
                "QLabel { background-color: rgba(76, 175, 80, 55); color: #4caf50; "
                "border-radius: 9px; padding: 3px 12px; font: 12px 'Segoe UI','Microsoft YaHei'; }")
        else:
            self.setStyleSheet(
                "QLabel { background-color: rgba(128, 128, 128, 55); "
                "border-radius: 9px; padding: 3px 12px; font: 12px 'Segoe UI','Microsoft YaHei'; }")


class _TreeMessageBox(MessageBoxBase):
    """收藏夹选择对话框（漫画 type=1）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.treeFrame = TreeFrame(1)
        self.viewLayout.addWidget(self.treeFrame)
        self.yesButton.setText('确定')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(350)

    def validate(self):
        isValid = True
        if not self.treeFrame.tree.selectedItems():
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请选择一个文件夹', self)
            isValid = False
        return isValid


class ComicDetailDialog(MessageBoxBase):
    """漫画详情对话框"""

    def __init__(self, cover, name, author, path_word, parent=None):
        super().__init__(parent)
        self.cover = cover
        self.name = name
        self.author = author
        self.path_word = path_word
        self.is_collect = False
        self._desc_expanded = False
        self._pendingGroupView = None

        # 章节下载链 ChapterDetailView.downloadComic 读取模块级全局变量，这里设置（同 DownloadFlyoutView）
        import view.components.comic_search_card as _cs
        _cs.comic_name = name
        _cs.comic_path_word = path_word
        _cs.comic_author = author

        self.setWindowTitle('漫画详情')
        self.widget.setFixedWidth(640)

        self.contentWidget = QWidget(self.widget)
        self.contentWidget.setStyleSheet('background: transparent;')
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setSpacing(12)
        self.contentLayout.setContentsMargins(30, 14, 30, 14)

        self._build_header()
        self._build_buttons()
        self._build_synopsis_placeholder()
        self._build_chapter_loading()

        self.viewLayout.addWidget(self.contentWidget)

        self.yesButton.setText('关闭')
        self.yesButton.setFixedWidth(120)
        self.cancelButton.hide()
        self.buttonLayout.removeWidget(self.cancelButton)
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.addStretch(1)
        self.buttonLayout.addWidget(self.yesButton, 0, Qt.AlignVCenter)
        self.buttonLayout.addStretch(1)

        # 拉取详情（comic）+ 分组（groups），一次请求
        self.comicGroups = ComicGroups(path_word=path_word)
        self.comicGroups.success.connect(self._on_groups_loaded)
        self.comicGroups.start()

    # ---- 头部 ----
    def _build_header(self):
        headerWidget = QWidget(self.contentWidget)
        headerWidget.setStyleSheet('background: transparent;')
        hLayout = QHBoxLayout(headerWidget)
        hLayout.setSpacing(14)
        hLayout.setContentsMargins(0, 0, 0, 0)

        self.coverLabel = QLabel(headerWidget)
        self.coverLabel.setScaledContents(True)
        self.coverLabel.setFixedSize(110, 150)
        self._load_image(self.cover)
        hLayout.addWidget(self.coverLabel, alignment=Qt.AlignTop)

        infoWidget = QWidget(headerWidget)
        infoWidget.setStyleSheet('background: transparent;')
        infoLayout = QVBoxLayout(infoWidget)
        infoLayout.setSpacing(6)
        infoLayout.setContentsMargins(0, 0, 0, 0)

        self.titleLabel = QLabel(self.name, infoWidget)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setStyleSheet(
            "font: 18px 'Segoe UI','Microsoft YaHei'; font-weight: 600;")
        infoLayout.addWidget(self.titleLabel)

        self.authorLabel = QLabel(f'👤 {self.author or "未知"}', infoWidget)
        self.authorLabel.setStyleSheet(
            "font: 12px 'Segoe UI','Microsoft YaHei'; color: rgba(128,128,128,200);")
        self.authorLabel.setWordWrap(True)
        infoLayout.addWidget(self.authorLabel)

        # 状态/评分/标签占位（详情加载完填充）
        self.metaWidget = QWidget(infoWidget)
        self.metaWidget.setStyleSheet('background: transparent;')
        self.metaLayout = QVBoxLayout(self.metaWidget)
        self.metaLayout.setSpacing(6)
        self.metaLayout.setContentsMargins(0, 0, 0, 0)
        infoLayout.addWidget(self.metaWidget)
        infoLayout.addStretch()

        hLayout.addWidget(infoWidget, 1)
        self.contentLayout.addWidget(headerWidget)

    def _fill_meta(self, comic):
        author = _parse_author(comic.get('author'))
        if author:
            self.authorLabel.setText(f'👤 {author}')

        status = _parse_status(comic.get('status'))
        if status:
            self.metaLayout.addWidget(_Tag(status, kind='status', parent=self.metaWidget))

        rating = _to_float(comic.get('rating'))
        popular = _to_int(comic.get('popular'))
        if rating > 0:
            scoreLabel = QLabel(f'★ {rating:.1f}', self.metaWidget)
            scoreLabel.setStyleSheet("font: 13px 'Segoe UI'; color: #f0a020;")
            self.metaLayout.addWidget(scoreLabel)
        elif popular > 0:
            scoreLabel = QLabel(f'🔥 {_fmt_popular(popular)}', self.metaWidget)
            scoreLabel.setStyleSheet("font: 13px 'Segoe UI'; color: #e8590c;")
            self.metaLayout.addWidget(scoreLabel)

        tags = _parse_tags(comic.get('tags') or comic.get('theme'))[:4]
        if tags:
            tagsWidget = QWidget(self.metaWidget)
            tagsWidget.setStyleSheet('background: transparent;')
            tagsLayout = FlowLayout(tagsWidget)
            tagsLayout.setSpacing(6)
            for t in tags:
                tagsLayout.addWidget(_Tag(t, kind='tag', parent=tagsWidget))
            self.metaLayout.addWidget(tagsWidget)

    # ---- 操作按钮 ----
    def _build_buttons(self):
        sqlite_util = SQLiteDatabase()
        try:
            records = sqlite_util.query_data('cmbok_collection_record', {'key': self.path_word, 'type': 1})
            self.is_collect = len(records) > 0
        finally:
            sqlite_util.close()

        btnWidget = QWidget(self.contentWidget)
        btnWidget.setStyleSheet('background: transparent;')
        btnLayout = QHBoxLayout(btnWidget)
        btnLayout.setSpacing(12)
        btnLayout.setContentsMargins(0, 0, 0, 0)

        self.collectBtn = PushButton(
            MyFluentIcon.HAVE_COLLECT if self.is_collect else MyFluentIcon.COLLECT,
            '已收藏' if self.is_collect else '收藏')
        self.collectBtn.setFixedHeight(36)
        self.collectBtn.clicked.connect(self.collectComic)
        btnLayout.addStretch()
        btnLayout.addWidget(self.collectBtn)
        self.contentLayout.addWidget(btnWidget)

    # ---- 简介 ----
    def _build_synopsis_placeholder(self):
        self.synopsisBox = QWidget(self.contentWidget)
        self.synopsisBox.setStyleSheet('background: transparent;')
        self.synopsisLayout = QVBoxLayout(self.synopsisBox)
        self.synopsisLayout.setContentsMargins(0, 0, 0, 0)
        self.synopsisLayout.setSpacing(6)
        self.synopsisBox.setVisible(False)
        self.contentLayout.addWidget(self.synopsisBox)

    def _fill_synopsis(self, comic):
        desc = _strip_html(comic.get('description') or comic.get('synopsis') or comic.get('brief'))
        if not desc:
            return
        synopsisTitle = QLabel('简介', self.synopsisBox)
        synopsisTitle.setStyleSheet(
            "font: 14px 'Segoe UI','Microsoft YaHei'; font-weight: 600;")
        self.synopsisLayout.addWidget(synopsisTitle)

        self.descLabel = QLabel(desc, self.synopsisBox)
        self.descLabel.setWordWrap(True)
        self.descLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.descLabel.setStyleSheet("font: 14px 'Segoe UI','Microsoft YaHei';")
        self.descLabel.setMaximumHeight(96)
        self.synopsisLayout.addWidget(self.descLabel)

        self.expandBtn = PushButton('展开', self.synopsisBox)
        self.expandBtn.setFixedWidth(80)
        self.expandBtn.clicked.connect(self._toggle_synopsis)
        self.synopsisLayout.addWidget(self.expandBtn, alignment=Qt.AlignRight)
        self.synopsisBox.setVisible(True)

    def _toggle_synopsis(self):
        self._desc_expanded = not self._desc_expanded
        if self._desc_expanded:
            self.descLabel.setMaximumHeight(16777215)
            self.expandBtn.setText('收起')
        else:
            self.descLabel.setMaximumHeight(96)
            self.expandBtn.setText('展开')

    # ---- 章节区 ----
    def _build_chapter_loading(self):
        self.chapterBox = QWidget(self.contentWidget)
        self.chapterBox.setStyleSheet('background: transparent;')
        self.chapterLayout = QVBoxLayout(self.chapterBox)
        self.chapterLayout.setContentsMargins(0, 0, 0, 0)
        self.chapterLayout.setSpacing(0)

        self.loadingWidget = QWidget(self.chapterBox)
        loadingLayout = QVBoxLayout(self.loadingWidget)
        loadingLayout.setContentsMargins(0, 0, 0, 0)
        self.loadingLabel = QLabel('正在加载章节，请稍候...', self.loadingWidget)
        self.loadingLabel.setStyleSheet("font: 14px 'Segoe UI','Microsoft YaHei';")
        self.loadingBar = IndeterminateProgressBar(self.loadingWidget)
        loadingLayout.addWidget(self.loadingLabel)
        loadingLayout.addWidget(self.loadingBar)
        self.chapterLayout.addWidget(self.loadingWidget)
        self.contentLayout.addWidget(self.chapterBox)

    def _on_groups_loaded(self, status, results):
        try:
            if status != 'success':
                self.loadingWidget.setVisible(False)
                tip_map = {
                    'fail': ('网络异常，o(╥﹏╥)o', InfoBarIcon.WARNING),
                    'timeout': ('请求超时了，(。・＿・。)ﾉ', InfoBarIcon.ERROR),
                    'error': ('系统异常，(。・＿・。)ﾉ', InfoBarIcon.ERROR),
                }
                text, icon = tip_map.get(status, ('加载失败', InfoBarIcon.ERROR))
                self.loadingLabel.setText(text)
                show_tip(icon, '温馨提示', text, self)
                return
            comic = results.get('comic', {}) or {}
            self._fill_meta(comic)
            self._fill_synopsis(comic)
            # 创建章节分组视图（内部启动章节加载），首个分组就绪后替换进度条
            self._pendingGroupView = ChapterGroupView(results, self._on_chapters_loaded)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('漫画详情加载分组失败')

    def _on_chapters_loaded(self):
        self.loadingWidget.setVisible(False)
        if self._pendingGroupView is not None:
            self.chapterLayout.addWidget(self._pendingGroupView)
            self._pendingGroupView = None

    # ---- 封面加载 ----
    def _load_image(self, image_url):
        self._load_loading_gif(':/cmbok/images/loading.gif')
        self.manager = QNetworkAccessManager(self)
        self.manager.finished.connect(self._on_image_loaded)
        self.manager.get(QNetworkRequest(QUrl(image_url)))

    def _on_image_loaded(self, reply):
        if reply.error() == reply.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.coverLabel.setPixmap(pixmap)
                return
        self._load_fallback_image(':/cmbok/images/comic_cover.png')

    def _load_loading_gif(self, gif_path):
        movie = QMovie(gif_path)
        self.coverLabel.setMovie(movie)
        movie.start()

    def _load_fallback_image(self, path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.coverLabel.setPixmap(pixmap)

    # ---- 收藏 ----
    def collectComic(self):
        sqlite_util = SQLiteDatabase()
        try:
            if not self.is_collect:
                w = _TreeMessageBox(self.window())
                if w.exec():
                    selected_items = w.treeFrame.tree.selectedItems()
                    if selected_items:
                        folder_name = selected_items[0].text(0)
                        folder = sqlite_util.query_data('comic_collection_folder',
                                                        {'name': folder_name, 'type': 1})
                        folder_id = 0 if folder_name == '首页' else folder[0].id
                        sqlite_util.insert_data('cmbok_collection_record', {
                            'cover': self.cover, 'name': self.name, 'author': self.author,
                            'key': self.path_word, 'type': 1,
                            'collection_time': get_current_time(), 'folder_id': folder_id})
                        self.collectBtn.setIcon(MyFluentIcon.HAVE_COLLECT)
                        self.collectBtn.setText('已收藏')
                        self.is_collect = True
                        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '收藏成功', self)
            else:
                sqlite_util.delete_data('cmbok_collection_record', {'key': self.path_word, 'type': 1})
                self.collectBtn.setIcon(MyFluentIcon.COLLECT)
                self.collectBtn.setText('收藏')
                self.is_collect = False
                show_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self)
            signalBus.collectChanged.emit()
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常', self, InfoBarPosition.TOP)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('详情对话框收藏漫画异常')
        finally:
            sqlite_util.close()
