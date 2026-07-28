# coding:utf-8
"""z-library 注册对话框"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QWidget

from qfluentwidgets import (MessageBoxBase, LineEdit, PasswordLineEdit, PrimaryPushButton,
                            BodyLabel, InfoBarPosition, InfoBarIcon)

from service.zlibrary_service import ZlibrarySendCode, ZlibraryRegister
from view.components.info_bar_tip import show_tip


class ZlibraryRegisterDialog(MessageBoxBase):
    """z-library 账号注册对话框"""
    registerSuccess = pyqtSignal(str)  # 注册成功，回传邮箱

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel('账号注册', self)
        self.emailEdit = LineEdit(self)
        self.emailEdit.setPlaceholderText('请输入邮箱')
        self.passwordEdit = PasswordLineEdit(self)
        self.passwordEdit.setPlaceholderText('请输入密码')
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText('请输入昵称')

        # 验证码 + 发送按钮一行
        self.codeEdit = LineEdit(self)
        self.codeEdit.setPlaceholderText('请输入验证码')
        self.sendCodeBtn = PrimaryPushButton(text='发送验证码', parent=self)
        codeLayout = QHBoxLayout()
        codeLayout.setContentsMargins(0, 0, 0, 0)
        codeLayout.addWidget(self.codeEdit)
        codeLayout.addWidget(self.sendCodeBtn)
        codeWidget = QWidget(self)
        codeWidget.setLayout(codeLayout)

        self.registerBtn = PrimaryPushButton(text='完成注册', parent=self)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.emailEdit)
        self.viewLayout.addWidget(self.passwordEdit)
        self.viewLayout.addWidget(self.nameEdit)
        self.viewLayout.addWidget(codeWidget)
        self.viewLayout.addWidget(self.registerBtn)

        self.yesButton.hide()
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(360)

        self.sendCodeBtn.clicked.connect(self._onSendCode)
        self.registerBtn.clicked.connect(self._onRegister)
        self._sendThread = None
        self._registerThread = None

    def _onSendCode(self):
        email = self.emailEdit.text().strip()
        password = self.passwordEdit.text()
        name = self.nameEdit.text().strip()
        if not email or not password or not name:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请填写邮箱、密码和昵称', self, InfoBarPosition.TOP)
            return
        self.sendCodeBtn.setEnabled(False)
        self.sendCodeBtn.setText('发送中...')
        self._sendThread = ZlibrarySendCode(email, password, name)
        self._sendThread.success.connect(self._onSendCodeResult)
        self._sendThread.start()

    def _onSendCodeResult(self, status):
        self.sendCodeBtn.setText('发送验证码')
        if status == 'success':
            self.sendCodeBtn.setText('已发送')
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '验证码已发送到邮箱，请查收', self, InfoBarPosition.TOP)
        else:
            self.sendCodeBtn.setEnabled(True)
            show_tip(InfoBarIcon.ERROR, '温馨提示', '验证码发送失败', self, InfoBarPosition.TOP)

    def _onRegister(self):
        email = self.emailEdit.text().strip()
        password = self.passwordEdit.text()
        name = self.nameEdit.text().strip()
        code = self.codeEdit.text().strip()
        if not email or not password or not name:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请填写邮箱、密码和昵称', self, InfoBarPosition.TOP)
            return
        if not code:
            show_tip(InfoBarIcon.WARNING, '温馨提示', '请输入验证码', self, InfoBarPosition.TOP)
            return
        self.registerBtn.setEnabled(False)
        self.registerBtn.setText('注册中...')
        self._registerThread = ZlibraryRegister(email, password, name, code)
        self._registerThread.success.connect(self._onRegisterResult)
        self._registerThread.start()

    def _onRegisterResult(self, status):
        self.registerBtn.setEnabled(True)
        self.registerBtn.setText('完成注册')
        if status == 'success':
            # 提示挂在父窗口（主窗口），避免对话框关闭后 InfoBar 被销毁；延长显示时长
            show_tip(InfoBarIcon.SUCCESS, '温馨提示', '注册成功，请登录', self.parent(), InfoBarPosition.TOP,
                     duration=5000)
            self.registerSuccess.emit(self.emailEdit.text().strip())
            self.accept()
        else:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '注册失败，请检查验证码或稍后重试', self, InfoBarPosition.TOP)
