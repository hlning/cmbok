# coding:utf-8
import logging
import math
import os
import traceback

from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QObject, QTimer, QSize
from PyQt5.QtGui import QColor, QBrush, QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QTableWidgetItem, QHeaderView, QFrame
from qfluentwidgets import ScrollArea, SegmentedToolWidget, FluentIcon, InfoBarPosition, InfoBarIcon, \
    TableWidget, RoundMenu, Action, ProgressRing, PrimaryToolButton

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from view.components.info_bar_tip import show_tip
from view.components.pagination_bar import PaginationBar
from view.components.empty_state_widget import EmptyStateWidget
from view.components.history_search_line_edit import HistorySearchLineEdit


# 定义全局信号槽类
class DownloadSignals(QObject):
    success = pyqtSignal(object, object, object, object)  # 定义信号


# 创建全局信号槽实例
download_signals = DownloadSignals()


class BookProcessSignals(QObject):
    success = pyqtSignal(object, object)  # 定义信号


book_process_signals = BookProcessSignals()


class ComicProcessSignals(QObject):
    success = pyqtSignal(object, object)  # 定义信号


comic_process_signals = ComicProcessSignals()


class DownloadInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('DownloadInterface')

        self.pivot = SegmentedToolWidget(self)
        self.stackedWidget = QStackedWidget(self)

        self.titleLabel = QLabel('⬇️我的下载', self)
        self.titleLabel.setObjectName('viewTitleLabel')

        self.hBoxLayout = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        # 下载完成通知
        download_signals.success.connect(self.downloadFinish)

        # 顶部导航
        # 漫画下载记录
        self.comicAreaInterface = DownloadAreaInterface('请输入漫画名搜索', 1)
        self.addSubInterface(self.comicAreaInterface, '漫画', MyFluentIcon.COMIC)
        # 图书下载记录
        self.bookAreaInterface = DownloadAreaInterface('请输入图书名搜索', 2)
        self.addSubInterface(self.bookAreaInterface, '图书', MyFluentIcon.BOOK)

        self.hBoxLayout.addWidget(self.pivot, 0, Qt.AlignCenter)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addLayout(self.hBoxLayout)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(36, 20, 36, 15)
        self.vBoxLayout.setSpacing(12)
        StyleSheet.SAMPLE_CARD.apply(self)

        self.stackedWidget.setCurrentWidget(self.comicAreaInterface)
        self.pivot.setCurrentItem(self.comicAreaInterface.objectName())
        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

        self.stackedWidget.currentChanged.connect(lambda index: self.updateComicRecords(index + 1))

    def addSubInterface(self, widget: QLabel, objectName, icon):
        widget.setObjectName(objectName)
        widget.setAlignment(Qt.AlignCenter)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, icon=icon)

    # 更新下载记录
    def updateComicRecords(self, type=1):
        if type == 1:
            self.comicAreaInterface.banner.search(None)
        else:
            self.bookAreaInterface.banner.search(None)

    # 刷新下载表格列宽（导航展开/收缩后内容区宽度变化时调用）
    def refreshTableSize(self):
        self.comicAreaInterface.banner.reset_bookview_size()
        self.bookAreaInterface.banner.reset_bookview_size()

    # 下载完成
    def downloadFinish(self, status, name, chapter_name, type=1):
        if status == 'success':
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', f"{name}-{chapter_name}下载完成，o(￣▽￣)ｄ", self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'fail':
            show_tip(InfoBarIcon.ERROR, '温馨提示', f"{name}-{chapter_name}下载失败，(꒦_꒦)", self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'no_account':
            show_tip(InfoBarIcon.ERROR, '温馨提示', f"今日已无法下载，明天再来吧(*^▽^*)", self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'no_num':
            show_tip(InfoBarIcon.ERROR, '温馨提示', f"已达到今日最大下载限制，明天再来吧(*^▽^*)", self,
                         InfoBarPosition.TOP_RIGHT)

        self.updateComicRecords(type)


# 下载窗口
class DownloadAreaInterface(ScrollArea):
    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.banner = DownloadWidget(name, type)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('comicDownloadInterface')
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


# 下载记录窗口
class DownloadWidget(QWidget):
    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.type = type
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(14)

        self.lineEdit = HistorySearchLineEdit(cfg.download_search_history)
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setFixedHeight(40)
        self.lineEdit.searchButton.setIconSize(QSize(14, 14))
        self.lineEdit.setPlaceholderText(name)
        self.lineEdit.searchSignal.connect(lambda text: self.search(text))
        self.lineEdit.textChanged.connect(lambda text: self.on_text_changed(text))
        self.lineEdit.returnPressed.connect(self.enter)

        self.vBoxLayout.addWidget(self.lineEdit, alignment=Qt.AlignCenter)

        # 下载进度更新
        if type == 2:
            book_process_signals.success.connect(self.updateProcess)
        else:
            comic_process_signals.success.connect(self.updateProcess)

        # 下载记录表格
        # 启用边框并设置圆角
        self.tableWidget = TableWidget(self)
        # 不设固定高度，由布局 stretch 决定，表格内部自带垂直滚动条
        self.tableWidget.setBorderVisible(True)
        self.tableWidget.setBorderRadius(8)

        self.tableWidget.setWordWrap(False)
        self.tableWidget.setRowCount(0)

        if self.type == 1:
            self.tableWidget.setColumnCount(9)
            self.tableWidget.verticalHeader().hide()
            self.tableWidget.setHorizontalHeaderLabels(
                ['ID', '漫画名称', '漫画作者', '章节名称', '状态', '进度', '开始时间', '完成时间', '操作'])
        else:
            self.tableWidget.setColumnCount(8)
            self.tableWidget.verticalHeader().hide()
            self.tableWidget.setHorizontalHeaderLabels(
                ['ID', '图书名称', '图书作者', '状态', '进度', '开始时间', '完成时间', '操作'])

        self.tableWidget.setColumnHidden(0, True)
        # 固定宽度列：状态/进度/开始时间/完成时间/操作；其余列（名称/作者/章节）自适应
        if self.type == 1:
            self._fixedColumns = {4: 90, 5: 70, 6: 160, 7: 160, 8: 90}
            self._flexColumns = {1: 1.3, 2: 1.0, 3: 0.9}
        else:
            self._fixedColumns = {3: 90, 4: 70, 5: 160, 6: 160, 7: 90}
            self._flexColumns = {1: 1.7, 2: 1.4}
        # 关闭水平滚动条：总宽由约束保持=表格宽，避免出现滚动条
        self.tableWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 防止 sectionResized 回调重入
        self._resizing = False
        # 设置水平表头并隐藏垂直表头
        header = self.tableWidget.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 自适应列可拖动；固定列固定宽度不可拖
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col in self._fixedColumns:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        header.setStretchLastSection(False)
        # 拖动列宽下限，保证表头文字不被拖到看不全
        header.setMinimumSectionSize(60)
        # 拖动自适应列时约束总宽=表格宽，其余自适应列按比例缩放
        header.sectionResized.connect(self._onSectionResized)
        # 使用样式表调整表头的样式
        header.setStyleSheet("QHeaderView::section { padding-left: 20px; }")
        self.reset_bookview_size()

        # 右键菜单：用右键位置定位行，避免 currentRow 返回旧行号时 item 为 None 崩溃
        self.tableWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableWidget.customContextMenuRequested.connect(self.show_context_menu)

        # 结果区：有数据显示表格，无数据显示空状态占位
        self.resultStack = QStackedWidget(self)
        self.resultStack.addWidget(self.tableWidget)  # 页0：表格
        self.emptyWidget = EmptyStateWidget(FluentIcon.DOWNLOAD, '暂无下载记录', self)
        self.resultStack.addWidget(self.emptyWidget)  # 页1：空状态
        self.resultStack.setCurrentWidget(self.emptyWidget)
        self.vBoxLayout.addWidget(self.resultStack, 1)

        # 分页栏
        self._pageSize = 10
        self._searchText = None
        self._total = 0
        self._pageCount = 1
        self.pager = PaginationBar([10, 20, 30], self)
        self.pager.pageChanged.connect(self.getRecords)
        self.pager.pageSizeChanged.connect(self._onPageSizeChanged)
        self.pager.setCurrentPageSize(cfg.get(cfg.downloadPageSize))
        self._pageSize = self.pager.page_sizes[self.pager.pageSizeBox.currentIndex()]
        self.setPage(None)

        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignCenter)

    # 下载进度更新
    def updateProcess(self, history_id, new_process):
        row_count = self.tableWidget.rowCount()
        for row in range(row_count):
            item = self.tableWidget.item(row, 0)
            if item and item.text() == str(history_id):
                if self.type == 1:
                    widgt = self.tableWidget.cellWidget(row, 5)
                    ring = widgt.findChild(ProgressRing)
                    ring.setValue(new_process)
                else:
                    widgt = self.tableWidget.cellWidget(row, 4)
                    ring = widgt.findChild(ProgressRing)
                    ring.setValue(new_process)
                return

    # 表格右键菜单（用右键位置定位行，避免 currentRow 返回旧行号时 item 为 None 崩溃）
    def show_context_menu(self, position):
        try:
            row = self.tableWidget.rowAt(position.y())
            if row < 0:
                return

            id_item = self.tableWidget.item(row, 0)
            if not id_item:
                return
            id = id_item.text()
            name_item = self.tableWidget.item(row, 1)
            name = name_item.text() if name_item else ''
            chapter_item = self.tableWidget.item(row, 3)
            chapter_name = chapter_item.text() if chapter_item else ''

            menu = RoundMenu()

            # 逐个添加动作，Action 继承自 QAction，接受 FluentIconBase 类型的图标
            if self.type == 1:
                menu.addAction(
                    Action(FluentIcon.FOLDER, '打开漫画目录', triggered=lambda: self.openFolder(name)))
                menu.addAction(
                    Action(FluentIcon.FOLDER, '打开章节目录',
                           triggered=lambda: self.openFolder(name, chapter_name)))
            else:
                menu.addAction(
                    Action(FluentIcon.FOLDER, '打开图书目录', triggered=lambda: self.openFolder('')))

            # menu.addAction(
            #    Action(FluentIcon.DOWNLOAD, '重新下载', triggered=lambda: self.againDownload(id)))

            menu.addAction(
                Action(FluentIcon.DELETE, '删除下载记录', triggered=lambda: self.delRecord(id)))

            # 清空失败记录
            menu.addAction(Action(MyFluentIcon.CLEAR, '清空失败记录', triggered=self.delErrorRecord))

            # 清空下载记录
            menu.addAction(Action(MyFluentIcon.CLEAR, '清空下载记录', triggered=self.delAllRecord))

            # 显示右键菜单
            menu.exec_(self.tableWidget.viewport().mapToGlobal(position))
        except Exception:
            logging.info('下载右键菜单异常: ' + traceback.format_exc())

    # 清空失败记录
    def delErrorRecord(self):
        sqlite_util = SQLiteDatabase()
        try:
            sqlite_util.delErrorRecord('cmbok_download_history')
            self.search(self.lineEdit.text())
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空记录成功', self)
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '清空记录失败', self)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('删除下载记录异常')
        finally:
            sqlite_util.close()

    # 清空下载记录
    def delAllRecord(self):
        sqlite_util = SQLiteDatabase()
        try:
            sqlite_util.delete_data('cmbok_download_history', {'type': self.type})
            self.search(self.lineEdit.text())
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空记录成功', self)
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '清空记录失败', self)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('删除下载记录异常')
        finally:
            sqlite_util.close()

    # 删除下载记录
    def delRecord(self, id):
        sqlite_util = SQLiteDatabase()
        try:
            sqlite_util.delete_data('cmbok_download_history', {'id': id})
            self.search(self.lineEdit.text())
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '删除记录成功', self)
        except Exception:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '删除记录失败', self)
            sqlite_util.rollback()
            logging.info(traceback.format_exc())
            logging.info('删除下载记录异常')
        finally:
            sqlite_util.close()

    # 打开漫画/章节目录
    def openFolder(self, name, chapter_name=''):
        folder_path = os.path.join(cfg.get(cfg.downloadFolder), name, chapter_name)
        if os.path.exists(folder_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
        else:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '目录不存在', self)

    # 表格每列宽度（开始时间权重更大；完成时间由 Stretch 自动填满剩余；操作列固定）
    def reset_bookview_size(self):
        width = self.tableWidget.viewport().width()
        if width <= 0:
            return
        fixed_total = sum(self._fixedColumns.values())
        remain = max(width - fixed_total, len(self._flexColumns) * 80)
        total_w = sum(self._flexColumns.values())
        self._resizing = True
        try:
            # 固定列设固定宽度
            for col, w in self._fixedColumns.items():
                self.tableWidget.setColumnWidth(col, w)
            # 自适应列按比例分配剩余空间（随窗口宽度变化）
            for col, w in self._flexColumns.items():
                self.tableWidget.setColumnWidth(col, int(remain * w / total_w))
        finally:
            self._resizing = False

    # 拖动自适应列时约束总宽=表格宽，避免出现水平滚动条
    def _onSectionResized(self, col, old, new):
        if self._resizing or col not in self._flexColumns:
            return
        self._resizing = True
        try:
            width = self.tableWidget.viewport().width()
            fixed_total = sum(self._fixedColumns.values())
            target_flex = max(width - fixed_total, 0)
            others = [c for c in self._flexColumns if c != col]
            min_w = 60
            # 限制拖动列最大宽度，保证其余自适应列不小于 min_w
            max_col = max(target_flex - len(others) * min_w, min_w)
            if new > max_col:
                new = max_col
                self.tableWidget.setColumnWidth(col, new)
            # 其余自适应列按当前比例分摊剩余空间
            remain = target_flex - new
            if others:
                others_total = sum(self.tableWidget.columnWidth(c) for c in others)
                if others_total > 0:
                    for c in others:
                        self.tableWidget.setColumnWidth(c, max(min_w, int(remain * self.tableWidget.columnWidth(c) / others_total)))
                else:
                    per = remain // len(others)
                    for c in others:
                        self.tableWidget.setColumnWidth(c, max(min_w, per))
            else:
                # 只有一个自适应列，直接占满剩余
                self.tableWidget.setColumnWidth(col, target_flex)
        finally:
            self._resizing = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 延迟到布局完成后再重算列宽，确保取到最新表格宽度并及时自适应
        QTimer.singleShot(0, self.reset_bookview_size)

    # 回车搜索
    def enter(self):
        self.search(self.lineEdit.text())

    # 搜索内容监听
    def on_text_changed(self, text):
        if text == "":
            self.search(None)

    # 搜索
    def search(self, text):
        self.setPage(text)

    # 设置页码（搜索/切每页条数时重算总数与页数，并加载第1页）
    def setPage(self, text):
        self._searchText = text
        sqlite_util = SQLiteDatabase()
        try:
            count = sqlite_util.count_data('cmbok_download_history',
                                           conditions={'name': f'%{text}%', 'type': self.type})
            self._total = count
            self._pageCount = max(1, math.ceil(count / self._pageSize))
            self.pager.setPage(0, self._pageCount, count)
            # 无数据时隐藏分页组件，有数据才显示
            self.pager.setVisible(self._total > 0)
            # 有数据显示表格，无数据显示空状态占位
            self.resultStack.setCurrentWidget(self.tableWidget if self._total > 0 else self.emptyWidget)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('查询下载记录异常')
        finally:
            sqlite_util.close()
        self.getRecords(0)

    # 获取下载记录
    def getRecords(self, index):
        self._currentPage = index
        sqlite_util = SQLiteDatabase()
        try:
            # 清空表格内容
            self.tableWidget.clearContents()
            # 查询下载记录
            historys = sqlite_util.query_data('cmbok_download_history',
                                              conditions={'name': f'%{self._searchText}%', 'type': self.type},
                                              order_by='status ASC,start_time DESC,name ASC,chapter_name DESC',
                                              limit=self._pageSize,
                                              offset=index * self._pageSize)
            self.tableWidget.setRowCount(len(historys))

            # 添加表格数据
            for i, history in enumerate(historys):
                status_msg = '下载限制' if history.status == -5 else '今日无法下载' if history.status == -4 else '软件退出' if history.status == -3 else '版权受限' if history.status == -2 else '转换epub失败' if history.status == -1 else '下载中' if history.status == 1 else '等待中' if history.status == 2 else '已完成' if history.status == 3 else '下载失败'
                status_item = QTableWidgetItem(status_msg)
                if history.status == -5 or history.status == -4 or history.status == -3 or history.status == -2 or history.status == -1 or history.status == 0:
                    status_item.setForeground(QBrush(QColor(253, 46, 86)))  # 红色字体
                elif history.status == 1:
                    status_item.setForeground(QBrush(QColor(64, 158, 215)))  # 蓝色字体
                elif history.status == 2:
                    status_item.setForeground(QBrush(QColor(198, 202, 219)))  # 灰色字体
                elif history.status == 3:
                    status_item.setForeground(QBrush(QColor(19, 210, 105)))  # 绿色字体
                self.tableWidget.setItem(i, 0, QTableWidgetItem(str(history.id)))
                status_item.setStatusTip(status_msg)

                nameItem = QTableWidgetItem(history.name)
                nameItem.setToolTip(history.name)
                self.tableWidget.setItem(i, 1, nameItem)
                self.tableWidget.setItem(i, 2, QTableWidgetItem(history.author))

                # 进度环
                ring_widget = self.createRing(history.process)

                if self.type == 1:
                    self.tableWidget.setItem(i, 3, QTableWidgetItem(history.chapter_name))
                    self.tableWidget.setItem(i, 4, status_item)
                    self.tableWidget.setCellWidget(i, 5, ring_widget)
                    self.tableWidget.setItem(i, 6, QTableWidgetItem(history.start_time))
                    self.tableWidget.setItem(i, 7, QTableWidgetItem(history.finish_time))
                    self.tableWidget.setCellWidget(i, 8, self.createRedownloadBtn(history))
                else:
                    self.tableWidget.setItem(i, 3, status_item)
                    self.tableWidget.setCellWidget(i, 4, ring_widget)
                    self.tableWidget.setItem(i, 5, QTableWidgetItem(history.start_time))
                    self.tableWidget.setItem(i, 6, QTableWidgetItem(history.finish_time))
                    self.tableWidget.setCellWidget(i, 7, self.createRedownloadBtn(history))
            self.pager.setPage(index, self._pageCount, self._total)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('查询下载记录异常')
        finally:
            sqlite_util.close()

    # 每页条数变化
    def _onPageSizeChanged(self, size):
        self._pageSize = size
        cfg.set(cfg.downloadPageSize, size)
        self.setPage(self._searchText)

    def createRing(self, process):
        # 创建按钮
        ring = ProgressRing()
        # 设置进度环取值范围和当前值
        ring.setRange(0, 100)
        ring.setValue(int(process))
        # 调整进度环大小
        ring.setFixedSize(25, 25)
        # 调整厚度
        ring.setStrokeWidth(4)

        # 创建一个 QHBoxLayout 来居中按钮
        layout = QHBoxLayout()
        layout.addWidget(ring)  # 水平居中

        # 创建一个 QWidget 容器，将布局应用于该容器
        container = QWidget()
        container.setLayout(layout)
        container.setFixedHeight(50)
        return container

    # 重新下载按钮
    def createRedownloadBtn(self, history):
        btn = PrimaryToolButton(FluentIcon.SYNC)
        btn.setFixedSize(32, 32)
        btn.setToolTip('重新下载')
        btn.clicked.connect(lambda _, h=history: self.redownload(h))
        layout = QHBoxLayout()
        layout.addWidget(btn)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        container.setLayout(layout)
        container.setFixedHeight(50)
        return container

    # 重新下载：删除旧记录，按历史信息重新发起下载
    def redownload(self, history):
        # 延迟导入避免与 service 层（download_signals）循环依赖
        from service.cmbok_service import ComicChapterImages, BookDownload
        with SQLiteDatabase() as db:
            db.delete_data('cmbok_download_history', {'id': history.id})
        if self.type == 1:
            # 漫画：按章节重新下载（chapter_path_word 实际存的是章节 uuid）
            checked_chapters = [{'name': history.chapter_name, 'uuid': history.chapter_path_word}]
            self.redownloadThread = ComicChapterImages(
                comic_name=history.name, comic_path_word=history.key,
                comic_author=history.author, checked_chapters=checked_chapters)
            self.redownloadThread.success.connect(self._onRedownloadStart)
            self.redownloadThread.start()
        else:
            # 图书：按历史信息重新下载（extension 缺失时兜底 epub）
            book = {
                'cover': history.cover or '',
                'title': history.name,
                'author': history.author,
                'id': history.key,
                'hash': history.book_hash,
                'extension': history.book_extension or 'epub'
            }
            self.redownloadBook = BookDownload(book=book)
            self.redownloadBook.success.connect(self._onRedownloadStart)
            self.redownloadBook.start()

    # 重新下载开始/被锁/异常：刷新列表
    def _onRedownloadStart(self, status):
        if status == 'lock':
            show_tip(InfoBarIcon.WARNING, '温馨提示', '前一个任务还在下载，请等会再下载吧(*￣︶￣)',
                     self, InfoBarPosition.TOP)
        self.search(self.lineEdit.text())
# 下载窗口
