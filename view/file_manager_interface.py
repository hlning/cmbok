# coding:utf-8
import os
import platform
import shutil
import subprocess

from PyQt5.QtCore import Qt, QDir
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileSystemModel,
    QWidget, QMessageBox, QHBoxLayout, QAction, QHeaderView
)
from qfluentwidgets import TreeView, FluentIcon, Action, RoundMenu, InfoBarIcon, InfoBarPosition, MessageBox, \
    MessageBoxBase, SubtitleLabel, LineEdit, CaptionLabel

from common.config import cfg
from view.components.info_bar_tip import show_tip


class CustomFileSystemModel(QFileSystemModel):
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                # 设置表头为中文
                if section == 0:
                    return "名称"
                elif section == 1:
                    return "大小"
                elif section == 2:
                    return "类型"
                elif section == 3:
                    return "修改时间"
        return super().headerData(section, orientation, role)


class FileManagerInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('FileManagerInterface')

        # 当前剪贴板文件路径
        self.clipboard = None
        self.clipboard_type = None  # 用于区分复制和剪切
        self.tree_index = None

        self.hBoxLayout = QHBoxLayout(self)

        self.treeView = TreeView(self)

        self.set_styles()

        # 快捷键支持
        self.create_shortcuts()

        download_path = cfg.get(cfg.downloadFolder)
        self.model = CustomFileSystemModel()
        self.model.setRootPath(download_path)
        self.treeView.setModel(self.model)
        self.treeView.setRootIndex(self.model.index(download_path))
        # 表头列自适应：名称列随窗口拉伸，其余列按内容宽度
        header = self.treeView.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        # 右键菜单
        self.treeView.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treeView.customContextMenuRequested.connect(self.show_context_menu)
        # 连接选中变化信号
        self.treeView.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self.treeView.setBorderVisible(True)
        self.treeView.setBorderRadius(8)

        self.hBoxLayout.addWidget(self.treeView, 1)
        self.hBoxLayout.setContentsMargins(50, 30, 50, 30)

    def contextMenuEvent(self, event):
        menu = RoundMenu()
        menu.addAction(
            Action(FluentIcon.FOLDER, '创建文件夹', triggered=lambda: self.create_folder(True)))
        menu.addAction(
            Action(FluentIcon.FULL_SCREEN, '展开所有', triggered=self.treeView.expandAll))
        menu.addAction(
            Action(FluentIcon.BACK_TO_WINDOW, '收起所有', triggered=self.treeView.collapseAll))
        # 显示右键菜单
        menu.exec_(event.globalPos())

    def on_selection_changed(self):
        self.tree_index = self.treeView.currentIndex()

    # 快捷键
    def create_shortcuts(self):
        # 创建快捷键
        copy_action = QAction("复制", self)
        copy_action.triggered.connect(lambda: self.copy_or_cut_item('copy'))
        copy_action.setShortcut("Ctrl+C")
        self.addAction(copy_action)

        cut_action = QAction("剪切", self)
        cut_action.triggered.connect(lambda: self.copy_or_cut_item('cut'))
        cut_action.setShortcut("Ctrl+X")
        self.addAction(cut_action)

        paste_action = QAction("粘贴", self)
        paste_action.triggered.connect(self.paste_item)
        paste_action.setShortcut("Ctrl+V")
        self.addAction(paste_action)

        delete_action = QAction("删除", self)
        delete_action.triggered.connect(self.delete_item)
        delete_action.setShortcut("Delete")
        self.addAction(delete_action)

    def set_styles(self):
        # 设置表头的样式，使其居中
        header = self.treeView.header()
        header.setStyleSheet("""
                   QHeaderView::section {
                       text-align: center;
                       padding:10px 0px -5px 20px;
                   }
               """)
        # 设置表头单元格的垂直居中
        self.treeView.header().setDefaultAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

    def show_context_menu(self, position):
        index = self.treeView.indexAt(position)
        if not index.isValid():
            return

        menu = RoundMenu()

        # 逐个添加动作，Action 继承自 QAction，接受 FluentIconBase 类型的图标
        # 检查选中的项是否为文件夹
        if os.path.isdir(self.model.filePath(index)):
            menu.addAction(Action(FluentIcon.FOLDER, '创建文件夹', triggered=self.create_folder))
        menu.addAction(
            Action(FluentIcon.FOLDER, '打开所在目录', triggered=self.open_dir))
        menu.addAction(
            Action(FluentIcon.COPY, '复制', triggered=lambda: self.copy_or_cut_item('copy'), shortcut='Ctrl+C'))
        menu.addAction(
            Action(FluentIcon.CUT, '剪切', triggered=lambda: self.copy_or_cut_item('cut'), shortcut='Ctrl+X'))
        menu.addAction(Action(FluentIcon.PASTE, '粘贴', triggered=self.paste_item, shortcut='Ctrl+V'))
        menu.addAction(Action(FluentIcon.DELETE, '删除', triggered=self.delete_item, shortcut='Delete'))

        menu.exec_(self.treeView.viewport().mapToGlobal(position))

    # 创建文件夹
    def create_folder(self, flag):
        if not flag:
            index = self.tree_index
            if index is None or not index.isValid():
                show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一个文件夹！', self,
                         InfoBarPosition.TOP)
                return
            path = self.model.filePath(index)
        else:
            path = cfg.get(cfg.downloadFolder)

        w = CustomMessageBox(self)
        if w.exec():
            folder_name = w.urlLineEdit.text()
            new_folder_path = os.path.join(path, folder_name)

            try:
                os.makedirs(new_folder_path)
                show_tip(InfoBarIcon.INFORMATION, '温馨提示', '创建成功', self,
                         InfoBarPosition.TOP)
            except Exception as e:
                show_tip(InfoBarIcon.ERROR, '温馨提示', str(e), self,
                         InfoBarPosition.TOP)

    def open_containing_folder(self, path):
        """
        打开指定路径所在的文件夹。

        如果路径是一个文件，则打开该文件所在的目录，并选中该文件。
        如果路径是一个文件夹，则直接打开该文件夹。

        Args:
            path (str): 要打开的文件夹或文件路径。
        """
        # 确保路径是绝对路径，这样可以避免一些潜在的问题
        path = os.path.abspath(path)

        if platform.system() == "Windows":
            # Windows 系统
            # 'explorer /select,"<path>"' 命令用于打开包含文件的文件夹并选中该文件。
            # 如果 path 是一个文件夹，它会直接打开该文件夹。
            try:
                # 使用 os.path.normpath 规范化路径，避免出现问题。
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            except FileNotFoundError:
                print(f"错误：找不到路径: {path}")
        elif platform.system() == "Darwin":
            # macOS 系统
            # 'open -R <path>' 命令用于在 Finder 中显示文件或文件夹。
            try:
                subprocess.Popen(["open", "-R", path])
            except FileNotFoundError:
                print(f"错误：找不到路径: {path}")
        else:  # Linux
            # Linux 系统
            # 尝试使用常见的 Linux 文件管理器打开文件夹。
            # 如果找不到任何文件管理器，则显示错误信息。
            try:
                subprocess.Popen(["xdg-open", QDir.toNativeSeparators(os.path.dirname(path))])  # 先尝试打开目录
            except FileNotFoundError:
                try:
                    subprocess.Popen(["nautilus", QDir.toNativeSeparators(os.path.dirname(path))])
                except FileNotFoundError:
                    try:
                        subprocess.Popen(["thunar", QDir.toNativeSeparators(os.path.dirname(path))])
                    except FileNotFoundError:
                        try:
                            subprocess.Popen(["pcmanfm", QDir.toNativeSeparators(os.path.dirname(path))])
                        except FileNotFoundError:
                            print("Error: No known file manager found.")
            except OSError:
                print("Error: xdg-open command failed.")

    # 打开所在目录
    def open_dir(self):
        current_index = self.treeView.currentIndex()
        if not current_index.isValid():
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一个文件或文件夹(*￣︶￣)', self,
                     InfoBarPosition.TOP)
            return
        target_path = self.model.filePath(current_index)
        self.open_containing_folder(target_path)

    # 复制or剪切
    def copy_or_cut_item(self, clipboard_type):
        index = self.tree_index
        if index is None or not index.isValid():
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一个文件或文件夹(*￣︶￣)', self,
                     InfoBarPosition.TOP)
            return

        self.clipboard = self.model.filePath(self.tree_index)  # 保存要复制或剪切的文件路径
        self.clipboard_type = clipboard_type
        show_tip(InfoBarIcon.INFORMATION, '温馨提示', ('复制' if clipboard_type == 'copy' else '剪切') + '成功', self,
                 InfoBarPosition.TOP)

    # 粘贴
    def paste_item(self):
        if self.clipboard is None:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '没有文件被复制或剪切', self,
                     InfoBarPosition.TOP)
            return

        current_index = self.treeView.currentIndex()
        if not current_index.isValid():
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一个文件或文件夹(*￣︶￣)', self,
                     InfoBarPosition.TOP)
            return
        target_path = self.model.filePath(current_index)

        try:
            if os.path.isdir(self.clipboard):
                target_folder = os.path.join(target_path, os.path.basename(self.clipboard))
                if self.clipboard_type == 'copy':
                    shutil.copytree(self.clipboard, target_folder)  # 复制文件夹
                else:
                    shutil.move(self.clipboard, target_folder)  # 复制文件夹
            else:
                if self.clipboard_type == 'copy':
                    shutil.copy2(self.clipboard, target_path)  # 复制文件
                else:
                    shutil.move(self.clipboard, target_path)  # 复制文件
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '粘贴成功', self,
                     InfoBarPosition.TOP)
        except Exception as e:
            show_tip(InfoBarIcon.ERROR, '温馨提示', str(e), self,
                     InfoBarPosition.TOP)

    # 删除
    def delete_item(self):
        index = self.tree_index
        if index is None or not index.isValid():
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一个文件或文件夹(*￣︶￣)', self,
                     InfoBarPosition.TOP)
            return

        file_path = self.model.filePath(index)  # 获取文件路径

        # 确认删除
        w = MessageBox("确认删除", f"您确定要删除 '{file_path}' 吗?", self)

        if w.exec():
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)  # 删除文件夹
                else:
                    os.remove(file_path)  # 删除文件
                self.model.remove(index)  # 更新视图
                show_tip(InfoBarIcon.INFORMATION, '温馨提示', '删除成功', self,
                         InfoBarPosition.TOP)
            except Exception as e:
                show_tip(InfoBarIcon.ERROR, '温馨提示', str(e), self,
                         InfoBarPosition.TOP)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                source_path = url.toLocalFile()
                target_index = self.treeView.indexAt(event.pos())
                target_path = self.model.filePath(target_index)

                # 进行复制操作
                try:
                    if os.path.isdir(source_path):
                        target_folder = os.path.join(target_path, os.path.basename(source_path))
                        shutil.copytree(source_path, target_folder)  # 复制文件夹
                    else:
                        shutil.copy2(source_path, target_path)  # 复制文件
                except Exception as e:
                    QMessageBox.critical(self, "错误", str(e))
                self.model.refresh()  # 刷新模型以更新视图
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()


# 自定义对话框
class CustomMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('添加文件夹', self)
        self.urlLineEdit = LineEdit(self)

        self.urlLineEdit.setPlaceholderText('请输入文件夹名称')
        self.urlLineEdit.setClearButtonEnabled(True)

        self.warningLabel = CaptionLabel()
        self.warningLabel.setTextColor("#cf1010", QColor(255, 28, 32))

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.urlLineEdit)
        self.viewLayout.addWidget(self.warningLabel)
        self.warningLabel.hide()

        self.yesButton.setText('确定')
        self.cancelButton.setText('取消')

        self.widget.setMinimumWidth(350)

    def validate(self):
        name = self.urlLineEdit.text()
        isValid = True
        if name == '' or name is None:
            self.warningLabel.setText("文件夹名称不能为空")
            isValid = False

        self.warningLabel.setHidden(isValid)
        self.urlLineEdit.setError(not isValid)
        return isValid
