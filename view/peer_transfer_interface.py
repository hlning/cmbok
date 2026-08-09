# coding:utf-8
"""在线传书页面（电脑端前台）。

两张卡片：传书到手机 / 从手机接收。后台对接 service.peer_transfer_service.peerTransfer。
- 传书到手机：选文件(QFileDialog 多选) -> 发现手机 -> 选对端 -> send_book -> StateToolTip 进度。
- 从手机接收：开启接收(enter_receive_mode) -> incomingOffer 信号弹接受框 -> respond_to_offer。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog)
from qfluentwidgets import (ScrollArea, ElevatedCardWidget, PushButton,
                            PrimaryPushButton, SubtitleLabel, BodyLabel,
                            CaptionLabel, ComboBox, StateToolTip, InfoBar,
                            MessageBoxBase, LineEdit, TransparentToolButton,
                            FluentIcon)

from common.config import cfg
from common.style_sheet import StyleSheet
from service.peer_transfer_service import peerTransfer

BOOK_EXTS = ('.epub', '.pdf', '.txt', '.mobi', '.azw', '.azw3')


def _fmt_size(n):
    try:
        n = int(n)
    except Exception:
        return ''
    if n < 1024:
        return '%d B' % n
    if n < 1024 * 1024:
        return '%.1f KB' % (n / 1024)
    if n < 1024 * 1024 * 1024:
        return '%.1f MB' % (n / 1024 / 1024)
    return '%.2f GB' % (n / 1024 / 1024 / 1024)


def _default_receive_dir():
    return os.path.join(cfg.get(cfg.downloadFolder), 'transfer')


class PeerTransferInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('PeerTransferInterface')

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self._picked_files = []        # 已选待发文件路径
        self._peers = []               # 当前在线对端（与 ComboBox 顺序对齐）
        self._receiving = False
        self._sendTooltip = None

        self.sendCard = _SendCard(self)
        self.recvCard = _ReceiveCard(self)

        self.__initWidget()
        self.__connectSignals()

    def __initWidget(self):
        self.view.setObjectName('view')
        StyleSheet.COMIC_INTERFACE.apply(self)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.vBoxLayout.setContentsMargins(36, 30, 36, 30)
        self.vBoxLayout.setSpacing(20)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self.vBoxLayout.addWidget(self.sendCard)
        self.vBoxLayout.addWidget(self.recvCard)

    def __connectSignals(self):
        peerTransfer.peersChanged.connect(self._refreshPeers)
        peerTransfer.sendProgress.connect(self._onSendProgress)
        peerTransfer.sendFinished.connect(self._onSendFinished)
        peerTransfer.incomingOffer.connect(self._onIncomingOffer)
        peerTransfer.receiveAutoStopped.connect(self._onReceiveAutoStopped)

    # ===================== 发送 =====================

    def pickFiles(self):
        folder = cfg.get(cfg.downloadFolder)
        paths, _ = QFileDialog.getOpenFileNames(
            self, '选择要传书的文件', folder,
            '书籍 (*.epub *.pdf *.txt *.mobi *.azw *.azw3);;所有文件 (*)')
        if not paths:
            return
        # 追加去重，支持多次“选择文件”累加
        existing = set(self._picked_files)
        for p in paths:
            if p not in existing:
                self._picked_files.append(p)
                existing.add(p)
        self.sendCard.setFiles(self._picked_files)
        # 选完文件即开始发现手机
        peerTransfer.enter_send_mode()
        self._refreshPeers()
        if not self._peers:
            self.sendCard.setPeerHint('正在搜索手机…请确认手机已开启「传书到电脑」')
        else:
            self.sendCard.setPeerHint('已发现手机，选择目标后点发送')

    def removeFile(self, path):
        if path in self._picked_files:
            self._picked_files.remove(path)
        self.sendCard.setFiles(self._picked_files)

    def clearFiles(self):
        self._picked_files = []
        self.sendCard.setFiles([])

    def _refreshPeers(self):
        self._peers = peerTransfer.online_peers()
        self.sendCard.setPeers([p.name for p in self._peers])
        if self._picked_files:
            if not self._peers:
                self.sendCard.setPeerHint('未发现手机，请确认手机已开启「传书到电脑」')
            else:
                self.sendCard.setPeerHint('已发现 %d 台设备，选择目标后点发送'
                                          % len(self._peers))

    def doSend(self):
        if not self._picked_files:
            InfoBar.warning('提示', '请先选择文件', parent=self, duration=1500)
            return
        idx = self.sendCard.peerIndex()
        if idx < 0 or idx >= len(self._peers):
            InfoBar.warning('提示', '请选择目标手机', parent=self, duration=1500)
            return
        peer = self._peers[idx]
        self._startSendTooltip()
        peerTransfer.send_book(peer.id, self._picked_files)

    def _startSendTooltip(self):
        self._sendTooltip = StateToolTip('正在传书', '请耐心等待~~', self)
        x = (self.width() - self._sendTooltip.width()) // 2
        y = (self.height() - self._sendTooltip.height()) // 2
        self._sendTooltip.move(x, y)
        self._sendTooltip.show()

    def _onSendProgress(self, offerId, sent, total, idx, count):
        if not self._sendTooltip:
            return
        if total > 0:
            pct = int(sent * 100 / total)
            if count > 1:
                txt = '正在传书 %d/%d · %d%%' % (idx + 1, count, pct)
            else:
                txt = '正在传书 · %d%%' % pct
            self._sendTooltip.setContent(txt + '，请耐心等待~~')

    def _onSendFinished(self, offerId, ok):
        if self._sendTooltip:
            self._sendTooltip.hide()
            self._sendTooltip = None
        if ok:
            InfoBar.success('传书完成', '文件已发送到手机', parent=self, duration=2000)
        else:
            InfoBar.error('传书失败', '请确认手机已开启接收后重试',
                          parent=self, duration=3000)

    # ===================== 接收 =====================

    def toggleReceive(self):
        if self._receiving:
            peerTransfer.exit_receive_mode()
            self._receiving = False
            self.recvCard.setReceiving(False)
        else:
            ok = peerTransfer.enter_receive_mode()
            if not ok:
                InfoBar.error('启动失败', '无法启动接收服务，请重试',
                              parent=self, duration=3000)
                return
            self._receiving = True
            self.recvCard.setReceiving(True)

    def _onReceiveAutoStopped(self):
        """接收模式因长时间无连接被服务自动停止。"""
        self._receiving = False
        self.recvCard.setReceiving(False)
        InfoBar.info('已自动停止接收', '长时间无连接，已自动停止接收',
                     parent=self, duration=3000)

    def _onIncomingOffer(self, offer):
        # offer 是 service 的 to_offer() 字典
        files = offer.get('files', []) or []
        count = len(files)
        total = sum(int(f.get('size', 0)) for f in files)
        dlg = ReceiveAcceptDialog(
            peer_name=offer.get('peerName', '对端'),
            file_count=count, total_size=total,
            kind=offer.get('kind', 'file'),
            default_dir=_default_receive_dir(), parent=self)
        if dlg.exec():
            peerTransfer.respond_to_offer(
                offer.get('id'), True, dlg.chosen_dir)
            InfoBar.success('已接受', '文件将保存到 %s' % dlg.chosen_dir,
                            parent=self, duration=2500)
        else:
            peerTransfer.respond_to_offer(offer.get('id'), False)
            InfoBar.warning('已拒绝', '已拒绝该次传书',
                            parent=self, duration=1500)


class _SendCard(ElevatedCardWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host

        self.titleLabel = SubtitleLabel('传书到手机（请确保在同一局域网）', self)
        self.descLabel = CaptionLabel('从本机选择书籍文件，发送到手机', self)
        self.pickBtn = PushButton('选择文件', self)
        self.pickBtn.clicked.connect(host.pickFiles)
        self.fileCountLabel = CaptionLabel('未选择文件', self)

        # 已选文件清单（每行文件名 + 删除按钮）
        self.filesContainer = QWidget(self)
        self.filesLayout = QVBoxLayout(self.filesContainer)
        self.filesLayout.setContentsMargins(0, 0, 0, 0)
        self.filesLayout.setSpacing(4)

        self.peerBox = ComboBox(self)
        self.peerBox.setPlaceholderText('目标手机')
        self.peerHint = CaptionLabel('请先选择文件', self)

        self.sendBtn = PrimaryPushButton('发送', self)
        self.sendBtn.clicked.connect(host.doSend)
        self.sendBtn.setEnabled(False)

        self.clearBtn = PushButton('清除全部', self)
        self.clearBtn.clicked.connect(host.clearFiles)
        self.clearBtn.setEnabled(False)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        v.addWidget(self.titleLabel)
        v.addWidget(self.descLabel)
        row1 = QHBoxLayout()
        row1.addWidget(self.pickBtn)
        row1.addWidget(self.fileCountLabel, 1)
        v.addLayout(row1)
        v.addWidget(self.filesContainer)
        row2 = QHBoxLayout()
        row2.addWidget(self.peerBox, 1)
        row2.addWidget(self.clearBtn)
        row2.addWidget(self.sendBtn)
        v.addLayout(row2)
        v.addWidget(self.peerHint)

    def setFiles(self, paths):
        """刷新已选文件清单：每行文件名 + 删除按钮。"""
        while self.filesLayout.count():
            item = self.filesLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for p in paths:
            self.filesLayout.addWidget(self._makeFileRow(p))
        self.filesLayout.addStretch()
        if paths:
            self.fileCountLabel.setText('已选 %d 个文件' % len(paths))
        else:
            self.fileCountLabel.setText('未选择文件')
        self.sendBtn.setEnabled(bool(paths))
        self.clearBtn.setEnabled(bool(paths))

    def _makeFileRow(self, path):
        w = QWidget(self)
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        name = BodyLabel(os.path.basename(path), self)
        name.setToolTip(path)
        delBtn = TransparentToolButton(FluentIcon.DELETE, self)
        delBtn.setFixedSize(28, 28)
        delBtn.clicked.connect(lambda: self.host.removeFile(path))
        row.addWidget(name, 1)
        row.addWidget(delBtn)
        return w

    def setPeers(self, names):
        cur = self.peerBox.currentText()
        self.peerBox.clear()
        for n in names:
            self.peerBox.addItem(n)
        if cur and cur in names:
            self.peerBox.setCurrentIndex(names.index(cur))

    def setPeerHint(self, text):
        self.peerHint.setText(text)

    def peerIndex(self):
        return self.peerBox.currentIndex()


class _ReceiveCard(ElevatedCardWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setFixedHeight(150)

        self.titleLabel = SubtitleLabel('从手机接收（请确保在同一局域网）', self)
        self.descLabel = CaptionLabel('开启后可接收手机发来的书，保存到下载目录下的 transfer', self)
        self.toggleBtn = PrimaryPushButton('开启接收', self)
        self.toggleBtn.clicked.connect(host.toggleReceive)
        self.statusLabel = CaptionLabel('未开启', self)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        v.addWidget(self.titleLabel)
        v.addWidget(self.descLabel)
        row = QHBoxLayout()
        row.addWidget(self.toggleBtn)
        row.addWidget(self.statusLabel, 1)
        v.addLayout(row)

    def setReceiving(self, on):
        self.toggleBtn.setText('停止接收' if on else '开启接收')
        self.statusLabel.setText('等待手机传书…' if on else '未开启')


class ReceiveAcceptDialog(MessageBoxBase):
    """接收确认弹窗：显示对端/文件信息，可选接收目录。yes=接收，cancel=拒绝。"""

    def __init__(self, peer_name, file_count, total_size, kind,
                 default_dir, parent=None):
        super().__init__(parent)
        self.chosen_dir = default_dir

        self.titleLabel = SubtitleLabel('%s 正在传书给你' % peer_name, self)
        self.infoLabel = BodyLabel(
            '%d 个文件 · %s' % (file_count, _fmt_size(total_size)), self)
        self.dirLabel = CaptionLabel('接收目录', self)
        self.dirEdit = LineEdit(self)
        self.dirEdit.setText(default_dir)
        self.dirEdit.setReadOnly(True)
        self.browseBtn = PushButton('浏览', self)
        self.browseBtn.clicked.connect(self._browse)

        tip = CaptionLabel(
            '书类文件保存到所选目录（电脑端不入库）', self)
        if kind == 'book':
            tip.setText('提示：电脑端不自动入库，文件存到所选目录')

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.infoLabel)
        self.viewLayout.addWidget(self.dirLabel)
        row = QHBoxLayout()
        row.addWidget(self.dirEdit, 1)
        row.addWidget(self.browseBtn)
        self.viewLayout.addLayout(row)
        self.viewLayout.addWidget(tip)

        self.yesButton.setText('接收')
        self.cancelButton.setText('拒绝')
        self.widget.setMinimumWidth(420)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(
            self, '选择接收目录', self.chosen_dir)
        if d:
            self.chosen_dir = d
            self.dirEdit.setText(d)
