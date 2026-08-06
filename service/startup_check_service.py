# coding:utf-8
"""启动检测线程：版本/公告/地址配置检测全部后台异步执行，不阻塞主线程。

主线程在 Window.__init__ 末尾 start() 本线程后立即返回进入事件循环，
软件可快速打开；检测结果通过 pyqtSignal 回传主线程，由槽函数提示或更新配置。
"""
import logging
import traceback
from urllib.parse import urlparse

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from common.config import cfg, GITHUBURL, GITHUB_RELEASE_API, NOTIFICATION_URL, URL_CONFIG_URL


class StartupCheckThread(QThread):
    """启动检测线程。

    信号：
    - versionFound(tag, body, html_url)：发现新版本时发，主线程弹更新框
    - notificationReady(text)：拿到公告文本时发，主线程顶部 InfoBar 提示
    - urlConfigUpdated(updates)：地址配置需更新时发 dict，主线程执行 cfg.set
    - zlibraryUnavailable()：zlibrary_url 本地与云端候选全部不可用时发，主线程提示图书功能受限
    """
    versionFound = pyqtSignal(str, str, str)
    notificationReady = pyqtSignal(str)
    urlConfigUpdated = pyqtSignal(dict)
    zlibraryUnavailable = pyqtSignal()

    def run(self):
        # 版本检测 -> 有新版本则提示并结束（保持"有新版不弹公告"的互斥逻辑）
        if not self._check_version():
            # 无新版本/未开启检测/请求失败：查公告
            self._check_notification()
        # 地址配置检测（与版本/公告逻辑独立，顺带在后台一起做完）
        self._check_url_config()

    def _check_version(self):
        """查 GitHub Releases 是否有新版本。有新版本发信号并返回 True。"""
        try:
            if cfg.get(cfg.checkUpdateAtStartUp):
                response = requests.get(GITHUB_RELEASE_API, timeout=5)
                if response.status_code == 200:
                    release = response.json()
                    tag = release.get('tag_name', '')
                    if tag and tag != cfg.get(cfg.version):
                        body = release.get('body') or '发现新版本，是否前往下载？'
                        html_url = release.get('html_url') or GITHUBURL
                        self.versionFound.emit(tag, body, html_url)
                        return True
        except Exception:
            logging.info(traceback.format_exc())
        return False

    def _check_notification(self):
        """查 jsDelivr 公告。有公告发信号。"""
        try:
            response = requests.get(NOTIFICATION_URL, timeout=5)
            if response.status_code == 200:
                notification = response.json().get('notification', '')
                if notification:
                    self.notificationReady.emit(notification)
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('服务器已关闭')

    def _check_url_config(self):
        """查 jsDelivr url_config.json：
        - copy_url：与本地不同则发信号更新；
        - zlibrary_url：只探测云端值（不检测本地配置），可用则写回，不可用则提示图书功能受限。
        """
        cloud = self._fetch_url_config()
        if not cloud:
            # 云端拉取失败：无云端地址可探测，沿用本地配置（运行时由 404/重定向兜底），copy_url 不动
            return
        # copy_url：与本地不同则更新
        copy_url = cloud.get('copy_url')
        if copy_url and copy_url != cfg.get(cfg.copy_url):
            self.urlConfigUpdated.emit({'copy_url': copy_url})
        # zlibrary_url：只探测云端地址
        self._check_zlibrary_url(cloud.get('zlibrary_url'))

    @staticmethod
    def _fetch_url_config():
        """拉云端 url_config.json，返回 dict 或 None。"""
        try:
            response = requests.get(URL_CONFIG_URL, timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception:
            logging.info('检查地址配置异常: ' + traceback.format_exc())
        return None

    def _check_zlibrary_url(self, cloud_zlibrary_url):
        """启动后台探测 zlibrary_url：只检测云端地址，不检测本地配置。
        - 云端地址可用（含重定向后的新域名）则写回配置；
        - 云端地址不可用则发 zlibraryUnavailable 信号，主线程提示图书功能受限；
        - 无云端地址（url_config.json 无此字段）则不探测，沿用本地配置。
        """
        if not cloud_zlibrary_url:
            # 云端无 zlibrary_url 字段，沿用本地配置
            return
        final = self._probe_zlibrary_url(cloud_zlibrary_url)
        if final:
            # 探测可用：最终域名与本地不同才写回（避免无意义写配置）
            local = cfg.get(cfg.zlibrary_url)
            if final != local:
                self.urlConfigUpdated.emit({'zlibrary_url': final})
            return
        # 云端地址不可用
        self.zlibraryUnavailable.emit()

    @staticmethod
    def _probe_zlibrary_url(url):
        """探测单个 zlibrary_url 可用性，跟随 HTTP 重定向，返回最终可用域名（无 scheme）；不可用返回 None。
        能拿到 HTTP 响应即视为可用（zlibrary 根路径常返回 503 但站点实际可用）；
        仅连接超时/重置/DNS 失败等异常才判不可用。重定向目标连不上会抛异常 -> 该候选不可用。"""
        if not url:
            return None
        try:
            # zlibrary_url 存的是不带 scheme 的域名（与 zlibrary_client 拼接 https:// 一致）
            target = url if url.startswith(('http://', 'https://')) else 'https://' + url
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                          "image/webp,*/*;q=0.8",
            }
            # allow_redirects=True：跟随 301/302 到新域名，resp.url 为最终落地地址
            resp = requests.get(target, timeout=6, headers=headers, allow_redirects=True)
            # 取最终落地域名（无 scheme），与配置存储格式一致；
            # netloc 异常为空时回退到候选地址的域名（target 已补 scheme，netloc 必为纯域名）
            final = urlparse(resp.url).netloc or urlparse(target).netloc
            return final or url
        except Exception:
            logging.info('zlibrary_url 探测异常: ' + traceback.format_exc())
            return None
