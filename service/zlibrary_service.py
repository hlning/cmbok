# coding:utf-8
"""z-library 登录/注册线程，遵循项目 QThread + pyqtSignal 模式"""
import logging
import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from common.config import cfg
from common.signal_bus import signalBus
from service.zlibrary_client import Zlibrary


class ZlibraryLogin(QThread):
    """z-library 邮箱密码登录，成功后保存 token 到配置"""
    success = pyqtSignal(object, object)  # status, email

    def __init__(self, email, password):
        super(ZlibraryLogin, self).__init__()
        self.email = email
        self.password = password

    def run(self):
        try:
            Z = Zlibrary(email=self.email, password=self.password)
            # 地址不可用（404）：提示图书功能暂不可用，区别于密码错误的「登录失败」
            if Z.isUnavailable():
                self.success.emit('unavailable', None)
                return
            if Z.isLoggedIn():
                remix_userid, remix_userkey = Z.getRemixToken()
                cfg.set(cfg.zlibrary_email, self.email)
                cfg.set(cfg.zlibrary_username, Z.getName() or '')
                cfg.set(cfg.zlibrary_remix_userid, remix_userid if remix_userid else '')
                cfg.set(cfg.zlibrary_remix_userkey, remix_userkey if remix_userkey else '')
                # 缓存 profile 最新下载量，登录后头像立即显示实际值（自登账号改进）
                from service.cmbok_service import _update_profile_downloads
                _update_profile_downloads(remix_userid, Z.getDownloadsToday(), Z.getDownloadsLimit())
                signalBus.zlibraryLoginChanged.emit(self.email)
                self.success.emit('success', self.email)
            else:
                self.success.emit('fail', None)
        except Exception:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('登录失败')


class ZlibrarySendCode(QThread):
    """z-library 注册：发送邮箱验证码"""
    success = pyqtSignal(object)  # status

    def __init__(self, email, password, name):
        super(ZlibrarySendCode, self).__init__()
        self.email = email
        self.password = password
        self.name = name

    def run(self):
        try:
            Z = Zlibrary()
            response = Z.sendCode(self.email, self.password, self.name)
            if response and response.get('success'):
                self.success.emit('success')
            else:
                self.success.emit('fail')
        except Exception:
            self.success.emit('error')
            logging.info(traceback.format_exc())
            logging.info('发送验证码失败')


class ZlibraryRegister(QThread):
    """z-library 注册：验证码校验完成注册"""
    success = pyqtSignal(object)  # status

    def __init__(self, email, password, name, code):
        super(ZlibraryRegister, self).__init__()
        self.email = email
        self.password = password
        self.name = name
        self.code = code

    def run(self):
        try:
            Z = Zlibrary()
            # 提交验证码完成注册（rpc.php 返回值不可靠，不据此判断成败）
            Z.verifyCode(self.email, self.password, self.name, self.code)
            # 用账号登录验证注册是否成功
            loginZ = Zlibrary(email=self.email, password=self.password)
            if loginZ.isLoggedIn():
                self.success.emit('success')
            else:
                self.success.emit('fail')
        except Exception:
            self.success.emit('error')
            logging.info(traceback.format_exc())
            logging.info('注册失败')
