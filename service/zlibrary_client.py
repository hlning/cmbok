# coding:utf-8
"""
Zlibrary 客户端 - 迁移自后台 pear-admin-flask 的 applications/service/Zlibrary.py
原项目: https://github.com/bipinkrish/Zlibrary-API (Bipinkrish)
域名改为国内可访问的 zh.kid1412.by，并新增 getDownloadLink 供流式下载使用。
"""
import requests

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

    def __makePostRequest(self, url: str, data: dict = None, override=False):
        if not self.isLoggedIn() and override is False:
            return {"success": False, "error": "Not logged in"}
        try:
            return requests.post("https://" + self.__domain + url, data=data or {},
                                 cookies=self.__cookies, headers=self.__headers,
                                 timeout=self.__timeout).json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __makeGetRequest(self, url: str, params: dict = None, cookies=None):
        if not self.isLoggedIn() and cookies is None:
            return {"success": False, "error": "Not logged in"}
        try:
            return requests.get("https://" + self.__domain + url, params=params or {},
                                cookies=self.__cookies if cookies is None else cookies,
                                headers=self.__headers, timeout=self.__timeout).json()
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
