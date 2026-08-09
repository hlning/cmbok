import json
import logging
import os
import shutil
import subprocess
import tempfile
import traceback

from PyQt5.QtCore import Qt, QUrl, QThread, QRectF, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QListWidget, QFileDialog, QWidget, QVBoxLayout, QDialog, QListWidgetItem
from qfluentwidgets import MessageBoxBase, SubtitleLabel, PrimaryPushButton, CaptionLabel, PushButton, FluentIcon, \
    ListWidget, MessageBox, InfoBarIcon, InfoBarPosition, StateToolTip, LineEdit, SpinBox, Slider, ImageLabel, \
    TransparentToolButton

from common.config import cfg
from service.tool_service import ConvertTool, TrimMarginTool
from utils.trim_margin import get_content_image_names, get_image_by_name, trim_image_whitespace, resize_for_zoom
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
        elif self.type == 6:
            self.title = '去白边'
            self.desc = '裁掉漫画图片内容外的空白（EPUB/MOBI，可放大适配屏幕）'
            self.convert_btn_txt = '预览调整'
            self.allowed_extensions = ['.epub', '.mobi']
            # 去白边参数（预览窗口可调，默认 245/0/100%）；底部「预览调整」按钮选中记录后进入预览
            self.trim_threshold = 245
            self.trim_padding = 0
            self.trim_zoom = 100

        self.titleLabel = SubtitleLabel(self.title, self)
        self.descLabel = CaptionLabel(self.desc)

        self.chooseFileBtn = PrimaryPushButton('选择文件（支持多文件）')
        self.chooseFileBtn.clicked.connect(self.show_file_dialog)

        # 重写按钮
        self.convertButton = PrimaryPushButton(self.convert_btn_txt, self.buttonGroup)
        self.convertButton.clicked.connect(self.convert)
        # 去白边：底部按钮改为进入预览（需选中记录），不走批量 convert
        if self.type == 6:
            self.convertButton.clicked.disconnect()
            self.convertButton.clicked.connect(self.openPreview)
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

    # 底部「预览调整」按钮：需先选中一条记录，再进入预览视图
    def openPreview(self):
        current = self.list_widget.currentItem()
        if current is None:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请先选择一条记录o(￣▽￣)ｄ', self, InfoBarPosition.TOP)
            return
        self.openPreviewWindow(current.text())

    # 打开独立预览调整窗口（确认/运用到其他文件后回填参数）
    def openPreviewWindow(self, file_path):
        files = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        dlg = PreviewDialog(file_path, files, self.trim_threshold, self.trim_padding, self.trim_zoom, self)
        if dlg.exec():
            self.trim_threshold = dlg.threshold
            self.trim_padding = dlg.padding
            self.trim_zoom = dlg.zoom

    # 选择文件
    def show_file_dialog(self):
        # 打开文件对话框，允许多选
        options = QFileDialog.Options()
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "所有文件 (*)", options=options)

        # 验证所选文件格式
        invalid_files = []

        # 追加到已选列表（不清空，支持多次选择累积）；重复文件自动去重
        existing = {self.list_widget.item(i).text() for i in range(self.list_widget.count())}
        duplicate_count = 0
        for file in files:
            if not any(file.endswith(ext) for ext in self.allowed_extensions):
                invalid_files.append(file)
                continue
            if file in existing:
                duplicate_count += 1
                continue
            self.list_widget.addItem(file)
            existing.add(file)

        if duplicate_count > 0:
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', f'已忽略 {duplicate_count} 个已选择的文件', self, InfoBarPosition.TOP)

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


