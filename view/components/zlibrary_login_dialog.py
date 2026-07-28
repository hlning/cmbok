# coding:utf-8
"""z-library 登录对话框"""
from PyQt5.QtCore import pyqtSignal

from qfluentwidgets import (MessageBoxBase, LineEdit, PasswordLineEdit, PrimaryPushButton,
                            BodyLabel, InfoBarPosition, InfoBarIcon)

from service.zlibrary_service import ZlibraryLogin
from view.components.info_bar_tip import show_tip


class ZlibraryLoginDialog(MessageBoxBase):
    """z-library 账号登录对话框"""
    loginSuccess = pyqtSignal(str)       # 登录成功，回传邮箱
    registerRequested = pyqtSignal()     # 请求打开注册对话框

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel('账号登录', self)
        self.emailEdit = LineEdit(self)
        self.emailEdit.setPlaceholderText('请输入邮箱')
        self.passwordEdit = PasswordLineEdit(self)
        self.passwordEdit.setPlaceholderText('请输入密码')

        self.loginBtn = PrimaryPushButton(text='登录', parent=self)
        self.registerBtn = PrimaryPushButton(text='去注册', parent=self)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.emailEdit)
        self.viewLayout.addWidget(self.passwordEdit)
        self.viewLayout.addWidget(self.loginBtn)
        self.viewLayout.addWidget(self.registerBtn)

        # 隐藏内置确定按钮，使用自定义登录按钮
        self.yesButton.hide()
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(360)

        self.loginBtn.clicked.connect(self._onLogin)
        self.registerBtn.clicked.connect(self._onRegister)
        self._loginThread = None

    def _onLogin(self):
        email = self.emailEdit.text().strip()
        password = self.passwordEdit.text()
        if not email or not password:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请输入邮箱和密码', self, InfoBarPosition.TOP)
            return
        self.loginBtn.setEnabled(False)
        self.loginBtn.setText('登录中...')
        self._loginThread = ZlibraryLogin(email, password)
        self._loginThread.success.connect(self._onLoginResult)
        self._loginThread.start()

    def _onLoginResult(self, status, email):
        self.loginBtn.setEnabled(True)
        self.loginBtn.setText('登录')
        if status == 'success':
            self.loginSuccess.emit(email)
            self.accept()
        elif status == 'fail':
            show_tip(InfoBarIcon.ERROR, '温馨提示', '登录失败，请检查邮箱与密码', self, InfoBarPosition.TOP)
        else:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '网络异常，登录失败', self, InfoBarPosition.TOP)

    def _onRegister(self):
        self.registerRequested.emit()
        self.reject()
