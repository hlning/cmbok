# coding:utf-8
"""
Zlibrary 客户端 - 迁移自后台 pear-admin-flask 的 applications/service/Zlibrary.py
原项目: https://github.com/bipinkrish/Zlibrary-API (Bipinkrish)
域名改为国内可访问的 zh.kid1412.by，并新增 getDownloadLink 供流式下载使用。
"""
import json
import logging
import time

import requests
from urllib.parse import urlparse

from common.config import cfg
from utils.client_util import get_system_proxy


class Zlibrary:
    def __init__(self, email: str = None, password: str = None,
                 remix_userid=None, remix_userkey: str = None):
        self.__email = None
        self.__name = None
        self.__kindle_email = None
        self.__remix_userid = None
        self.__remix_userkey = None
        self.__domain = cfg.get(cfg.zlibrary_url)
        # 候选节点列表：连接失败时自动切换；当前域名不在候选里则插到最前（兼容手动/老配置）
        self.__candidates = self._load_candidates()
        self.__timeout = 30
        # 系统代理（Windows 注册表，与浏览器同源）：开了系统代理则走代理（访问被墙节点），
        # 否则直连（TUN 模式下直连已被网络层路由）
        _proxy = get_system_proxy()
        self.__proxies = {'http': _proxy, 'https': _proxy} if _proxy else None
        self.__loggedin = False
        # 地址不可用（API 路径 404，说明当前域名非 z-library 主机）；登录/搜索据此提示功能暂不可用
        self.__unavailable = False
        # 账号今日下载额度已用完（z-library 返回 allowDownload=False 且 disallowDownloadMessage 含 daily limit）；
        # 下载据此提示「账号今日额度已用完」，区别于普通下载失败
        self.__quota_exceeded = False
        # 今日已下载数/限额（profile 返回，自登账号头像据此显示实际值，区别于软件本地计数）
        self.__downloads_today = None
        self.__downloads_limit = None
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
        user = response["user"]
        self.__email = user.get("email")
        self.__name = user.get("name")
        self.__kindle_email = user.get("kindle_email")
        self.__remix_userid = str(user["id"])
        self.__remix_userkey = user.get("remix_userkey")
        # 今日已下载数/限额（z-library profile 返回，自登账号头像据此显示实际值）
        self.__downloads_today = user.get("downloads_today")
        self.__downloads_limit = user.get("downloads_limit")
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
        """发请求并对 429/5xx 退避重试。连接失败或 404（域名非 z-library 主机）时按候选列表切换域名重试。
        成功（拿到 HTTP 业务响应，含重定向/限流等）后更新 self.__domain 为实际使用域名并持久化。
        返回 (resp, rate_limited)。全候选连接失败抛最后一个连接异常；全候选 404 返回最后一个 404 resp（上层标记 unavailable）。
        调用方均在 QThread 内，sleep 不阻塞主线程。"""
        candidates = self._candidate_order()
        last_exc = None
        last_404_resp = None
        for domain in candidates:
            try:
                resp = None
                rate_limited = False
                for attempt in range(self._MAX_RETRIES + 1):
                    resp = requests.request(method, "https://" + domain + url,
                                            timeout=self.__timeout, allow_redirects=False, proxies=self.__proxies, **kwargs)
                    if resp.status_code == 404:
                        # 当前域名非 z-library 主机（API 路径不存在），切下一个候选
                        last_404_resp = resp
                        logging.info('zlibrary 节点 %s 返回 404（非 z-library 主机），尝试下一个候选', domain)
                        break
                    if resp.status_code not in self._RETRY_STATUS:
                        # 拿到业务响应（含重定向）：记下实际使用的域名
                        if domain != self.__domain:
                            self.__domain = domain
                            cfg.set(cfg.zlibrary_url, domain)
                        return resp, False
                    if attempt >= self._MAX_RETRIES:
                        rate_limited = True
                        break
                    time.sleep(self.__retry_wait(resp, attempt))
                # 404：切下一个候选域名；限流耗尽：业务响应（临时限流）不切域名直接返回
                if resp is not None and resp.status_code == 404:
                    continue
                if domain != self.__domain:
                    self.__domain = domain
                    cfg.set(cfg.zlibrary_url, domain)
                return resp, rate_limited
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # 连接失败（DNS/连接被拒/超时）：切下一个候选域名重试
                last_exc = e
                logging.info('zlibrary 节点 %s 不可达: %s，尝试下一个候选', domain, e)
                continue
        # 全候选连接失败 或 全 404
        if last_404_resp is not None:
            return last_404_resp, False
        raise last_exc if last_exc else requests.exceptions.ConnectionError('所有 zlibrary 节点均不可达')

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
                    self._add_candidate(new_domain)
                    return self.__makePostRequest(url, data, override, _followed=True)
            # 404：API 路径不存在，说明当前域名非 z-library 主机（如配错指向其他站点），标记功能不可用
            if resp.status_code == 404:
                self.__unavailable = True
                return {"success": False, "unavailable": True, "error": "服务地址不可用（404）"}
            if rate_limited:
                return {"success": False, "rate_limited": True, "error": "请求过于频繁，请稍后再试"}
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            # 所有候选节点均连接失败（__request_with_retry 遍历完候选仍不可达）：
            # 标记功能不可用，提示「图书功能暂不可用，请等待恢复」，区别于普通错误
            self.__unavailable = True
            return {"success": False, "unavailable": True,
                    "error": "图书功能暂不可用"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __extractDomain(self, location):
        """从重定向 Location 提取域名；相对路径或空则返回 None"""
        if not location:
            return None
        netloc = urlparse(location).netloc
        return netloc or None

    def _load_candidates(self):
        """从配置加载候选节点列表。当前域名不在候选里则插到最前（兼容手动配置/老配置）。"""
        try:
            raw = cfg.get(cfg.zlibrary_url_candidates)
            candidates = json.loads(raw) if raw else []
            if not isinstance(candidates, list):
                candidates = []
            candidates = [str(d).strip() for d in candidates if d]
        except Exception:
            candidates = []
        # 去重保序
        seen, result = set(), []
        for d in candidates:
            if d and d not in seen:
                seen.add(d)
                result.append(d)
        # 当前域名不在候选里则插到最前，确保至少有一个候选可用
        if self.__domain and self.__domain not in result:
            result.insert(0, self.__domain)
        return result

    def _candidate_order(self):
        """候选域名遍历顺序：当前域名在前，其余候选按列表顺序，去重。"""
        order = [self.__domain] if self.__domain else []
        for d in self.__candidates:
            if d and d not in order:
                order.append(d)
        return order or ([self.__domain] if self.__domain else [])

    def _add_candidate(self, new_domain):
        """把域名加入候选列表最前并持久化（已存在则提到最前），下次优先使用。供重定向发现新域名时调用。"""
        if not new_domain:
            return
        if new_domain in self.__candidates:
            self.__candidates.remove(new_domain)
        self.__candidates.insert(0, new_domain)
        try:
            cfg.set(cfg.zlibrary_url_candidates, json.dumps(self.__candidates))
        except Exception:
            pass

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
                    self._add_candidate(new_domain)
                    return self.__makeGetRequest(url, params, cookies, _followed=True)
            # 404：API 路径不存在，说明当前域名非 z-library 主机，标记功能不可用
            if resp.status_code == 404:
                self.__unavailable = True
                return {"success": False, "unavailable": True, "error": "服务地址不可用（404）"}
            if rate_limited:
                return {"success": False, "rate_limited": True, "error": "请求过于频繁，请稍后再试"}
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            # 所有候选节点均连接失败（__request_with_retry 遍历完候选仍不可达）：
            # 标记功能不可用，提示「图书功能暂不可用，请等待恢复」，区别于普通错误
            self.__unavailable = True
            return {"success": False, "unavailable": True,
                    "error": "图书功能暂不可用"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def getProfile(self):
        return self.__makeGetRequest("/eapi/user/profile")

    def search(self, message: str = None, yearFrom=None, yearTo=None, languages: str = None,
               extensions=None, order: str = None, page: int = None, limit: int = None):
        logging.info('zlibrary 搜索「%s」，当前节点: %s', message or '', self.__domain)
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
        logging.info('zlibrary 下载取链接 book=%s，当前节点: %s', book_id, self.__domain)
        response = self.__makeGetRequest(f"/eapi/book/{book_id}/{book_hash}/file")
        if not response or not response.get("success"):
            return False, None, None, None
        file_info = response.get("file", {})
        allow_download = file_info.get("allowDownload", False)
        # 每次重新评估，避免缓存的 Zlibrary 实例跨调用残留上次的额度状态
        self.__quota_exceeded = False
        if not allow_download:
            # 额度用完：disallowDownloadMessage 含 "daily limit"（z-library 免费账号 10 本/日）
            msg = file_info.get("disallowDownloadMessage", "") or ""
            if "limit" in msg.lower():
                self.__quota_exceeded = True
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
            res = requests.get(ddl, headers=headers, timeout=self.__timeout, proxies=self.__proxies)
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

    def isQuotaExceeded(self) -> bool:
        """账号今日下载额度是否已用完（z-library 返回 disallowDownloadMessage 含 daily limit）。
        下载据此提示「账号今日额度已用完」，区别于普通下载失败。"""
        return self.__quota_exceeded

    def getDownloadsToday(self):
        """今日已下载数（z-library profile 返回，含外部消耗；自登账号头像据此显示实际值，
        区别于软件本地计数 logged_count）。未登录/profile 未成功返回 None。"""
        return self.__downloads_today

    def getDownloadsLimit(self):
        """每日下载限额（z-library profile 返回，免费账号通常 10）。未登录返回 None。"""
        return self.__downloads_limit

    def verifyToken(self):
        """复校 token 是否仍有效（运行时 API 失败时调用，区分 token 失效 vs 真失败）。
        返回 True=token 有效（按真失败处理），False=token 失效（需重新登录），None=地址不可用（非 token 问题）。"""
        profile = self.__makeGetRequest("/eapi/user/profile")
        if isinstance(profile, dict) and profile.get("unavailable"):
            return None
        return bool(profile and profile.get("success"))

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
