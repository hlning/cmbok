# coding:utf-8
"""z-library 登录对话框"""
import json

from PyQt5.QtCore import pyqtSignal, QStringListModel, Qt
from PyQt5.QtWidgets import QCompleter

from qfluentwidgets import (MessageBoxBase, LineEdit, PasswordLineEdit, PrimaryPushButton,
                            BodyLabel, InfoBarPosition, InfoBarIcon, isDarkTheme, qconfig)

from common.config import cfg
from service.zlibrary_service import ZlibraryLogin
from view.components.info_bar_tip import show_tip


class EmailLineEdit(LineEdit):
    """邮箱输入框：聚焦时弹出历史邮箱下拉选择"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._emailCompleter = QCompleter(self)
        self._emailCompleter.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._emailCompleter.setCaseSensitivity(Qt.CaseInsensitive)
        # 调 QLineEdit.setCompleter 绑定 widget（qfluentwidgets 的 setCompleter 不绑定，会导致 complete() 崩溃）
        super(LineEdit, self).setCompleter(self._emailCompleter)
        self._stylePopup()
        qconfig.themeChanged.connect(self._stylePopup)

    def setHistory(self, emails):
        self._emailCompleter.setModel(QStringListModel(emails, self._emailCompleter))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        m = self._emailCompleter.model()
        if m and m.rowCount() > 0:
            self._emailCompleter.complete()

    def _stylePopup(self):
        dark = isDarkTheme()
        bg = '#2b2b2b' if dark else '#ffffff'
        fg = '#eaeaea' if dark else '#1f1f1f'
        hover = 'rgba(255,255,255,26)' if dark else 'rgba(0,0,0,26)'
        border = 'rgba(255,255,255,0.1)' if dark else 'rgba(0,0,0,0.1)'
        self._emailCompleter.popup().setStyleSheet(f"""
            QListView {{
                background: {bg}; border: 1px solid {border};
                border-radius: 6px; padding: 4px; outline: none;
            }}
            QListView::item {{ padding: 6px 12px; border-radius: 4px; color: {fg}; }}
            QListView::item:hover, QListView::item:selected {{ background: {hover}; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: rgba(128,128,128,150); border-radius: 3px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)


class ZlibraryLoginDialog(MessageBoxBase):
    """z-library 账号登录对话框"""
    loginSuccess = pyqtSignal(str)       # 登录成功，回传邮箱
    registerRequested = pyqtSignal()     # 请求打开注册对话框

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel('账号登录', self)
        self.emailEdit = EmailLineEdit(self)
        self.emailEdit.setPlaceholderText('请输入邮箱')
        self.emailEdit.setHistory(self._loadEmailHistory())
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
            self._saveEmailHistory(email)
            self.loginSuccess.emit(email)
            self.accept()
        elif status == 'fail':
            show_tip(InfoBarIcon.ERROR, '温馨提示', '登录失败，请检查邮箱与密码', self, InfoBarPosition.TOP)
        else:
            show_tip(InfoBarIcon.ERROR, '温馨提示', '网络异常，登录失败', self, InfoBarPosition.TOP)

    def _loadEmailHistory(self):
        try:
            return json.loads(cfg.get(cfg.zlibrary_email_history) or '[]')
        except Exception:
            return []

    def _saveEmailHistory(self, email):
        emails = self._loadEmailHistory()
        if email in emails:
            emails.remove(email)
        emails.insert(0, email)
        emails = emails[:10]
        cfg.set(cfg.zlibrary_email_history, json.dumps(emails, ensure_ascii=False))
        self.emailEdit.setHistory(emails)

    def _onRegister(self):
        self.registerRequested.emit()
        self.reject()