class PreviewImageThread(QThread):
    """后台取预览图：解析可浏览的 epub 路径（mobi 经 calibre 转换到 dialog 持有的临时目录），
    收集全部内容图名 + 取首图，回传 (epub_path, names, first_image)。"""
    finished = pyqtSignal(str, list, object)  # epub_path, image_names, 首图(PIL Image 或 None)

    def __init__(self, file_path, mobi_tmp_dir=None):
        super().__init__()
        self.file_path = file_path
        self.mobi_tmp_dir = mobi_tmp_dir  # mobi 转换用临时目录（dialog 持有，线程不清理）

    def run(self):
        ext = os.path.splitext(self.file_path)[1].lower()
        try:
            if ext == '.epub':
                epub_path = self.file_path
            elif ext == '.mobi':
                calibrePath = cfg.get(cfg.calibrePath)
                calibre_bin = 'ebook-convert.exe' if os.name == 'nt' else 'ebook-convert'
                if not (calibrePath and os.path.isfile(calibrePath) and os.path.basename(calibrePath) == calibre_bin):
                    self.finished.emit('', [], None)
                    return
                if not self.mobi_tmp_dir:
                    self.finished.emit('', [], None)
                    return
                stem = os.path.splitext(os.path.basename(self.file_path))[0]
                tmp_epub = os.path.join(self.mobi_tmp_dir, f'{stem}.epub')
                subprocess.run([calibrePath, self.file_path, tmp_epub],
                               check=True, capture_output=True, timeout=120)
                epub_path = tmp_epub
            else:
                self.finished.emit('', [], None)
                return
            names = get_content_image_names(epub_path)
            first = get_image_by_name(epub_path, names[0]) if names else None
            self.finished.emit(epub_path, names, first)
        except Exception:
            logging.info(f'[去白边] 预览取图失败: {traceback.format_exc()}')
            self.finished.emit('', [], None)


class DevicePreviewWidget(QWidget):
    """设备边框预览：按设备分辨率 a×b 比例画屏幕边框，裁剪后图片在边框内按实际显示规则
    （注入的 max-width:100%;height:auto，不放大、超屏缩小、窄屏居中留白）渲染，
    调整阈值/边距/分辨率实时刷新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._dev_w = 1072
        self._dev_h = 1448
        self.setMinimumHeight(200)

    def setImage(self, pil_img, dev_w, dev_h):
        self._dev_w = max(1, int(dev_w))
        self._dev_h = max(1, int(dev_h))
        if pil_img is not None:
            self._pixmap = self._pilToPixmap(pil_img)
        self.update()

    @staticmethod
    def _pilToPixmap(pil_img):
        rgb = pil_img.convert('RGB')
        w, h = rgb.size
        qimg = QImage(rgb.tobytes('raw', 'RGB'), w, h, w * 3, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        # 实体设备边框（bezel）：屏幕外扩一圈深色圆角机身，按 dev 比例适配 widget 并预留 bezel 空间
        bezel = 10  # 机身边框宽度（像素）
        avail_w = max(1, w - bezel * 2)
        avail_h = max(1, h - bezel * 2)
        scale = min(avail_w / self._dev_w, avail_h / self._dev_h)
        box_w = self._dev_w * scale   # 屏幕宽
        box_h = self._dev_h * scale   # 屏幕高
        outer_w = box_w + bezel * 2
        outer_h = box_h + bezel * 2
        outer_x = (w - outer_w) / 2
        outer_y = (h - outer_h) / 2
        outer_rect = QRectF(outer_x, outer_y, outer_w, outer_h)
        screen_x = outer_x + bezel
        screen_y = outer_y + bezel
        screen_rect = QRectF(screen_x, screen_y, box_w, box_h)
        # 设备机身（深色圆角，像实体设备）
        painter.setPen(QPen(QColor(35, 35, 35), 1))
        painter.setBrush(QColor(60, 60, 60))
        painter.drawRoundedRect(outer_rect, 8, 8)
        # 屏幕（浅灰底）
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(245, 245, 245))
        painter.drawRect(screen_rect)
        # 图片（设备实际显示：max-width:100%, height:auto, 不放大）
        if self._pixmap is not None and not self._pixmap.isNull():
            iw = self._pixmap.width()
            ih = self._pixmap.height()
            if iw > 0:
                disp_w_px = min(iw, self._dev_w)       # 设备像素显示宽（不放大：图宽<=设备宽取图宽）
                disp_h_px = ih * disp_w_px / iw         # 等比高
                img_w = disp_w_px * scale               # 屏幕内像素宽
                img_h = disp_h_px * scale               # 屏幕内像素高
                img_x = screen_x + (box_w - img_w) / 2  # 水平居中
                if img_h <= box_h:
                    # 图片矮于设备：垂直居中，上下留白
                    img_y = screen_y + (box_h - img_h) / 2
                    painter.drawPixmap(QRectF(img_x, img_y, img_w, img_h),
                                       self._pixmap, QRectF(0, 0, iw, ih))
                else:
                    # 图片高于设备：垂直居中裁切，显示中间一屏
                    src_h = ih * box_h / img_h
                    src_y = (ih - src_h) / 2
                    painter.drawPixmap(QRectF(img_x, screen_y, img_w, box_h),
                                       self._pixmap, QRectF(0, src_y, iw, src_h))
        # 屏幕边线（屏幕与机身交界，细线增强分界，最后画确保始终可见）
        painter.setPen(QPen(QColor(30, 30, 30), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(screen_rect)


class PresetSelectDialog(MessageBoxBase):
    """选择已保存的去白边预设；列表支持删除（删除即时生效）。"""

    def __init__(self, presets, parent=None):
        super().__init__(parent)
        self.presets = presets  # 父级 list 引用，删除直接改它
        self.selected = None
        self.titleLabel = SubtitleLabel('选择预设', self)
        self.list_widget = ListWidget(self)
        self.list_widget.setMinimumHeight(220)
        for p in presets:
            self.list_widget.addItem(QListWidgetItem(self._format(p)))
        self.delBtn = PrimaryPushButton(FluentIcon.DELETE, '删除选中', self)
        self.delBtn.clicked.connect(self._deleteSelected)
        topRow = QHBoxLayout()
        topRow.addWidget(self.titleLabel)
        topRow.addStretch()
        topRow.addWidget(self.delBtn)
        self.viewLayout.addLayout(topRow)
        self.viewLayout.addWidget(self.list_widget)
        self.yesButton.setText('应用')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(440)

    @staticmethod
    def _format(p):
        return (f"{p.get('name', '')}  （阈值{p.get('threshold', 245)} / "
                f"边距{p.get('padding', 0)} / 放大{p.get('zoom', 100)}% / "
                f"{p.get('width', 1072)}x{p.get('height', 1448)}）")

    def _deleteSelected(self):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        self.list_widget.takeItem(r)
        if 0 <= r < len(self.presets):
            self.presets.pop(r)

    def accept(self):
        r = self.list_widget.currentRow()
        if 0 <= r < len(self.presets):
            self.selected = self.presets[r]
        super().accept()


class PresetSaveDialog(MessageBoxBase):
    """输入名称保存去白边预设。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('保存预设', self)
        self.urlLineEdit = LineEdit(self)
        self.urlLineEdit.setPlaceholderText('请输入预设名称')
        self.urlLineEdit.setClearButtonEnabled(True)
        self.warningLabel = CaptionLabel("名称不能为空或含非法字符")
        self.warningLabel.setTextColor("#cf1010", QColor(255, 28, 32))
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.urlLineEdit)
        self.viewLayout.addWidget(self.warningLabel)
        self.warningLabel.hide()
        self.yesButton.setText('保存')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(350)

    def validate(self):
        txt = self.urlLineEdit.text()
        isValid = bool(txt) and txt.strip() != '' and is_valid_filename(txt.strip())
        self.warningLabel.setHidden(isValid)
        self.urlLineEdit.setError(not isValid)
        return isValid


