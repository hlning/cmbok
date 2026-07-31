# coding: utf-8
from PyQt5.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    """ Signal bus """

    switchToSampleCard = pyqtSignal(str, int)
    micaEnableChanged = pyqtSignal(bool)
    supportSignal = pyqtSignal()
    zlibraryLoginChanged = pyqtSignal(str)  # z-library 登录态变化（email，空=登出）
    collectChanged = pyqtSignal()  # 收藏/取消收藏后通知收藏页刷新


signalBus = SignalBus()
