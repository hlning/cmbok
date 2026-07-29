import os

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QColor
from PyQt5.QtWidgets import QHBoxLayout, QListWidget, QFileDialog
from qfluentwidgets import MessageBoxBase, SubtitleLabel, PrimaryPushButton, CaptionLabel, PushButton, FluentIcon, \
    ListWidget, MessageBox, InfoBarIcon, InfoBarPosition, StateToolTip, LineEdit

from common.config import cfg
from service.tool_service import ConvertTool
from utils.utils_files_and_folders import is_valid_filename
from view.components.info_bar_tip import show_tip


# 自定义工具对话框：转PDF，合并PDF
class ToolMessageBox(MessageBoxBase):
    def __init__(self, type, parent=None):
        super().__init__(parent)

        self.stateTooltip = None
        self.type = type
        self.title = ''
        self.desc = ''
        self.convert_btn_txt = ''
        # 定义允许的文件格式
        self.allowed_extensions = []
        # 合并pdf保存的文件名称
        self.merge_file_name = ''
        # 转pdf
        if self.type == 1:
            self.title = '转PDF'
            self.desc = '支持DOCX、MOBI、EPUB、FB2、CBZ、SVG、TXT、图像'
            self.convert_btn_txt = '转换'
            self.allowed_extensions = ['.docx', '.mobi', '.epub', '.fb2', '.cbz', '.svg', '.txt',
                                       '.png', '.jpg', '.jpeg', '.bmp']
        elif self.type == 2:
            self.title = '合并PDF'
            self.desc = '支持PDF、DOCX、MOBI、EPUB、FB2、CBZ、SVG、TXT、图像'
            self.convert_btn_txt = '合并'
            self.allowed_extensions = ['.pdf', '.docx', '.mobi', '.epub', '.fb2', '.cbz', '.svg', '.txt',
                                       '.png', '.jpg', '.jpeg', '.bmp']
        elif self.type == 3:
            self.title = '转EPUB'
            self.desc = '支持PDF、DOCX、MOBI、EPUB、FB2、CBZ、SVG、TXT、图像'
            self.convert_btn_txt = '转换'
            self.allowed_extensions = ['.pdf', '.docx', '.mobi', '.fb2', '.cbz', '.svg', '.txt', '.png', '.jpg',
                                       '.jpeg', '.bmp']
        elif self.type == 4:
            self.title = '转DOC'
            self.desc = '支持PDF、MOBI、EPUB、FB2、CBZ、SVG、TXT、图像'
            self.convert_btn_txt = '转换'
            self.allowed_extensions = ['.pdf', '.mobi', '.epub', '.fb2', '.cbz', '.svg', '.txt', '.png', '.jpg',
                                       '.jpeg', '.bmp']
        elif self.type == 5:
            self.title = '合并EPUB'
            self.desc = '支持EPUB、DOCX、TXT、MD、HTML、RTF'
            self.convert_btn_txt = '合并'
            self.allowed_extensions = ['.epub', '.docx', '.txt', '.md', '.html', '.htm', '.rtf', '.odt']

        self.titleLabel = SubtitleLabel(self.title, self)
        self.descLabel = CaptionLabel(self.desc)

        self.chooseFileBtn = PrimaryPushButton('选择文件（支持多文件）')
        self.chooseFileBtn.clicked.connect(self.show_file_dialog)

        # 重写按钮
        self.convertButton = PrimaryPushButton(self.convert_btn_txt, self.buttonGroup)
        self.convertButton.clicked.connect(self.convert)
        self.buttonLayout.addWidget(self.convertButton, 1, Qt.AlignVCenter)

        self.closeButton = PushButton('取消', self.buttonGroup)
        self.closeButton.clicked.connect(self.closeWindow)
        self.buttonLayout.addWidget(self.closeButton, 1, Qt.AlignVCenter)

        # 上移、下移、删除按钮
        self.hBoxLayout = QHBoxLayout()
        self.hBoxLayout.setSpacing(2)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)  # 设置布局的边距

        self.upButton = PushButton(FluentIcon.UP, '上移')
        self.upButton.clicked.connect(self.move_up)
        self.downButton = PushButton(FluentIcon.DOWN, '下移')
        self.downButton.clicked.connect(self.move_down)
        self.delButton = PrimaryPushButton(FluentIcon.DELETE, '删除')
        self.delButton.clicked.connect(self.delete_item)

        self.hBoxLayout.addWidget(self.upButton)
        self.hBoxLayout.addWidget(self.downButton)
        self.hBoxLayout.addWidget(self.delButton)

        # 创建列表框，用于显示选择的文件
        self.list_widget = ListWidget()
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setMinimumHeight(350)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.chooseFileBtn)
        self.viewLayout.addWidget(self.list_widget)
        self.viewLayout.addLayout(self.hBoxLayout)
        self.list_widget.hide()
        self.upButton.hide()
        self.downButton.hide()
        self.delButton.hide()

        self.yesButton.hide()
        self.cancelButton.hide()

        self.widget.setMinimumWidth(450)

    # 上移
    def move_up(self):
        currentRow = self.list_widget.currentRow()
        if currentRow > 0:
            # 获取当前项并交换位置
            item = self.list_widget.takeItem(currentRow)
            self.list_widget.insertItem(currentRow - 1, item)
            self.list_widget.setCurrentRow(currentRow - 1)  # 重新选中上移后的项

    # 下移
    def move_down(self):
        currentRow = self.list_widget.currentRow()
        if currentRow < self.list_widget.count() - 1:
            # 获取当前项并交换位置
            item = self.list_widget.takeItem(currentRow)
            self.list_widget.insertItem(currentRow + 1, item)
            self.list_widget.setCurrentRow(currentRow + 1)  # 重新选中下移后的项

    # 删除选中行
    def delete_item(self):
        currentRow = self.list_widget.currentRow()
        if currentRow >= 0:
            self.list_widget.takeItem(currentRow)  # 删除选中的项

    # 选择文件
    def show_file_dialog(self):
        # 打开文件对话框，允许多选
        options = QFileDialog.Options()
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "所有文件 (*)", options=options)

        # 验证所选文件格式
        invalid_files = []

        # 清空列表
        if len(files) > 0:
            self.list_widget.clear()

        for file in files:
            if any(file.endswith(ext) for ext in self.allowed_extensions):
                self.list_widget.addItem(file)
            else:
                invalid_files.append(file)

        if self.list_widget.count() > 0:
            self.list_widget.show()
            self.upButton.show()
            self.downButton.show()
            self.delButton.show()

        # 如果有无效文件，显示提示框
        if invalid_files:
            w = MessageBox("无效文件", "以下文件格式不符合要求:\n" + "\n".join(invalid_files), self.parent())
            w.setClosableOnMaskClicked(True)
            w.cancelButton.hide()
            w.exec()

    # 禁用按钮
    def disabledBtn(self):
        self.chooseFileBtn.setDisabled(True)
        self.convertButton.setDisabled(True)
        self.closeButton.setDisabled(True)
        self.upButton.setDisabled(True)
        self.downButton.setDisabled(True)
        self.delButton.setDisabled(True)

    # 启用按钮
    def enabledBtn(self):
        self.chooseFileBtn.setDisabled(False)
        self.convertButton.setDisabled(False)
        self.closeButton.setDisabled(False)
        self.upButton.setDisabled(False)
        self.downButton.setDisabled(False)
        self.delButton.setDisabled(False)

    # 转换pdf 合并pdf
    def convert(self):
        file_count = self.list_widget.count()
        if file_count == 0:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择文件，o(￣▽￣)ｄ', self,
                     InfoBarPosition.TOP)
            return

        # 转 EPUB/DOC、合并 EPUB 依赖 pandoc，提前检测可用性
        if self.type in (3, 4, 5):
            try:
                import pypandoc
                pypandoc.get_pandoc_version()
            except Exception:
                MessageBox("温馨提示",
                           "未检测到 pandoc，转 EPUB/DOC 需要安装 pandoc 并加入系统 PATH。",
                           self.parent()).exec()
                return

        # 合并文件需要输入文件名称（合并PDF / 合并EPUB）
        if self.type in (2, 5):
            w = CustomMessageBox(self)
            if w.exec():
                self.merge_file_name = w.urlLineEdit.text()
                # 检查文件是否存在
                merge_ext = '.pdf' if self.type == 2 else '.epub'
                save_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{self.merge_file_name}{merge_ext}')
                if os.path.exists(save_path):
                    w = MessageBox("温馨提示",
                                   "文件已存在，继续合并则会覆盖已存在的文件",
                                   self.parent())
                    w.setClosableOnMaskClicked(True)
                    if not w.exec():
                        return
            else:
                return

        # 检测输出文件是否已存在，存在则确认覆盖（合并 PDF 已单独确认，跳过）
        if self.type in (1, 3, 4):
            existing = []
            save_folder = cfg.get(cfg.toolSaveFolder)
            for index in range(file_count):
                fp = self.list_widget.item(index).text()
                stem = os.path.splitext(os.path.basename(fp))[0]
                if self.type == 1:
                    out = os.path.join(save_folder, f'{stem}.pdf')
                elif self.type == 3:
                    out = os.path.join(save_folder, f'{stem}.epub')
                else:
                    out = os.path.join(save_folder, f'{stem}.docx')
                if os.path.exists(out):
                    existing.append(out)
            if existing:
                w = MessageBox("温馨提示",
                               "以下输出文件已存在，继续将覆盖：\n" + "\n".join(existing),
                               self.parent())
                w.setClosableOnMaskClicked(True)
                if not w.exec():
                    return

        # 禁用按钮，转换在子线程执行，UI 保持响应（不再弹"无法响应"预提示）
        self.disabledBtn()
        files = []
        for index in range(file_count):  # 遍历所有项
            item_text = self.list_widget.item(index).text()  # 获取每一项的文本
            files.append(item_text)  # 将文本添加到列表中

        self.bookSearch = ConvertTool(files, self.type, self.merge_file_name)
        self.bookSearch.process.connect(self.convertStart)
        self.bookSearch.finished.connect(self.convertFinish)
        self.bookSearch.start()

    # 开始转换
    def convertStart(self):
        self.stateTooltip = StateToolTip(f'正在{self.convert_btn_txt}', '请耐心等待~~', self)
        sh = self.stateTooltip.sizeHint()
        self.stateTooltip.move(max(0, self.width() // 2 - sh.width() // 2) - 120,
                               max(0, self.height() // 2 - sh.height() // 2))
        self.stateTooltip.show()

    # 转换完成
    def convertFinish(self, status, error_files):
        self.stateTooltip.setState(True)
        self.stateTooltip = None
        if status == 'finished' and len(error_files) == 0:
            w = MessageBox("温馨提示", f"{self.convert_btn_txt}完成o(*￣▽￣*)ブ", self)
        else:
            w = MessageBox("温馨提示", f"如下文件{self.convert_btn_txt}失败o(╥﹏╥)o\n" + "\n".join(error_files), self)

        w.yesButton.setText('打开文件夹')
        w.cancelButton.setText('确认')
        w.setClosableOnMaskClicked(True)
        if w.exec():
            QDesktopServices.openUrl(QUrl.fromLocalFile(cfg.get(cfg.toolSaveFolder)))

        # 启用按钮
        self.enabledBtn()

    # 关闭窗口
    def closeWindow(self):
        self.reject()


class CustomMessageBox(MessageBoxBase):
    """ Custom message box """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('合并文件', self)
        self.urlLineEdit = LineEdit(self)

        self.urlLineEdit.setPlaceholderText('请输入合并后的文件名称')
        self.urlLineEdit.setClearButtonEnabled(True)

        self.warningLabel = CaptionLabel("文件名称不能为空或含非法字符")
        self.warningLabel.setTextColor("#cf1010", QColor(255, 28, 32))

        # add widget to view layout
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.urlLineEdit)
        self.viewLayout.addWidget(self.warningLabel)
        self.warningLabel.hide()

        # change the text of button
        self.yesButton.setText('确定')
        self.cancelButton.setText('取消')

        self.widget.setMinimumWidth(350)

        # self.hideYesButton()

    def validate(self):
        """ Rewrite the virtual method """
        txt = self.urlLineEdit.text()
        isValid = txt is not None and is_valid_filename(txt)
        self.warningLabel.setHidden(isValid)
        self.urlLineEdit.setError(not isValid)
        return isValid
