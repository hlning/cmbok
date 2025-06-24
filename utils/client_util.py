import datetime
import random

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_api_client():
    # 定义重试策略
    retry_strategy = Retry(
        total=3,  # 最大重试次数
        backoff_factor=1,  # 初始等待时间为1秒（指数退避）
        status_forcelist=[429, 500, 502, 503, 504],  # 这些状态码会触发重试
        raise_on_status=False,
        # 你可以加入其他参数，如RespectRetryAfterHeader=True
    )

    # 创建一个会话对象
    session = requests.Session()

    # 设置默认请求头
    headers = {
        "User-Agent": "COPY/2.3.0",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "source": "copyApp",
        "deviceinfo": "DCO-AL00-DCO-AL00",
        "webp": "1",
        "platform": "3",
        "referer": "com.copymanga.app-2.3.0",
        "authorization": random.choice(
            ['30f97499a1b77eb8fb3f5c717ae1a96f1470b91c', 'd5ef3229d1a6e0ff3acd00a6d42b85d8a25641a3',
             'a65a03aaef34cdc33cfdc95cef6fb897a7156bb6', 'b551ec288beac86aff02cb5a01a9063c46b2f53a',
             'bd494a59cd20ebf64e7c18aee39e3d813ffd3354']),  # 请根据实际需求填写Token
        "version": "2.3.0",
        "region": "1",
        "device": "V417IR",
        "umstring": "d8c31fb914fe4e3c9a8fe6eaadc641bc",
        "dt": datetime.datetime.now().strftime("%Y.%m.%d")
    }
    session.headers.update(headers)

    # 配置适配器，绑定重试策略
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 设置默认超时（请注意，requests自身没有会话级别超时参数，这需要在每次请求时指定）
    # 这里我们可以封装请求函数，自动加入超时
    def request_with_timeout(method, url, **kwargs):
        timeout = 5  # 秒
        return session.request(method, url, timeout=timeout, **kwargs)

    # 返回一个函数包装的会话
    return request_with_timeout
