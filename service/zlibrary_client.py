# coding:utf-8
"""
Zlibrary 客户端 - 迁移自后台 pear-admin-flask 的 applications/service/Zlibrary.py
原项目: https://github.com/bipinkrish/Zlibrary-API (Bipinkrish)
域名改为国内可访问的 zh.kid1412.by，并新增 getDownloadLink 供流式下载使用。
"""
import time

import requests
from urllib.parse import urlparse

from common.config import cfg


class Zlibrary:
    def __init__(self, email: str = None, password: str = None,
                 remix_userid=None, remix_userkey: str = None):
        self.__email = None
        self.__name = None
        self.__kindle_email = None
        self.__remix_userid = None
        self.__remix_userkey = None
        self.__domain = cfg.get(cfg.zlibrary_url)
        self.__timeout = 30
        self.__loggedin = False
        # 地址不可用（API 路径 404，说明当前域名非 z-library 主机）；登录/搜索据此提示功能暂不可用
        self.__unavailable = False
        self.__headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        }
        self.__cookies = {
            "siteLanguageV2": "en",
        }

        if email is not None and password is not None:
            self.login(email, password)
        elif remix_userid is not None and remix_userkey is not None:
            self.loginWithToken(remix_userid, remix_userkey)

    def __setValues(self, response):
        if not response or not response.get("success"):
            return response
        self.__email = response["user"]["email"]
        self.__name = response["user"]["name"]
        self.__kindle_email = response["user"]["kindle_email"]
        self.__remix_userid = str(response["user"]["id"])
        self.__remix_userkey = response["user"]["remix_userkey"]
        self.__cookies["remix_userid"] = self.__remix_userid
        self.__cookies["remix_userkey"] = self.__remix_userkey
        self.__loggedin = True
        return response

    def __login(self, email, password):
        return self.__setValues(
            self.__makePostRequest("/eapi/user/login",
                                   data={"email": email, "password": password}, override=True)
        )

    def __checkIDandKey(self, remix_userid, remix_userkey):
        return self.__setValues(
            self.__makeGetRequest("/eapi/user/profile", cookies={
                "siteLanguageV2": "en",
                "remix_userid": str(remix_userid),
                "remix_userkey": remix_userkey,
            })
        )

    def login(self, email: str, password: str):
        return self.__login(email, password)

    def loginWithToken(self, remix_userid, remix_userkey: str):
        return self.__checkIDandKey(remix_userid, remix_userkey)

    # 限流/服务器错误退避重试（z-library 走 Cloudflare，429/5xx 常见）
    _RETRY_STATUS = {429, 503, 520, 522}
    _MAX_RETRIES = 3
    _MAX_RETRY_WAIT = 30  # 单次退避上限（秒），避免 Retry-After 过大卡死线程

    def __retry_wait(self, resp, attempt):
        """退避时长：优先 Retry-After，否则指数退避 2/4/8s"""
        ra = resp.headers.get('Retry-After')
        if ra:
            try:
                return min(float(ra), self._MAX_RETRY_WAIT)
            except ValueError:
                pass
        return min(2 ** (attempt + 1), self._MAX_RETRY_WAIT)

    def __request_with_retry(self, method, url, **kwargs):
        """发请求并对 429/5xx 退避重试。返回 (resp, rate_limited)。
        rate_limited=True 表示重试耗尽仍被限流。调用方均在 QThread 内，sleep 不阻塞主线程。"""
        resp = None
        rate_limited = False
        for attempt in range(self._MAX_RETRIES + 1):
            resp = requests.request(method, "https://" + self.__domain + url,
                                    timeout=self.__timeout, allow_redirects=False, **kwargs)
            if resp.status_code not in self._RETRY_STATUS:
                return resp, False
            if attempt >= self._MAX_RETRIES:
                rate_limited = True
                break
            time.sleep(self.__retry_wait(resp, attempt))
        return resp, rate_limited

    def __makePostRequest(self, url: str, data: dict = None, override=False, _followed=False):
        if not self.isLoggedIn() and override is False:
            return {"success": False, "error": "Not logged in"}
        try:
            resp, rate_limited = self.__request_with_retry(
                "POST", url, data=data or {}, cookies=self.__cookies, headers=self.__headers)
            # 重定向到新域名：更新域名并持久化，用新域名重试原请求（仅重试一次防循环）
            if resp.status_code in (301, 302, 303, 307, 308) and not _followed:
                new_domain = self.__extractDomain(resp.headers.get('Location'))
                if new_domain and new_domain != self.__domain:
                    self.__domain = new_domain
                    cfg.set(cfg.zlibrary_url, new_domain)
                    return self.__makePostRequest(url, data, override, _followed=True)
            # 404：API 路径不存在，说明当前域名非 z-library 主机（如配错指向其他站点），标记功能不可用
            if resp.status_code == 404:
                self.__unavailable = True
                return {"success": False, "unavailable": True, "error": "服务地址不可用（404）"}
            if rate_limited:
                return {"success": False, "rate_limited": True, "error": "请求过于频繁，请稍后再试"}
            return resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __extractDomain(self, location):
        """从重定向 Location 提取域名；相对路径或空则返回 None"""
        if not location:
            return None
        netloc = urlparse(location).netloc
        return netloc or None

    def __makeGetRequest(self, url: str, params: dict = None, cookies=None, _followed=False):
        if not self.isLoggedIn() and cookies is None:
            return {"success": False, "error": "Not logged in"}
        try:
            resp, rate_limited = self.__request_with_retry(
                "GET", url, params=params or {},
                cookies=self.__cookies if cookies is None else cookies, headers=self.__headers)
            # 重定向到新域名：更新域名并持久化，用新域名重试原请求（仅重试一次防循环）
            if resp.status_code in (301, 302, 303, 307, 308) and not _followed:
                new_domain = self.__extractDomain(resp.headers.get('Location'))
                if new_domain and new_domain != self.__domain:
                    self.__domain = new_domain
                    cfg.set(cfg.zlibrary_url, new_domain)
                    return self.__makeGetRequest(url, params, cookies, _followed=True)
            # 404：API 路径不存在，说明当前域名非 z-library 主机，标记功能不可用
            if resp.status_code == 404:
                self.__unavailable = True
                return {"success": False, "unavailable": True, "error": "服务地址不可用（404）"}
            if rate_limited:
                return {"success": False, "rate_limited": True, "error": "请求过于频繁，请稍后再试"}
            return resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def getProfile(self):
        return self.__makeGetRequest("/eapi/user/profile")

    def search(self, message: str = None, yearFrom=None, yearTo=None, languages: str = None,
               extensions=None, order: str = None, page: int = None, limit: int = None):
        return self.__makePostRequest("/eapi/book/search", {
            k: v for k, v in {
                "message": message, "yearFrom": yearFrom, "yearTo": yearTo,
                "languages": languages, "extensions[]": extensions, "order": order,
                "page": page, "limit": limit,
            }.items() if v is not None
        })

    def getDownloadLink(self, book_id, book_hash):
        """
        获取图书下载链接（不下载内容），供流式下载使用。
        返回 (allowDownload, filename, downloadLink, headers)
        """
        response = self.__makeGetRequest(f"/eapi/book/{book_id}/{book_hash}/file")
        if not response or not response.get("success"):
            return False, None, None, None
        file_info = response.get("file", {})
        allow_download = file_info.get("allowDownload", False)
        if not allow_download:
            return False, None, None, None
        filename = file_info.get("description", "")
        try:
            filename += " (" + file_info["author"] + ")"
        except Exception:
            pass
        filename += "." + file_info.get("extension", "")
        ddl = file_info.get("downloadLink")
        headers = self.__headers.copy()
        if ddl:
            try:
                headers["authority"] = ddl.split("/")[2]
            except Exception:
                pass
        return True, filename, ddl, headers

    def downloadBook(self, book_id, book_hash):
        """整文件下载（备用），返回 (allowDownload, filename, content)"""
        allow_download, filename, ddl, headers = self.getDownloadLink(book_id, book_hash)
        if not allow_download or not ddl:
            return False, None, None
        try:
            res = requests.get(ddl, headers=headers, timeout=self.__timeout)
            if res.status_code == 200:
                return True, filename, res.content
        except Exception:
            pass
        return False, None, None

    def isLoggedIn(self) -> bool:
        return self.__loggedin

    def isUnavailable(self) -> bool:
        """地址是否不可用：API 路径返回 404，说明当前域名非 z-library 主机。
        登录/搜索据此提示「图书功能暂不可用」。"""
        return self.__unavailable

    def getRemixToken(self):
        """返回 (remix_userid, remix_userkey) 用于持久化登录态"""
        return self.__remix_userid, self.__remix_userkey

    def getEmail(self):
        return self.__email

    def getName(self):
        """z-library 用户名（登录后由 profile 返回，可能为空）"""
        return self.__name

    # 注册相关
    def makeRegistration(self, email: str, password: str, name: str):
        return self.__makePostRequest("/eapi/user/registration",
                                      {"email": email, "password": password, "name": name}, override=True)

    def sendCode(self, email: str, password: str, name: str):
        usr_data = {"email": email, "password": password, "name": name, "rx": 215,
                    "action": "registration", "site_mode": "books", "isSinglelogin": 1}
        response = self.__makePostRequest("/papi/user/verification/send-code",
                                          data=usr_data, override=True)
        if response and response.get("success"):
            response["msg"] = "验证码已发送到邮箱，请输入验证码完成注册"
        return response

    def verifyCode(self, email: str, password: str, name: str, code: str):
        usr_data = {"email": email, "password": password, "name": name, "verifyCode": code,
                    "rx": 215, "action": "registration", "redirectUrl": "",
                    "isModa": True, "gg_json_mode": 1}
        return self.__makePostRequest("/rpc.php", data=usr_data, override=True)
