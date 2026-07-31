# coding:utf-8
"""通用分页栏：共X条 / 每页Y条 / 页码 / < > / 第X/Y页
页码与翻页均为可点击文字；仅当前页有边框+背景色，其余悬停变色。"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from qfluentwidgets import ComboBox, CaptionLabel, qconfig, themeColor, isDarkTheme


class _PageLabel(QLabel):
    """可点击的文字标签（页码/箭头）"""
    clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(28)
        self.setMinimumWidth(32)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(e)


class PaginationBar(QWidget):
    pageChanged = pyqtSignal(int)       # 0-based 页码
    pageSizeChanged = pyqtSignal(int)   # 每页条数

    def __init__(self, page_sizes=None, parent=None):
        super().__init__(parent)
        self.page_sizes = page_sizes or [10, 15, 20]

        self.hLayout = QHBoxLayout(self)
        self.hLayout.setContentsMargins(0, 0, 0, 0)
        self.hLayout.setSpacing(8)

        self.totalLabel = CaptionLabel('共 0 条', self)
        self.pageSizeBox = ComboBox(self)
        self.pageSizeBox.addItems([f'{s} 条/页' for s in self.page_sizes])
        self.pageSizeBox.setCurrentIndex(0)
        self.pageSizeBox.currentIndexChanged.connect(self._onPageSizeChanged)

        self.prevBtn = _PageLabel('<', self)
        self.prevBtn.setProperty('role', 'arrow')
        self.prevBtn.clicked.connect(lambda: self._goto(self._page - 1))
        self.nextBtn = _PageLabel('>', self)
        self.nextBtn.setProperty('role', 'arrow')
        self.nextBtn.clicked.connect(lambda: self._goto(self._page + 1))
        self.pagesLayout = QHBoxLayout()
        self.pagesLayout.setSpacing(4)

        self.pageLabel = CaptionLabel('第 1 / 1 页', self)

        self.hLayout.addWidget(self.totalLabel)
        self.hLayout.addWidget(self.pageSizeBox)
        self.hLayout.addWidget(self.prevBtn)
        self.hLayout.addLayout(self.pagesLayout)
        self.hLayout.addWidget(self.nextBtn)
        self.hLayout.addWidget(self.pageLabel)

        self._page = 0
        self._pageCount = 1
        self._pageWidgets = []

        self._applyStyle()
        qconfig.themeChanged.connect(self._applyStyle)

    def _applyStyle(self):
        accent = themeColor().name()
        text_color = '#eaeaea' if isDarkTheme() else '#2c2c2c'
        current_text = '#000000' if isDarkTheme() else '#ffffff'
        self.setStyleSheet(f"""
            QLabel {{ padding: 2px 8px; border-radius: 4px; color: {text_color}; font-size: 14px; }}
            QComboBox {{ font-size: 14px; }}
            QLabel[role="arrow"] {{ font-weight: bold; }}
            QLabel[role="page"][current="false"]:hover,
            QLabel[role="arrow"]:enabled:hover {{
                color: {accent};
            }}
            QLabel[role="page"][current="true"] {{
                background: {accent}; border: 1px solid {accent}; color: {current_text};
            }}
            QLabel[role="arrow"]:disabled {{
                color: gray;
            }}
        """)

    def _onPageSizeChanged(self, idx):
        self.pageSizeChanged.emit(self.page_sizes[idx])

    def setCurrentPageSize(self, size):
        """设置当前每页条数（用于记忆恢复），不在可选列表中则保持默认；不触发信号"""
        if size in self.page_sizes:
            self.pageSizeBox.blockSignals(True)
            self.pageSizeBox.setCurrentIndex(self.page_sizes.index(size))
            self.pageSizeBox.blockSignals(False)

    def _goto(self, p):
        if 0 <= p < self._pageCount:
            self.pageChanged.emit(p)

    def setPage(self, page, pageCount, total):
        self._page = max(0, min(page, max(0, pageCount - 1)))
        self._pageCount = max(1, pageCount)
        self.totalLabel.setText(f'共 {total} 条')
        self.prevBtn.setEnabled(self._page > 0)
        self.nextBtn.setEnabled(self._page < self._pageCount - 1)
        self.pageLabel.setText(f'第 {self._page + 1} / {self._pageCount} 页')
        self._renderPages()

    def _renderPages(self):
        for w in self._pageWidgets:
            self.pagesLayout.removeWidget(w)
            w.deleteLater()
        self._pageWidgets.clear()
        for p in self._pageNumbers():
            if p == -1:
                lbl = CaptionLabel('...', self)
                self.pagesLayout.addWidget(lbl)
                self._pageWidgets.append(lbl)
            else:
                btn = _PageLabel(str(p + 1), self)
                btn.setProperty('role', 'page')
                btn.setProperty('current', p == self._page)
                btn.clicked.connect(lambda pp=p: self._goto(pp))
                self.pagesLayout.addWidget(btn)
                self._pageWidgets.append(btn)

    def _pageNumbers(self):
        cur, total = self._page, self._pageCount
        if total <= 7:
            return list(range(total))
        pages = [0]
        if cur > 2:
            pages.append(-1)
        pages.extend(range(max(1, cur - 1), min(total - 1, cur + 1) + 1))
        if cur < total - 3:
            pages.append(-1)
        pages.append(total - 1)
        return pages
