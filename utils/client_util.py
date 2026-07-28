import logging
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common.config import cfg

# 热辣漫画线路（Origin/version/region/webp 与 copy 线路不同，参考 Breeze 插件）
_HOTMANGA_HOSTS = {
    'api.manga2025.com', 'mapi.hotmangasd.com', 'mapi.hotmangasf.com', 'mapi.hotmangasg.com',
    'mapi.elfgjfghkk.club', 'mapi.fgjfghkk.club', 'mapi.fgjfghkkcenter.club',
}
# 浏览器 UA（不能用 COPY/x.x.x，否则触发"破解版"风控 210）
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _is_hotmanga(url):
    host = (urlparse(url).hostname or '').lower()
    return host in _HOTMANGA_HOSTS or 'hotmanga' in host or 'fgjfghkk' in host


def _headers_for(url):
    """按 Breeze 插件 getApiHeaders 构造请求头（浏览器风，避免破解版风控）"""
    is_hot = _is_hotmanga(url)
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7",
        "version": "2025.02.12" if is_hot else "2025.05.09",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "User-Agent": _BROWSER_UA,
        "platform": "1",
        "Origin": "https://m.relamanhua.org" if is_hot else "https://2025copy.com",
        "webp": "1" if is_hot else "0",
    }
    if not is_hot:
        headers["region"] = "0"
    # authorization token 用户可选（留空匿名访问）
    token = (cfg.get(cfg.copy_token) or '').strip()
    if token:
        headers["authorization"] = f"Token {token}"
    return headers


def create_api_client():
    # 重试策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )

    session = requests.Session()

    # 可选代理（梯子本地端口）；留空=直连，适合 TUN 模式全局路由
    proxy = (cfg.get(cfg.copy_proxy) or '').strip()
    if proxy:
        session.proxies = {'http': proxy, 'https': proxy}

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    def request_with_timeout(method, url, **kwargs):
        timeout = 10  # 秒
        # 每次请求按域名动态构造请求头（热辣/copy 线路不同）
        headers = _headers_for(url)
        extra = kwargs.pop('headers', None) or {}
        headers.update(extra)
        return session.request(method, url, timeout=timeout, headers=headers, **kwargs)

    return request_with_timeout
