# coding:utf-8
import json
import logging
import math
import os
import traceback

from PyQt5.QtCore import Qt, QUrl, QTimer, QSize
from PyQt5.QtGui import QColor, QBrush, QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, \
    QTableWidgetItem, QHeaderView, QMainWindow
from qfluentwidgets import FluentIcon, InfoBarPosition, InfoBarIcon, TableWidget, RoundMenu, Action, \
    ProgressRing, PrimaryToolButton, MessageBox, SearchLineEdit

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from view.components.info_bar_tip import show_tip
from view.components.pagination_bar import PaginationBar
from view.components.empty_state_widget import EmptyStateWidget


class WebsiteDownloadManagerWindow(QMainWindow):
    """站点下载管理窗口（跨域站点的下载任务）：表格展示 + 下载/删除

    仅 cross_origin=1 的站点在浮窗勾选后保存记录到此表；
    点下载构造隐藏 Browser 执行取图+浏览器下载图片+合并 epub，进度回传更新表格。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('下载管理')
        self.resize(1000, 640)
        self._downloading_browser = None  # 持有下载中 Browser 引用防 GC

        self.titleLabel = QLabel('📥站点下载管理', self)
        self.titleLabel.setObjectName('viewTitleLabel')

        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
        self.lineEdit.setFixedHeight(40)
        self.lineEdit.searchButton.setIconSize(QSize(14, 14))
        self.lineEdit.setPlaceholderText('请输入漫画名搜索')
        self.lineEdit.searchSignal.connect(lambda text: self.search(text))
        self.lineEdit.textChanged.connect(lambda text: self.on_text_changed(text))
        self.lineEdit.returnPressed.connect(self.enter)

        # 下载记录表格
        self.tableWidget = TableWidget(self)
        self.tableWidget.setBorderVisible(True)
        self.tableWidget.setBorderRadius(8)
        self.tableWidget.setWordWrap(False)
        self.tableWidget.setRowCount(0)
        self.tableWidget.setColumnCount(9)
        self.tableWidget.verticalHeader().hide()
        self.tableWidget.setHorizontalHeaderLabels(
            ['ID', '漫画名称', '章节数', '章节范围', '状态', '进度', '创建时间', '完成时间', '操作'])
        self.tableWidget.setColumnHidden(0, True)
        # 固定宽度列：章节数/状态/进度/创建时间/完成时间/操作；名称/范围自适应
        self._fixedColumns = {2: 70, 4: 90, 5: 70, 6: 160, 7: 160, 8: 110}
        self._flexColumns = {1: 2.0, 3: 1.5}
        self.tableWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._resizing = False
        header = self.tableWidget.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col in self._fixedColumns:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        header.sectionResized.connect(self._onSectionResized)
        header.setStyleSheet("QHeaderView::section { padding-left: 20px; }")
        self.tableWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableWidget.customContextMenuRequested.connect(self.show_context_menu)

        # 结果区：表格 / 空状态
        self.resultStack = QStackedWidget(self)
        self.resultStack.addWidget(self.tableWidget)
        self.emptyWidget = EmptyStateWidget(FluentIcon.DOWNLOAD, '暂无下载记录', self)
        self.resultStack.addWidget(self.emptyWidget)
        self.resultStack.setCurrentWidget(self.emptyWidget)

        # 分页
        self._pageSize = 10
        self._searchText = None
        self._total = 0
        self._pageCount = 1
        self.pager = PaginationBar([10, 20, 30], self)
        self.pager.pageChanged.connect(self.getRecords)
        self.pager.pageSizeChanged.connect(self._onPageSizeChanged)
        self.pager.setCurrentPageSize(cfg.get(cfg.downloadPageSize))
        self._pageSize = self.pager.page_sizes[self.pager.pageSizeBox.currentIndex()]

        central = QWidget(self)
        self.vBoxLayout = QVBoxLayout(central)
        self.vBoxLayout.setContentsMargins(36, 20, 36, 15)
        self.vBoxLayout.setSpacing(12)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.lineEdit, alignment=Qt.AlignCenter)
        self.vBoxLayout.addWidget(self.resultStack, 1)
        self.vBoxLayout.addWidget(self.pager, alignment=Qt.AlignCenter)
        self.setCentralWidget(central)
        StyleSheet.SAMPLE_CARD.apply(self)

        self.reset_bookview_size()
        self.setPage(None)

    # ---- 搜索 ----
    def enter(self):
        self.search(self.lineEdit.text())

    def on_text_changed(self, text):
        if text == "":
            self.search(None)

    def search(self, text):
        self.setPage(text)

    def setPage(self, text):
        self._searchText = text
        sqlite_util = SQLiteDatabase()
        try:
            count = sqlite_util.count_data('website_chapter_download',
                                            conditions={'comic_name': f'%{text}%'})
            self._total = count
            self._pageCount = max(1, math.ceil(count / self._pageSize))
            self.pager.setPage(0, self._pageCount, count)
            self.pager.setVisible(self._total > 0)
            self.resultStack.setCurrentWidget(self.tableWidget if self._total > 0 else self.emptyWidget)
        except Exception:
            logging.info(traceback.format_exc())
        finally:
            sqlite_util.close()
        self.getRecords(0)

    def getRecords(self, index):
        self._currentPage = index
        sqlite_util = SQLiteDatabase()
        try:
            self.tableWidget.clearContents()
            historys = sqlite_util.query_data('website_chapter_download',
                                              conditions={'comic_name': f'%{self._searchText}%'},
                                              order_by='start_time DESC',
                                              limit=self._pageSize,
                                              offset=index * self._pageSize)
            self.tableWidget.setRowCount(len(historys))
            for i, history in enumerate(historys):
                status_msg = ('下载中' if history.status == 1 else '已完成' if history.status == 2
                              else '失败' if history.status == -1 else '待下载')
                status_item = QTableWidgetItem(status_msg)
                if history.status == -1:
                    status_item.setForeground(QBrush(QColor(253, 46, 86)))  # 红
                elif history.status == 1:
                    status_item.setForeground(QBrush(QColor(64, 158, 215)))  # 蓝
                elif history.status == 2:
                    status_item.setForeground(QBrush(QColor(19, 210, 105)))  # 绿
                else:
                    status_item.setForeground(QBrush(QColor(198, 202, 219)))  # 灰
                self.tableWidget.setItem(i, 0, QTableWidgetItem(str(history.id)))
                nameItem = QTableWidgetItem(history.comic_name)
                nameItem.setToolTip(history.comic_name)
                self.tableWidget.setItem(i, 1, nameItem)
                self.tableWidget.setItem(i, 2, QTableWidgetItem(str(history.chapter_count)))
                self.tableWidget.setItem(i, 3, QTableWidgetItem(history.chapter_range or ''))
                self.tableWidget.setItem(i, 4, status_item)
                self.tableWidget.setCellWidget(i, 5, self.createRing(history.process))
                self.tableWidget.setItem(i, 6, QTableWidgetItem(history.start_time or ''))
                self.tableWidget.setItem(i, 7, QTableWidgetItem(history.finish_time or ''))
                self.tableWidget.setCellWidget(i, 8, self.createActionBtn(history))
            self.pager.setPage(index, self._pageCount, self._total)
        except Exception:
            logging.info(traceback.format_exc())
        finally:
            sqlite_util.close()

    def _onPageSizeChanged(self, size):
        self._pageSize = size
        cfg.set(cfg.downloadPageSize, size)
        self.setPage(self._searchText)

    # ---- 进度环 / 操作按钮 ----
    def createRing(self, process):
        ring = ProgressRing()
        ring.setRange(0, 100)
        ring.setValue(int(process or 0))
        ring.setFixedSize(25, 25)
        ring.setStrokeWidth(4)
        layout = QHBoxLayout()
        layout.addWidget(ring)
        container = QWidget()
        container.setLayout(layout)
        container.setFixedHeight(50)
        return container

    def createActionBtn(self, history):
        container = QWidget()
        layout = QHBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        download_btn = PrimaryToolButton(FluentIcon.DOWNLOAD)
        download_btn.setFixedSize(32, 32)
        download_btn.setToolTip('下载')
        if history.status in (1, 2):
            download_btn.setDisabled(True)  # 下载中/已完成不可再下载
        download_btn.clicked.connect(lambda _, h=history: self.startDownload(h))
        layout.addWidget(download_btn)
        del_btn = PrimaryToolButton(FluentIcon.DELETE)
        del_btn.setFixedSize(32, 32)
        del_btn.setToolTip('删除')
        if history.status == 1:
            del_btn.setDisabled(True)  # 下载中不可删除
        del_btn.clicked.connect(lambda _, h=history: self.delRecord(h))
        layout.addWidget(del_btn)
        container.setLayout(layout)
        container.setFixedHeight(50)
        return container

    # ---- 下载触发（构造隐藏 Browser 执行）----
    def startDownload(self, history):
        if self._downloading_browser is not None:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '有任务正在下载，请等待完成后再下载', self,
                     InfoBarPosition.TOP)
            return
        try:
            from view.website_interface import Browser
            sc = json.loads(history.site_config_json) if history.site_config_json else {}
            chapters = json.loads(history.chapters_json) if history.chapters_json else []
            if not chapters:
                show_tip(InfoBarIcon.WARNING, '温馨提示', '该记录没有章节信息，无法下载', self,
                         InfoBarPosition.TOP)
                return
            result = {'comic_name': history.comic_name}
            browser = Browser(
                url='', comic_cover_dom='', comic_name_dom='', chapter_name_dom='', chapter_link_dom='',
                img_dom=sc.get('img_dom', ''), img_attr=sc.get('img_attr', ''), img_script=sc.get('img_script', ''),
                use_frame=sc.get('use_frame'), chapter_order=sc.get('chapter_order'),
                img_load_mode=sc.get('img_load_mode'), next_page_selector=sc.get('next_page_selector', ''),
                page_label_selector=sc.get('page_label_selector', ''), cross_origin=sc.get('cross_origin', 0),
                restore_algorithm=sc.get('restore_algorithm', ''),
                hidden=True, task_id=history.id)
            browser.progress.connect(self._onProgress)
            browser.finished.connect(self._onFinished)
            browser.failed.connect(self._onFailed)
            self._downloading_browser = browser
            with SQLiteDatabase() as db:
                db.update_data('website_chapter_download', {'status': 1, 'process': 0}, {'id': history.id})
            self.search(self.lineEdit.text())
            browser.downloadComic(result, chapters, task_id=history.id)
        except Exception:
            logging.info('站点下载管理触发下载异常: ' + traceback.format_exc())
            self._downloading_browser = None
            with SQLiteDatabase() as db:
                db.update_data('website_chapter_download', {'status': -1}, {'id': history.id})
            self.search(self.lineEdit.text())
            show_tip(InfoBarIcon.ERROR, '温馨提示', '启动下载失败，请重试', self, InfoBarPosition.TOP)

    def _onProgress(self, task_id, process):
        for row in range(self.tableWidget.rowCount()):
            item = self.tableWidget.item(row, 0)
            if item and item.text() == str(task_id):
                widgt = self.tableWidget.cellWidget(row, 5)
                if widgt:
                    ring = widgt.findChild(ProgressRing)
                    if ring:
                        ring.setValue(int(process))
                return

    def _onFinished(self, task_id, path):
        browser = self._downloading_browser
        self._downloading_browser = None
        if browser is not None:
            try:
                browser.deleteLater()
            except Exception:
                pass
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '下载完成，o(￣▽￣)ｄ', self, InfoBarPosition.TOP_RIGHT)
        # 不再弹框询问打开目录（改为记录右键"打开目录"）

    def _onFailed(self, task_id):
        browser = self._downloading_browser
        self._downloading_browser = None
        if browser is not None:
            try:
                browser.deleteLater()
            except Exception:
                pass
        with SQLiteDatabase() as db:
            db.update_data('website_chapter_download', {'status': -1}, {'id': task_id})
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.ERROR, '温馨提示', '下载失败，请重试', self, InfoBarPosition.TOP_RIGHT)

    # ---- 删除 / 清空 ----
    def delRecord(self, history):
        if history.status == 1:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '下载中的任务不能删除', self, InfoBarPosition.TOP)
            return
        with SQLiteDatabase() as db:
            db.delete_data('website_chapter_download', {'id': history.id})
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '删除记录成功', self, InfoBarPosition.TOP)

    def show_context_menu(self, position):
        try:
            row = self.tableWidget.rowAt(position.y())
            if row < 0:
                return
            id_item = self.tableWidget.item(row, 0)
            if not id_item:
                return
            rid = id_item.text()
            name_item = self.tableWidget.item(row, 1)
            comic_name = name_item.text() if name_item else ''
            menu = RoundMenu(parent=self)
            menu.addAction(Action(FluentIcon.FOLDER, '打开目录', triggered=lambda: self._openDir(comic_name)))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.DELETE, '删除下载记录', triggered=lambda: self._delById(rid)))
            menu.addAction(Action(FluentIcon.DELETE, '清空已完成', triggered=self.delCompleted))
            menu.addAction(Action(FluentIcon.DELETE, '清空全部记录', triggered=self.delAll))
            self._ctx_menu = menu  # 保持引用防 exec 期间被 GC 导致偶发崩溃
            menu.exec(self.tableWidget.viewport().mapToGlobal(position))
        except Exception:
            logging.info('下载管理右键菜单异常: ' + traceback.format_exc())

    def _openDir(self, comic_name):
        # 打开该记录的漫画下载目录（= downloadFolder/comic_name）；目录不存在（未完成/已删除/
        # downloadFolder 变更）时回退下载根目录并提示，避免静默开错目录让人以为没定位到对应文件夹
        try:
            folder = cfg.get(cfg.downloadFolder)
            target = os.path.join(folder, comic_name) if comic_name else folder
            if os.path.isdir(target):
                logging.info(f'[下载管理] 打开目录: {target}')
            else:
                logging.info(f'[下载管理] 漫画目录不存在，回退根目录: target={target}')
                show_tip(InfoBarIcon.WARNING, '温馨提示', '该漫画目录不存在，已打开下载根目录',
                         self, InfoBarPosition.TOP_RIGHT)
                target = folder
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        except Exception:
            logging.info('打开目录异常: ' + traceback.format_exc())

    def _delById(self, rid):
        with SQLiteDatabase() as db:
            db.delete_data('website_chapter_download', {'id': rid})
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '删除记录成功', self, InfoBarPosition.TOP)

    def delCompleted(self):
        with SQLiteDatabase() as db:
            db.delete_data('website_chapter_download', {'status': 2})
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空已完成成功', self, InfoBarPosition.TOP)

    def delAll(self):
        w = MessageBox('确认清空', '确认清空全部下载记录吗？（下载中的任务不会被删除）', self)
        if not w.exec():
            return
        with SQLiteDatabase() as db:
            db.cursor.execute("DELETE FROM website_chapter_download WHERE status != 1")
            db.connection.commit()
        self.search(self.lineEdit.text())
        show_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空记录成功', self, InfoBarPosition.TOP)

    # ---- 表格列宽自适应（参考 download_interface）----
    def reset_bookview_size(self):
        width = self.tableWidget.viewport().width()
        if width <= 0:
            return
        fixed_total = sum(self._fixedColumns.values())
        remain = max(width - fixed_total, len(self._flexColumns) * 80)
        total_w = sum(self._flexColumns.values())
        self._resizing = True
        try:
            for col, w in self._fixedColumns.items():
                self.tableWidget.setColumnWidth(col, w)
            for col, w in self._flexColumns.items():
                self.tableWidget.setColumnWidth(col, int(remain * w / total_w))
        finally:
            self._resizing = False

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
            max_col = max(target_flex - len(others) * min_w, min_w)
            if new > max_col:
                new = max_col
                self.tableWidget.setColumnWidth(col, new)
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
                self.tableWidget.setColumnWidth(col, target_flex)
        finally:
            self._resizing = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.reset_bookview_size)

    def closeEvent(self, event):
        # 下载中关闭窗口：Browser 为独立窗口（parent=None），不随管理窗口销毁，
        # 其信号会回调到已销毁的表格导致崩溃，故需中断下载并将任务标记为失败（与崩溃启动清扫一致）。
        if self._downloading_browser is not None:
            w = MessageBox('提示', '有任务正在下载，关闭窗口将中断下载。确认关闭吗？', self)
            if not w.exec():
                event.ignore()
                return
            browser = self._downloading_browser
            self._downloading_browser = None
            tid = getattr(browser, 'task_id', None)
            try:
                browser.deleteLater()
            except Exception:
                pass
            if tid is not None:
                with SQLiteDatabase() as db:
                    # 中断下载标记为失败（与崩溃启动清扫一致），process 保留已下载进度
                    db.update_data('website_chapter_download', {'status': -1}, {'id': tid})
        event.accept()
