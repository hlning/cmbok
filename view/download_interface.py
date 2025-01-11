# coding:utf-8
import logging
import math
import os
import traceback

from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QBrush, QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QTableWidgetItem, QSizePolicy
from qfluentwidgets import ScrollArea, SearchLineEdit, SegmentedToolWidget, FluentIcon, InfoBarPosition, InfoBarIcon, \
    PipsPager, PipsScrollButtonDisplayMode, TableWidget, \
    RoundMenu, Action, ProgressRing

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon


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
        self.resize(400, 400)

        self.pivot = SegmentedToolWidget(self)
        self.stackedWidget = QStackedWidget(self)

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
        self.vBoxLayout.addLayout(self.hBoxLayout)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

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

    # 下载完成
    def downloadFinish(self, status, name, chapter_name, type=1):
        if status == 'success':
            info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', f"{name}-{chapter_name}下载完成，o(￣▽￣)ｄ", self,
                         InfoBarPosition.TOP_RIGHT)
        elif status == 'fail':
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', f"{name}-{chapter_name}下载失败，(꒦_꒦)", self,
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

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.setAlignment(Qt.AlignTop)


# 下载记录窗口
class DownloadWidget(QWidget):
    def __init__(self, name, type, parent=None):
        super().__init__(parent=parent)

        self.type = type
        self.vBoxLayout = QVBoxLayout(self)

        self.lineEdit = SearchLineEdit()
        self.lineEdit.setFixedWidth(500)
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
        self.tableWidget.setFixedHeight(650)
        self.tableWidget.setBorderVisible(True)
        self.tableWidget.setBorderRadius(8)

        self.tableWidget.setWordWrap(False)
        self.tableWidget.setRowCount(0)

        if self.type == 1:
            self.tableWidget.setColumnCount(8)
            self.tableWidget.verticalHeader().hide()
            self.tableWidget.setHorizontalHeaderLabels(
                ['ID', '漫画名称', '漫画作者', '章节名称', '状态', '进度', '开始时间', '完成时间'])
        else:
            self.tableWidget.setColumnCount(7)
            self.tableWidget.verticalHeader().hide()
            self.tableWidget.setHorizontalHeaderLabels(
                ['ID', '图书名称', '图书作者', '状态', '进度', '开始时间', '完成时间'])

        self.tableWidget.setColumnHidden(0, True)
        # 设置水平表头并隐藏垂直表头
        self.tableWidget.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 使用样式表调整表头的样式
        self.tableWidget.horizontalHeader().setStyleSheet("QHeaderView::section { padding-left: 20px; }")
        self.reset_bookview_size()
        # 查询下载记录
        self.vBoxLayout.addWidget(self.tableWidget)
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

        self.vBoxLayout.addStretch(1)
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

    # 表格右键操作
    def contextMenuEvent(self, event):
        # 获取鼠标点击的行
        row = self.tableWidget.currentRow()

        menu = RoundMenu()

        if row >= 0:  # 确保选中了一行
            id = self.tableWidget.item(row, 0).text()
            name = self.tableWidget.item(row, 1).text()
            chapter_name = self.tableWidget.item(row, 3).text()

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
            menu.exec_(event.globalPos())

    # 清空失败记录
    def delErrorRecord(self):
        sqlite_util = SQLiteDatabase()
        try:
            sqlite_util.delErrorRecord('cmbok_download_history')
            self.search(self.lineEdit.text())
            info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空记录成功', self)
        except Exception:
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '清空记录失败', self)
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
            info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', '清空记录成功', self)
        except Exception:
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '清空记录失败', self)
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
            info_bar_tip(InfoBarIcon.SUCCESS, '温馨提示', '删除记录成功', self)
        except Exception:
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '删除记录失败', self)
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
            info_bar_tip(InfoBarIcon.ERROR, '温馨提示', '目录不存在', self)

    # 表格每列宽度
    def reset_bookview_size(self):
        width = self.tableWidget.size().width()
        self.tableWidget.setColumnWidth(0, int(width))
        if self.type == 1:
            self.tableWidget.setColumnWidth(1, int(width * 1.3))
            self.tableWidget.setColumnWidth(2, int(width * 1.1))
            self.tableWidget.setColumnWidth(3, int(width * 0.9))
            self.tableWidget.setColumnWidth(4, int(width * 0.9))
            self.tableWidget.setColumnWidth(5, int(width * 0.6))
            self.tableWidget.setColumnWidth(6, int(width * 1.6))
            self.tableWidget.setColumnWidth(7, int(width * 1.6))
        else:
            self.tableWidget.setColumnWidth(1, int(width * 1.7))
            self.tableWidget.setColumnWidth(2, int(width * 1.6))
            self.tableWidget.setColumnWidth(3, int(width * 0.9))
            self.tableWidget.setColumnWidth(4, int(width * 0.6))
            self.tableWidget.setColumnWidth(5, int(width * 1.6))
            self.tableWidget.setColumnWidth(6, int(width * 1.6))

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

    # 设置页码
    def setPage(self, text):
        sqlite_util = SQLiteDatabase()
        try:
            # 查询总数更新分页器
            count = sqlite_util.count_data('cmbok_download_history',
                                           conditions={'name': f'%{text}%', 'type': self.type})
            pageNumber = math.ceil(count / 16)
            # 更新表格显示行数
            if count > 0 and count <= 16:
                self.tableWidget.setRowCount(count)
            elif count > 16:
                self.tableWidget.setRowCount(16)
            else:
                self.tableWidget.setRowCount(0)
            # 设置当前页码
            if pageNumber == 0:
                self.pager.setCurrentIndex(0)
            # 设置页数
            self.pager.setPageNumber(pageNumber)
            # 设置圆点数量
            self.pager.setVisibleNumber(10 if pageNumber > 10 else pageNumber)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('查询漫画下载记录异常')
        finally:
            sqlite_util.close()

    # 获取下载记录
    def getRecords(self, text, index):
        sqlite_util = SQLiteDatabase()
        try:
            # 清空表格内容
            self.tableWidget.clearContents()
            # 查询下载记录
            historys = sqlite_util.query_data('cmbok_download_history',
                                              conditions={'name': f'%{text}%', 'type': self.type},
                                              order_by='status ASC,start_time DESC,name ASC,chapter_name DESC',
                                              limit=16,
                                              offset=index * 16)

            # 添加表格数据
            for i, history in enumerate(historys):
                status_item = QTableWidgetItem(
                    '软件退出' if history.status == -3 else '无法下载' if history.status == -2 else '转换epub失败' if history.status == -1 else '下载中' if history.status == 1 else '等待中' if history.status == 2 else '已完成' if history.status == 3 else '下载失败')
                if history.status == -3 or history.status == -2 or history.status == -1 or history.status == 0:
                    status_item.setForeground(QBrush(QColor(253, 46, 86)))  # 红色字体
                elif history.status == 1:
                    status_item.setForeground(QBrush(QColor(64, 158, 215)))  # 蓝色字体
                elif history.status == 2:
                    status_item.setForeground(QBrush(QColor(198, 202, 219)))  # 灰色字体
                elif history.status == 3:
                    status_item.setForeground(QBrush(QColor(19, 210, 105)))  # 绿色字体

                self.tableWidget.setItem(i, 0, QTableWidgetItem(str(history.id)))
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
                else:
                    self.tableWidget.setItem(i, 3, status_item)
                    self.tableWidget.setCellWidget(i, 4, ring_widget)
                    self.tableWidget.setItem(i, 5, QTableWidgetItem(history.start_time))
                    self.tableWidget.setItem(i, 6, QTableWidgetItem(history.finish_time))

        except Exception:
            logging.info(traceback.format_exc())
            logging.info('查询下载记录异常')
        finally:
            sqlite_util.close()

    def createRing(self, process):
        ring_layout = QHBoxLayout()
        ring_layout.setAlignment(Qt.AlignCenter)
        ring = ProgressRing()
        # 设置进度环取值范围和当前值
        ring.setRange(0, 100)
        ring.setValue(int(process))
        # 调整进度环大小
        ring.setFixedSize(25, 25)
        # 调整厚度
        ring.setStrokeWidth(4)
        ring_layout.addWidget(ring)
        ring_widget = QWidget()
        ring_widget.setLayout(ring_layout)
        ring_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return ring_widget
# 下载窗口
