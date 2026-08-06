# coding:utf-8
"""带搜索历史的 SearchLineEdit

聚焦时弹出历史下拉（最近搜索/输入过滤匹配），点击历史项填入并触发搜索，
点小叉删单条，底部「清空历史」一键清空。历史存于 config.json（见 common.search_history）。

- 不抢焦点：popup 用 Qt.ToolTip + NoFocus，搜索框持续可输入、textChanged 实时过滤。
- 记录时机：searchSignal（点搜索按钮 / 选中历史项触发 search()）与 returnPressed（回车）都记录。
- 不改动各页已有的 searchSignal/returnPressed 连接，仅在自身内部并联记录与过滤逻辑。
"""
from PyQt5.QtCore import Qt, QPoint, QTimer, QEvent
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import SearchLineEdit

from common.search_history import SearchHistory
from view.components.search_history_popup import SearchHistoryPopup


class HistorySearchLineEdit(SearchLineEdit):
    """带搜索历史下拉的搜索框"""

    def __init__(self, config_item, parent=None):
        super().__init__(parent)
        self._history = SearchHistory(config_item)
        self._popup = SearchHistoryPopup(self)
        self._popup.selected.connect(self._onPopupSelected)
        self._popup.removed.connect(self._onPopupRemoved)
        self._popup.cleared.connect(self._onPopupCleared)

        # 搜索触发时记录历史：searchSignal 带 text 参数；returnPressed 无参，单独读 text
        self.searchSignal.connect(self._recordHistory)
        self.returnPressed.connect(self._recordHistoryFromReturn)
        # 输入时实时过滤
        self.textChanged.connect(self._onTextChanged)

        self._filteredWindow = None  # 已安装事件过滤器的顶层窗口

    # ---------- 历史过滤 ----------
    def _filter(self, text):
        text = (text or '').strip().lower()
        all_kw = self._history.get_all()
        if not text:
            return all_kw, '暂无搜索历史'
        filtered = [k for k in all_kw if text in k.lower()]
        return filtered, '无匹配历史'

    def _refreshPopup(self):
        items, empty_text = self._filter(self.text())
        self._popup.setKeywords(items, empty_text)

    # ---------- popup 显隐与定位 ----------
    def _showPopup(self):
        self._refreshPopup()
        self._popup.setFixedWidth(self.width())
        self._popup.move(self.mapToGlobal(QPoint(0, self.height())))
        self._popup.show()
        self._popup.raise_()

    def _hidePopup(self):
        if self._popup.isVisible():
            self._popup.hide()

    def _maybeHidePopup(self):
        """focusOut 后延迟检查：鼠标/焦点仍在 popup 或本框则保留，否则隐藏。

        真实鼠标点击浮窗内按钮（删除/清空）时，主窗口会瞬间失活、搜索框失焦又
        获焦，从而触发 focusOut；若此时隐藏浮窗，按钮会丢失鼠标 grab，mouseRelease
        不再送达，clicked 不发出（表现为删除无效）。故先按鼠标位置判断：鼠标正落在
        popup 或本框上，说明用户正在与浮窗交互，必须保留。
        """
        pos = QCursor.pos()
        if self._popup.isVisible() and self._popup.geometry().contains(pos):
            return
        if self.rect().contains(self.mapFromGlobal(pos)):
            return
        focus = QApplication.focusWidget()
        if focus is not None and focus is not self:
            # 焦点在 popup 内部 -> 保留
            p = focus
            while p is not None:
                if p is self._popup:
                    return
                p = p.parentWidget()
        self._hidePopup()

    def _repositionPopup(self):
        self._popup.setFixedWidth(self.width())
        self._popup.move(self.mapToGlobal(QPoint(0, self.height())))

    # ---------- 事件重写 ----------
    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._showPopup()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        # 延迟到下一轮事件循环，让点击删除/清空按钮的焦点转移先完成
        QTimer.singleShot(0, self._maybeHidePopup)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._hidePopup()
            return
        super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._popup.isVisible():
            self._repositionPopup()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self._popup.isVisible():
            self._repositionPopup()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hidePopup()

    def showEvent(self, e):
        super().showEvent(e)
        self._ensureWindowFilter()

    def _ensureWindowFilter(self):
        """懒安装事件过滤器到顶层窗口。

        __init__ 时 widget 尚未挂到主窗口，window() 还不是最终窗口；
        故在首次 showEvent 时安装，并在 window() 变化时重新挂载。
        """
        win = self.window()
        if win is self._filteredWindow:
            return
        if self._filteredWindow is not None:
            self._filteredWindow.removeEventFilter(self)
        if win is not None:
            win.installEventFilter(self)
        self._filteredWindow = win

    def eventFilter(self, obj, event):
        # 浮窗是独立顶层窗口、用全局坐标定位：主窗口移动/缩放时需主动重定位，
        # 主窗口隐藏（最小化/关闭）时收起浮窗，避免它悬空停在原屏幕位置。
        if obj is self._filteredWindow:
            t = event.type()
            if t == QEvent.Move or t == QEvent.Resize:
                if self._popup.isVisible():
                    self._repositionPopup()
            elif t == QEvent.Hide:
                self._hidePopup()
        return super().eventFilter(obj, event)

    def _onTextChanged(self, text):
        if self._popup.isVisible():
            self._refreshPopup()

    # ---------- popup 信号 ----------
    def _onPopupSelected(self, keyword):
        self._hidePopup()
        self.setText(keyword)
        self.search()  # 触发 searchSignal -> 各页搜索 + _recordHistory 记录

    def _onPopupRemoved(self, keyword):
        self._history.remove(keyword)
        self._refreshPopup()

    def _onPopupCleared(self):
        self._history.clear()
        self._refreshPopup()

    # ---------- 记录历史 ----------
    def _recordHistory(self, text):
        self._history.add(text)

    def _recordHistoryFromReturn(self):
        self._history.add(self.text())
