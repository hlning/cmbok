# coding:utf-8
"""图书详情对话框：点击图书卡片弹出，排版参考 app 端 book_detail_page，
仅保留「收藏」与「下载」，不含在线阅读/书架/推荐。"""
import logging
import re
import traceback

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QPixmap, QMovie
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import MessageBoxBase, FluentIcon, PrimaryPushButton, PushButton, \
    FlowLayout, InfoBarPosition, InfoBarIcon, MessageBox

from common.config import cfg
from common.signal_bus import signalBus
from common.sqlite_util import SQLiteDatabase
from custom.my_fluent_icon import MyFluentIcon
from service.cmbok_service import BookDownload
from utils.base_utils import get_current_time
from view.components.folder_tree import TreeFrame
from view.components.info_bar_tip import show_tip


def _strip_html(text):
    """去除 z-library 简介里的 HTML 标签，合并多余空白"""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', str(text))
    return re.sub(r'\s+', ' ', text).strip()


def _safe_str(value):
    if value is None:
        return ''
    return str(value)


class _Chip(QLabel):
    """元信息小标签：圆角半透明底，适配深浅主题；highlight=True 为主色高亮（格式）"""

    def __init__(self, text, highlight=False, parent=None):
        super().__init__(text, parent)
        if highlight:
            self.setStyleSheet(
                "QLabel { background-color: rgba(0, 120, 212, 55); color: #2b8fff; "
                "border-radius: 9px; padding: 4px 12px; font: 12px 'Segoe UI', 'Microsoft YaHei'; }")
        else:
            self.setStyleSheet(
                "QLabel { background-color: rgba(128, 128, 128, 55); "
                "border-radius: 9px; padding: 4px 12px; font: 12px 'Segoe UI', 'Microsoft YaHei'; }")


