# coding:utf-8
"""搜索历史下拉弹窗

聚焦搜索框时弹出，显示历史关键词列表：点击某项触发搜索、点右侧小叉删除单条、底部「清空历史」。
- 窗口标志 Qt.ToolTip：不抢键盘焦点、不占任务栏，搜索框持续可输入。
- 所有内部控件 setFocusPolicy(NoFocus)：点击不夺焦点，避免 focusOut 误关。
- 样式内联 QSS，监听 qconfig.themeChanged 适配 dark/light（不依赖 qrc 资源）。
"""
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtWidgets import (QFrame, QWidget, QHBoxLayout, QVBoxLayout, QScrollArea,
                             QGraphicsOpacityEffect)

from qfluentwidgets import (TransparentToolButton, TransparentPushButton, BodyLabel,
                            CaptionLabel, FluentIcon, isDarkTheme, qconfig)


class HistoryItemWidget(QWidget):
    """单条历史项：点击文字区域选中、点击右侧小叉删除"""
    selected = pyqtSignal(str)
    removeRequested = pyqtSignal(str)

    def __init__(self, keyword, parent=None):
        super().__init__(parent)
        self._keyword = keyword
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAttribute(Qt.WA_Hover)
        self.setObjectName('historyItem')
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 2, 0)
        layout.setSpacing(0)

        self.label = BodyLabel(keyword, self)
        self.label.setCursor(Qt.PointingHandCursor)
        # 文字超长省略（不换行），保持行高一致
        from PyQt5.QtCore import Qt as _Qt
        self.label.setWordWrap(False)
        layout.addWidget(self.label, 1)

        self.delBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.delBtn.setFixedSize(26, 26)
        self.delBtn.setIconSize(QSize(11, 11))
        self.delBtn.setFocusPolicy(Qt.NoFocus)
        self.delBtn.setToolTip('删除')
        self.delBtn.clicked.connect(lambda: self.removeRequested.emit(self._keyword))
        layout.addWidget(self.delBtn)

    def keyword(self):
        return self._keyword

    def mousePressEvent(self, e):
        # 点击非按钮区域（文字/空白）触发选中；点小叉由 TransparentToolButton 自身消费，不会进到这
        if e.button() == Qt.LeftButton:
            self.selected.emit(self._keyword)
        super().mousePressEvent(e)


class SearchHistoryPopup(QFrame):
    """搜索历史下拉弹窗"""
    selected = pyqtSignal(str)     # 选中某条 -> 填回搜索框并触发搜索
    removed = pyqtSignal(str)      # 删除某条 -> 搜索框更新存储并刷新
    cleared = pyqtSignal()         # 清空全部 -> 搜索框更新存储并刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._items = []
        self._initUi()
        self._stylePopup()
        qconfig.themeChanged.connect(self._stylePopup)

    def _initUi(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)

        # 列表滚动区
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFrameShape(QFrame.NoFrame)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setFocusPolicy(Qt.NoFocus)
        self.scrollArea.setStyleSheet('background: transparent; border: none;')

        self.container = QWidget(self.scrollArea)
        self.containerLayout = QVBoxLayout(self.container)
        self.containerLayout.setContentsMargins(6, 6, 6, 6)
        self.containerLayout.setSpacing(2)
        self.containerLayout.addStretch()
        self.scrollArea.setWidget(self.container)
        layout.addWidget(self.scrollArea)

        # 分隔线
        self.separator = QFrame(self)
        self.separator.setFrameShape(QFrame.HLine)
        self.separator.setFixedHeight(1)
        layout.addWidget(self.separator)

        # 底部「清空历史」
        self.footer = QWidget(self)
        footerLayout = QHBoxLayout(self.footer)
        footerLayout.setContentsMargins(12, 2, 12, 4)
        footerLayout.setSpacing(0)
        footerLayout.addStretch()
        self.clearBtn = TransparentPushButton(FluentIcon.DELETE, '清空历史', self.footer)
        self.clearBtn.setFocusPolicy(Qt.NoFocus)
        self.clearBtn.setIconSize(QSize(13, 13))
        self.clearBtn.clicked.connect(self._onClear)
        footerLayout.addWidget(self.clearBtn)
        layout.addWidget(self.footer)

        # 空状态
        self.emptyLabel = CaptionLabel('暂无搜索历史', self)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setFixedHeight(44)
        layout.addWidget(self.emptyLabel)

        self.setMaximumHeight(360)

    def setKeywords(self, keywords, empty_text='暂无搜索历史'):
        """重建列表显示给定 keywords（已过滤后的子集）"""
        self._items = list(keywords)
        # 清空 container（保留末尾 stretch）
        while self.containerLayout.count() > 1:
            item = self.containerLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for kw in self._items:
            item = HistoryItemWidget(kw, self.container)
            item.selected.connect(self._onSelected)
            item.removeRequested.connect(self._onRemove)
            self.containerLayout.insertWidget(self.containerLayout.count() - 1, item)
        self.emptyLabel.setText(empty_text)
        self._updateVisibility()

    def _updateVisibility(self):
        has = bool(self._items)
        self.scrollArea.setVisible(has)
        self.separator.setVisible(has)
        self.footer.setVisible(has)
        self.emptyLabel.setVisible(not has)
        if has:
            # 列表区高度：每项 32 + 间距；最多 8 条后滚动
            n = len(self._items)
            list_h = min(n * 34 + 12, 280)
            self.scrollArea.setFixedHeight(list_h)
        self.adjustSize()

    def _onSelected(self, keyword):
        self.selected.emit(keyword)

    def _onRemove(self, keyword):
        self.removed.emit(keyword)

    def _onClear(self):
        self.cleared.emit()

    def _stylePopup(self):
        dark = isDarkTheme()
        bg = '#2b2b2b' if dark else '#ffffff'
        fg = '#eaeaea' if dark else '#1f1f1f'
        sub = '#9d9d9d' if dark else '#888888'
        hover = 'rgba(255,255,255,26)' if dark else 'rgba(0,0,0,26)'
        border = 'rgba(255,255,255,0.12)' if dark else 'rgba(0,0,0,0.1)'
        self.setStyleSheet(f"""
            SearchHistoryPopup {{
                background: {bg}; border: 1px solid {border};
                border-radius: 8px;
            }}
            #historyItem {{
                background: transparent; border-radius: 5px;
            }}
            #historyItem:hover {{
                background: {hover};
            }}
            BodyLabel {{ color: {fg}; border: none; background: transparent; }}
            CaptionLabel {{ color: {sub}; border: none; background: transparent; }}
            QScrollArea, #historyItem > * {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 2px 4px 0; }}
            QScrollBar::handle:vertical {{ background: rgba(128,128,128,150); border-radius: 3px; min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: rgba(128,128,128,210); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