class PreviewDialog(QDialog):
    """去白边预览调整窗口：原图/设备边框预览并排，阈值边距滑块，设备分辨率+预设管理。"""

    def __init__(self, file_path, all_files, threshold, padding, zoom, parent=None):
        super().__init__(parent)
        # 系统标题栏：最小化/最大化/关闭，去掉 QDialog 默认的「？」帮助按钮
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle('预览调整 - 去白边')
        self.resize(900, 720)
        self.setMinimumSize(680, 520)
        self.file_path = file_path
        self.all_files = list(all_files)
        self.threshold = threshold
        self.padding = padding
        self.zoom = zoom
        self.previewPilImg = None
        self.stateTooltip = None
        self.trimTool = None
        # 翻页浏览状态：当前文件内多张图片，白边各异，供挑选代表性图调参
        self.preview_epub_path = ''    # 可浏览的 epub 路径（epub=原文件，mobi=转换后临时 epub）
        self.preview_image_names = []  # 内容图 zip 条目名列表
        self.preview_index = 0
        ext = os.path.splitext(file_path)[1].lower()
        self._mobi_tmp_dir = tempfile.mkdtemp(prefix='preview_mobi_') if ext == '.mobi' else None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        # 预设 + 设备分辨率行
        self.presets = self._load_presets()
        topRow = QHBoxLayout()
        self.presetBtn = PushButton('选择预设', self)
        self.presetBtn.clicked.connect(self.onSelectPreset)
        self.presetNameLabel = CaptionLabel('自定义', self)
        topRow.addWidget(self.presetBtn)
        topRow.addWidget(CaptionLabel('当前预设：', self))
        topRow.addWidget(self.presetNameLabel)
        topRow.addSpacing(24)
        topRow.addWidget(CaptionLabel('设备分辨率', self))
        self.widthBox = SpinBox(self)
        self.widthBox.setRange(100, 4000)
        self.widthBox.setValue(1072)
        self.widthBox.setFixedWidth(130)
        self.heightBox = SpinBox(self)
        self.heightBox.setRange(100, 4000)
        self.heightBox.setValue(1448)
        self.heightBox.setFixedWidth(130)
        self.widthBox.valueChanged.connect(self.updatePreview)
        self.heightBox.valueChanged.connect(self.updatePreview)
        topRow.addWidget(self.widthBox)
        topRow.addWidget(CaptionLabel('×', self))
        topRow.addWidget(self.heightBox)
        # 保存预设（颜色同确认按钮，置于设备分辨率右侧）
        self.savePresetBtn = PrimaryPushButton('保存预设', self)
        self.savePresetBtn.clicked.connect(self.onSavePreset)
        topRow.addWidget(self.savePresetBtn)
        topRow.addStretch()
        v.addLayout(topRow)

        # 预览区：原图（左右翻页按钮）/ 设备边框预览 并排，随窗口缩放
        self.prevBtn = TransparentToolButton(FluentIcon.LEFT_ARROW, self)
        self.prevBtn.setToolTip('上一页')
        self.prevBtn.setEnabled(False)
        self.prevBtn.clicked.connect(self.prevImage)
        self.nextBtn = TransparentToolButton(FluentIcon.RIGHT_ARROW, self)
        self.nextBtn.setToolTip('下一页')
        self.nextBtn.setEnabled(False)
        self.nextBtn.clicked.connect(self.nextImage)
        self.origLabel = ImageLabel(self)
        self.devicePreview = DevicePreviewWidget(self)
        self.origCap = CaptionLabel(f'原图 - {os.path.basename(file_path)}', self)
        self.origCap.setAlignment(Qt.AlignHCenter)
        self.trimCap = CaptionLabel('设备预览', self)
        self.trimCap.setAlignment(Qt.AlignHCenter)
        orig_v = QVBoxLayout()
        orig_v.addWidget(self.origLabel, 1, Qt.AlignCenter)
        orig_v.addWidget(self.origCap)
        origRow = QHBoxLayout()
        origRow.addWidget(self.prevBtn, 0, Qt.AlignVCenter)
        origRow.addLayout(orig_v, 1)
        origRow.addWidget(self.nextBtn, 0, Qt.AlignVCenter)
        trim_v = QVBoxLayout()
        trim_v.addWidget(self.devicePreview, 1)
        trim_v.addWidget(self.trimCap)
        previewRow = QHBoxLayout()
        previewRow.addLayout(origRow, 1)
        previewRow.addLayout(trim_v, 1)
        v.addLayout(previewRow, 1)

        # 阈值/边距/放大：Slider + SpinBox 联动
        self.thresholdSlider = Slider(Qt.Horizontal, self)
        self.thresholdSlider.setRange(0, 255)
        self.thresholdSlider.setValue(threshold)
        self.thresholdBox = SpinBox(self)
        self.thresholdBox.setRange(0, 255)
        self.thresholdBox.setValue(threshold)
        self.thresholdBox.setFixedWidth(130)
        self.paddingSlider = Slider(Qt.Horizontal, self)
        self.paddingSlider.setRange(0, 50)
        self.paddingSlider.setValue(padding)
        self.paddingBox = SpinBox(self)
        self.paddingBox.setRange(0, 50)
        self.paddingBox.setValue(padding)
        self.paddingBox.setFixedWidth(130)
        self.zoomSlider = Slider(Qt.Horizontal, self)
        self.zoomSlider.setRange(100, 300)
        self.zoomSlider.setValue(zoom)
        self.zoomBox = SpinBox(self)
        self.zoomBox.setRange(100, 300)
        self.zoomBox.setValue(zoom)
        self.zoomBox.setFixedWidth(130)
        self.zoomBox.setSuffix('%')
        self.thresholdSlider.valueChanged.connect(self.thresholdBox.setValue)
        self.thresholdBox.valueChanged.connect(self.thresholdSlider.setValue)
        self.thresholdBox.valueChanged.connect(self.updatePreview)
        self.paddingSlider.valueChanged.connect(self.paddingBox.setValue)
        self.paddingBox.valueChanged.connect(self.paddingSlider.setValue)
        self.paddingBox.valueChanged.connect(self.updatePreview)
        self.zoomSlider.valueChanged.connect(self.zoomBox.setValue)
        self.zoomBox.valueChanged.connect(self.zoomSlider.setValue)
        self.zoomBox.valueChanged.connect(self.updatePreview)
        paramRow = QHBoxLayout()
        paramRow.addWidget(CaptionLabel('白边阈值', self))
        paramRow.addWidget(self.thresholdSlider, 1)
        paramRow.addWidget(self.thresholdBox)
        paramRow.addSpacing(24)
        paramRow.addWidget(CaptionLabel('保留边距', self))
        paramRow.addWidget(self.paddingSlider, 1)
        paramRow.addWidget(self.paddingBox)
        paramRow.addSpacing(24)
        paramRow.addWidget(CaptionLabel('图片放大', self))
        paramRow.addWidget(self.zoomSlider, 1)
        paramRow.addWidget(self.zoomBox)
        v.addLayout(paramRow)

        # 按钮：确认 / 运用到其他文件 / 取消，全部靠右
        btnRow = QHBoxLayout()
        self.confirmBtn = PrimaryPushButton('确认（处理当前文件）', self)
        self.applyAllBtn = PrimaryPushButton('运用到其他文件', self)
        self.cancelBtn = PushButton('取消', self)
        self.confirmBtn.clicked.connect(self.onConfirm)
        self.applyAllBtn.clicked.connect(self.onApplyAll)
        self.cancelBtn.clicked.connect(self.reject)
        btnRow.addStretch()
        btnRow.addWidget(self.confirmBtn)
        btnRow.addWidget(self.applyAllBtn)
        btnRow.addWidget(self.cancelBtn)
        v.addLayout(btnRow)

        # 后台取预览图（含 mobi 转换 + 收集全部图片名）
        self.trimCap.setText('正在获取预览图...')
        self.previewThread = PreviewImageThread(file_path, self._mobi_tmp_dir)
        self.previewThread.finished.connect(self.onPreviewReady)
        self.previewThread.start()

    # 预览图就绪（epub 路径 + 全部图片名 + 首图）
    def onPreviewReady(self, epub_path, names, img):
        self.preview_epub_path = epub_path
        self.preview_image_names = list(names) if names else []
        self.preview_index = 0
        if not self.preview_image_names or img is None:
            self.trimCap.setText('预览图获取失败（mobi 需配置 Calibre）')
            self._updateNavButtons()
            return
        self.previewPilImg = img
        self._renderImages()
        self._updateOrigCap()
        self._updateNavButtons()

    # 翻页：上一页/下一页切换当前文件内的图片（白边不同，供挑选代表性图调参）
    def prevImage(self):
        if self.preview_index > 0:
            self._showImage(self.preview_index - 1)

    def nextImage(self):
        if self.preview_index < len(self.preview_image_names) - 1:
            self._showImage(self.preview_index + 1)

    def _showImage(self, index):
        if not self.preview_image_names or not (0 <= index < len(self.preview_image_names)):
            return
        name = self.preview_image_names[index]
        img = get_image_by_name(self.preview_epub_path, name)
        if img is None:
            self.trimCap.setText('图片加载失败')
            self._updateNavButtons()
            return
        self.preview_index = index
        self.previewPilImg = img
        self._renderImages()
        self._updateOrigCap()
        self._updateNavButtons()

    def _updateOrigCap(self):
        if not self.previewPilImg or not self.preview_image_names:
            return
        total = len(self.preview_image_names)
        w, h = self.previewPilImg.size
        self.origCap.setText(f'原图 {self.preview_index + 1}/{total} {w}x{h} - {os.path.basename(self.file_path)}')

    def _updateNavButtons(self):
        n = len(self.preview_image_names)
        self.prevBtn.setEnabled(n > 0 and self.preview_index > 0)
        self.nextBtn.setEnabled(n > 0 and self.preview_index < n - 1)

    # 预览区可用高度（窗口高度减去参数行、按钮行、边距）
    def _previewHeight(self):
        return max(200, self.height() - 170)

    # 渲染原图 + 设备预览（窗口尺寸变化或首次取图时调用）
    def _renderImages(self):
        if not self.previewPilImg:
            return
        h = self._previewHeight()
        self._setImage(self.origLabel, self.previewPilImg, h)
        self._renderTrimmed()

    # 仅刷新设备预览（滑块/分辨率变化时调用，原图不动）
    def updatePreview(self):
        if not self.previewPilImg:
            return
        self._renderTrimmed()

    def _renderTrimmed(self):
        dev_w = self.widthBox.value()
        dev_h = self.heightBox.value()
        zoom = self.zoomBox.value()
        trimmed = trim_image_whitespace(self.previewPilImg, self.thresholdBox.value(), self.paddingBox.value())
        base = trimmed if trimmed is not None else self.previewPilImg
        resized = resize_for_zoom(base, zoom, dev_w, dev_h)
        self.devicePreview.setImage(resized, dev_w, dev_h)
        fw, fh = resized.size
        if trimmed is None and resized is base:
            self.trimCap.setText(f'设备 {dev_w}x{dev_h} | 放大{zoom}%（无明显白边，显示原图）')
        elif zoom > 100 and resized is base:
            self.trimCap.setText(f'设备 {dev_w}x{dev_h} | 放大{zoom}%（已达屏幕上限，未放大）| {fw}x{fh}')
        else:
            self.trimCap.setText(f'设备 {dev_w}x{dev_h} | 放大{zoom}% | {fw}x{fh}')
        # 关闭临时 PIL 对象（不关 self.previewPilImg）
        if resized is not base:
            resized.close()
        if trimmed is not None:
            trimmed.close()

    # PIL Image -> ImageLabel 显示（缩放到指定高度）
    def _setImage(self, label, pil_img, h):
        from PIL import Image
        h = max(1, h)
        scale = h / pil_img.height
        new_w = max(1, int(pil_img.width * scale))
        small = pil_img.convert('RGB').resize((new_w, h), Image.LANCZOS)
        qimg = QImage(small.tobytes('raw', 'RGB'), new_w, h, new_w * 3, QImage.Format_RGB888).copy()
        label.setImage(qimg)

    # 窗口缩放时重新渲染预览图
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._renderImages()

    # 关闭/确认/取消时清理 mobi 转换的临时目录（done 覆盖 accept/reject，closeEvent 覆盖 X 按钮）
    def done(self, result):
        if self._mobi_tmp_dir:
            shutil.rmtree(self._mobi_tmp_dir, ignore_errors=True)
            self._mobi_tmp_dir = None
        super().done(result)

    def closeEvent(self, event):
        if self._mobi_tmp_dir:
            shutil.rmtree(self._mobi_tmp_dir, ignore_errors=True)
            self._mobi_tmp_dir = None
        super().closeEvent(event)

    # 处理前检查输出文件覆盖
    def _checkOverwrite(self, files):
        existing = []
        for fp in files:
            stem = os.path.splitext(os.path.basename(fp))[0]
            ext = os.path.splitext(fp)[1]
            out = os.path.join(os.path.dirname(fp), f'{stem}_去白边{ext}')
            if os.path.exists(out):
                existing.append(out)
        if existing:
            w = MessageBox("温馨提示", "以下输出文件已存在，继续将覆盖：\n" + "\n".join(existing), self)
            w.setClosableOnMaskClicked(True)
            if not w.exec():
                return False
        return True

    # 启动去白边处理
    def _startProcess(self, files):
        self._src_files = files
        self.threshold = self.thresholdBox.value()
        self.padding = self.paddingBox.value()
        self.zoom = self.zoomBox.value()
        self.confirmBtn.setEnabled(False)
        self.applyAllBtn.setEnabled(False)
        self.cancelBtn.setEnabled(False)
        self.trimTool = TrimMarginTool(files, self.threshold, self.padding,
                                       self.zoom, self.widthBox.value(), self.heightBox.value())
        self.trimTool.process.connect(self._onProcessStart)
        self.trimTool.progress.connect(self._onProcessProgress)
        self.trimTool.finished.connect(self._onProcessFinished)
        self.trimTool.start()

    def _onProcessStart(self):
        self.stateTooltip = StateToolTip('正在去白边', '请耐心等待~~', self)
        sh = self.stateTooltip.sizeHint()
        self.stateTooltip.move(max(0, self.width() // 2 - sh.width() // 2),
                               max(0, self.height() // 2 - sh.height() // 2))
        self.stateTooltip.show()

    def _onProcessProgress(self, current, total, name):
        if self.stateTooltip:
            self.stateTooltip.setContent(f'正在处理 {current}/{total}：{name}')

    def _onProcessFinished(self, status, error_files):
        if self.stateTooltip:
            self.stateTooltip.setState(True)
            self.stateTooltip = None
        if status == 'finished' and len(error_files) == 0:
            w = MessageBox("温馨提示", "去白边完成o(*￣▽￣*)ブ", self)
        else:
            w = MessageBox("温馨提示", "如下文件去白边失败o(╥﹏╥)o\n" + "\n".join(error_files), self)
        w.yesButton.setText('打开文件夹')
        w.cancelButton.setText('确认')
        w.setClosableOnMaskClicked(True)
        if w.exec():
            src = self._src_files[0] if getattr(self, '_src_files', None) else None
            folder = os.path.dirname(src) if src else ''
            if folder:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.accept()

    # 确认：处理当前文件
    def onConfirm(self):
        if not self._checkOverwrite([self.file_path]):
            return
        self._startProcess([self.file_path])

    # 运用到其他文件：处理列表全部文件
    def onApplyAll(self):
        if not self._checkOverwrite(self.all_files):
            return
        self._startProcess(list(self.all_files))

    # ===== 预设管理 =====
    def _load_presets(self):
        try:
            data = json.loads(cfg.get(cfg.trim_presets) or '[]')
            if isinstance(data, list):
                return data
        except Exception:
            logging.info(f'[去白边] 读取预设失败: {traceback.format_exc()}')
        return []

    def _save_presets(self, presets):
        try:
            cfg.set(cfg.trim_presets, json.dumps(presets, ensure_ascii=False))
            self.presets = presets
        except Exception:
            logging.info(f'[去白边] 保存预设失败: {traceback.format_exc()}')

    def _applyPreset(self, preset):
        for box in (self.thresholdBox, self.paddingBox, self.zoomBox, self.widthBox, self.heightBox):
            box.blockSignals(True)
        self.thresholdBox.setValue(preset.get('threshold', 245))
        self.thresholdSlider.setValue(preset.get('threshold', 245))
        self.paddingBox.setValue(preset.get('padding', 0))
        self.paddingSlider.setValue(preset.get('padding', 0))
        self.zoomBox.setValue(preset.get('zoom', 100))
        self.zoomSlider.setValue(preset.get('zoom', 100))
        self.widthBox.setValue(preset.get('width', 1072))
        self.heightBox.setValue(preset.get('height', 1448))
        for box in (self.thresholdBox, self.paddingBox, self.zoomBox, self.widthBox, self.heightBox):
            box.blockSignals(False)
        self.presetNameLabel.setText(preset.get('name', '自定义'))
        self.updatePreview()

    def onSelectPreset(self):
        if not self.presets:
            show_tip(InfoBarIcon.INFORMATION, '温馨提示', '暂无已保存预设，可调整参数后点击「保存预设」', self,
                     InfoBarPosition.TOP)
            return
        dlg = PresetSelectDialog(self.presets, self)
        accepted = dlg.exec()
        # 删除操作即时生效（无论应用/取消都回写）
        self._save_presets(self.presets)
        if accepted and dlg.selected is not None:
            self._applyPreset(dlg.selected)

    def onSavePreset(self):
        dlg = PresetSaveDialog(self)
        if not dlg.exec():
            return
        name = dlg.urlLineEdit.text().strip()
        existing = next((p for p in self.presets if p.get('name') == name), None)
        if existing:
            w = MessageBox("温馨提示", f"预设「{name}」已存在，是否覆盖？", self)
            w.setClosableOnMaskClicked(True)
            if not w.exec():
                return
            self.presets.remove(existing)
        preset = {
            'name': name,
            'threshold': self.thresholdBox.value(),
            'padding': self.paddingBox.value(),
            'zoom': self.zoomBox.value(),
            'width': self.widthBox.value(),
            'height': self.heightBox.value(),
        }
        self.presets.append(preset)
        self._save_presets(self.presets)
        self.presetNameLabel.setText(name)
        show_tip(InfoBarIcon.INFORMATION, '保存成功', f'预设「{name}」已保存', self, InfoBarPosition.TOP)
