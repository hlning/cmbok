# coding: utf-8
from PyQt5.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    """ Signal bus """

    switchToSampleCard = pyqtSignal(str, int)
    micaEnableChanged = pyqtSignal(bool)
    supportSignal = pyqtSignal()
    zlibraryLoginChanged = pyqtSignal(str)  # z-library 登录态变化（email，空=登出）


signalBus = SignalBus()