class _TreeMessageBox(MessageBoxBase):
    """收藏夹选择对话框（图书 type=2）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.treeFrame = TreeFrame(2)
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


class BookDetailDialog(MessageBoxBase):
    """图书详情对话框"""

    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.cover = book.get('cover', '')
        self.name = book.get('title', '')
        self.author = _safe_str(book.get('author'))
        self.book_id = book.get('id')
        self.book_hash = book.get('hash')
        self.extension = _safe_str(book.get('extension'))
        self.is_collect = False
        self.bookDownload = None
        self._desc_expanded = False

        self.setWindowTitle('图书详情')
        self.widget.setFixedWidth(600)

        self.contentWidget = QWidget(self.widget)
        self.contentWidget.setStyleSheet('background: transparent;')
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setSpacing(10)
        self.contentLayout.setContentsMargins(36, 14, 36, 14)

        self._build_cover()
        self._build_title()
        self._build_score()
        self._build_chips()
        self._build_buttons()
        self._build_synopsis()

        self.viewLayout.addWidget(self.contentWidget)

        # 底部只留「关闭」：固定宽度居中
        self.yesButton.setText('关闭')
        self.yesButton.setFixedWidth(120)
        self.cancelButton.hide()
        self.buttonLayout.removeWidget(self.cancelButton)
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.addStretch(1)
        self.buttonLayout.addWidget(self.yesButton, 0, Qt.AlignVCenter)
        self.buttonLayout.addStretch(1)

    # ---- UI 构建 ----
    def _build_cover(self):
        self.coverLabel = QLabel(self.contentWidget)
        self.coverLabel.setScaledContents(True)
        self.coverLabel.setFixedSize(180, 240)
        self.coverLabel.setAlignment(Qt.AlignCenter)
        self._load_image(self.cover)
        self.contentLayout.addWidget(self.coverLabel, alignment=Qt.AlignHCenter)

    def _build_title(self):
        self.titleLabel = QLabel(self.name, self.contentWidget)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setAlignment(Qt.AlignCenter)
        self.titleLabel.setStyleSheet(
            "font: 20px 'Segoe UI', 'Microsoft YaHei'; font-weight: 600;")
        self.contentLayout.addWidget(self.titleLabel)

        self.authorLabel = QLabel(self.author or '未知作者', self.contentWidget)
        self.authorLabel.setAlignment(Qt.AlignCenter)
        self.authorLabel.setStyleSheet(
            "font: 13px 'Segoe UI', 'Microsoft YaHei'; color: #888;")
        self.contentLayout.addWidget(self.authorLabel)

    def _build_score(self):
        try:
            score = float(self.book.get('interestScore') or 0)
        except (TypeError, ValueError):
            score = 0
        if score > 0:
            self.scoreLabel = QLabel(f'★ {score:.1f}  兴趣评分', self.contentWidget)
            self.scoreLabel.setAlignment(Qt.AlignCenter)
            self.scoreLabel.setStyleSheet("font: 13px 'Segoe UI'; color: #f0a020;")
            self.contentLayout.addWidget(self.scoreLabel)

    def _build_chips(self):
        chipsWidget = QWidget(self.contentWidget)
        chipsWidget.setStyleSheet('background: transparent;')
        chipsLayout = FlowLayout(chipsWidget)
        chipsLayout.setSpacing(8)

        ext = self.extension.upper()
        if ext:
            chipsLayout.addWidget(_Chip(ext, highlight=True, parent=chipsWidget))
        year = _safe_str(self.book.get('year'))
        if year:
            chipsLayout.addWidget(_Chip(year, parent=chipsWidget))
        lang = _safe_str(self.book.get('language'))
        if lang:
            chipsLayout.addWidget(_Chip(lang, parent=chipsWidget))
        size = _safe_str(self.book.get('filesizeString'))
        if size:
            chipsLayout.addWidget(_Chip(size, parent=chipsWidget))
        pages = _safe_str(self.book.get('pages'))
        if pages:
            chipsLayout.addWidget(_Chip(f'{pages} 页', parent=chipsWidget))
        publisher = _safe_str(self.book.get('publisher'))
        if publisher:
            chipsLayout.addWidget(_Chip(publisher, parent=chipsWidget))
        isbn = _safe_str(self.book.get('identifier'))
        if isbn:
            chipsLayout.addWidget(_Chip(f'ISBN: {isbn}', parent=chipsWidget))

        self.contentLayout.addWidget(chipsWidget, alignment=Qt.AlignHCenter)

    def _build_buttons(self):
        # 初始收藏状态
        sqlite_util = SQLiteDatabase()
        try:
            records = sqlite_util.query_data('cmbok_collection_record', {'key': self.book_id, 'type': 2})
            self.is_collect = len(records) > 0
        finally:
            sqlite_util.close()

        btnWidget = QWidget(self.contentWidget)
        btnWidget.setStyleSheet('background: transparent;')
        btnLayout = QHBoxLayout(btnWidget)
        btnLayout.setSpacing(12)

        self.collectBtn = PushButton(
            MyFluentIcon.HAVE_COLLECT if self.is_collect else MyFluentIcon.COLLECT,
            '已收藏' if self.is_collect else '收藏')
        self.collectBtn.setFixedHeight(36)
        self.collectBtn.clicked.connect(self.collectBook)
        btnLayout.addWidget(self.collectBtn)

        self.downloadBtn = PrimaryPushButton(FluentIcon.DOWNLOAD, '下载')
        self.downloadBtn.setFixedHeight(36)
        self.downloadBtn.clicked.connect(self.downloadBook)
        btnLayout.addWidget(self.downloadBtn)

        self.contentLayout.addWidget(btnWidget, alignment=Qt.AlignHCenter)

    def _build_synopsis(self):
        desc = _strip_html(self.book.get('description'))
        if not desc:
            return
        self.synopsisTitle = QLabel('简介', self.contentWidget)
        self.synopsisTitle.setStyleSheet(
            "font: 14px 'Segoe UI', 'Microsoft YaHei'; font-weight: 600;")
        self.contentLayout.addWidget(self.synopsisTitle)

        self.descLabel = QLabel(desc, self.contentWidget)
        self.descLabel.setWordWrap(True)
        self.descLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.descLabel.setStyleSheet("font: 14px 'Segoe UI','Microsoft YaHei';")
        self.descLabel.setMaximumHeight(110)  # 默认收起约 4 行
        self.contentLayout.addWidget(self.descLabel)

        self.expandBtn = PushButton('展开', self.contentWidget)
        self.expandBtn.setFixedWidth(80)
        self.expandBtn.clicked.connect(self._toggle_synopsis)
        self.contentLayout.addWidget(self.expandBtn, alignment=Qt.AlignRight)

    def _toggle_synopsis(self):
        self._desc_expanded = not self._desc_expanded
        if self._desc_expanded:
            self.descLabel.setMaximumHeight(16777215)
            self.expandBtn.setText('收起')
        else:
            self.descLabel.setMaximumHeight(110)
            self.expandBtn.setText('展开')

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
        self._load_fallback_image(':/cmbok/images/book_cover.png')

    def _load_loading_gif(self, gif_path):
        movie = QMovie(gif_path)
        self.coverLabel.setMovie(movie)
        movie.start()

    def _load_fallback_image(self, path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.coverLabel.setPixmap(pixmap)

    # ---- 收藏 ----
    def collectBook(self):
        sqlite_util = SQLiteDatabase()
        try:
            if not self.is_collect:
                w = _TreeMessageBox(self.window())
                if w.exec():
                    selected_items = w.treeFrame.tree.selectedItems()
                    if selected_items:
                        folder_name = selected_items[0].text(0)
                        folder = sqlite_util.query_data('comic_collection_folder',
                                                        {'name': folder_name, 'type': 2})
                        folder_id = 0 if folder_name == '首页' else folder[0].id
                        sqlite_util.insert_data('cmbok_collection_record', {
                            'cover': self.cover, 'name': self.name, 'author': self.author,
                            'key': self.book_id, 'book_hash': self.book_hash,
                            'book_extension': self.extension, 'type': 2,
                            'collection_time': get_current_time(), 'folder_id': folder_id})
                        self.collectBtn.setIcon(MyFluentIcon.HAVE_COLLECT)
                        self.collectBtn.setText('已收藏')
                        self.is_collect = True
                        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '收藏成功', self)
            else:
                sqlite_util.delete_data('cmbok_collection_record', {'key': self.book_id, 'type': 2})
                self.collectBtn.setIcon(MyFluentIcon.COLLECT)
                self.collectBtn.setText('收藏')
                self.is_collect = False
                show_tip(InfoBarIcon.WARNING, '温馨提示', '已取消收藏', self)
            signalBus.collectChanged.emit()
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '系统异常', self, InfoBarPosition.TOP)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('详情对话框收藏图书异常')
        finally:
            sqlite_util.close()

    # ---- 下载 ----
    def downloadBook(self):
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
        self.bookDownload = BookDownload(book=self.book)
        self.bookDownload.success.connect(self.downloadBookStatus)
        self.bookDownload.start()

    def downloadBookStatus(self, status):
        # BookDownload.success 仅在开始下载时 emit 'success'；进度/完成走 download_signals 到下载页
        try:
            if status == 'success':
                show_tip(InfoBarIcon.SUCCESS, '温馨提示', '已加入下载队列，可在「下载」页查看进度', self)
        except Exception:
            pass
