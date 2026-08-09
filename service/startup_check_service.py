# coding:utf-8
"""启动检测线程：版本/公告/地址配置检测全部后台异步执行，不阻塞主线程。

主线程在 Window.__init__ 末尾 start() 本线程后立即返回进入事件循环，
软件可快速打开；检测结果通过 pyqtSignal 回传主线程，由槽函数提示或更新配置。
"""
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from common.config import cfg, GITHUBURL, GITHUB_RELEASE_API, NOTIFICATION_URL, URL_CONFIG_URL
from utils.client_util import get_system_proxy


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
                try:
                    return response.json()
                except ValueError:
                    # 远程文件非合法 JSON（如 zlibrary_url 误用花括号无键格式）：
                    # 整体解析失败，无云端配置可用，沿用本地配置（运行时 404/重定向兜底）
                    logging.warning('远程 url_config.json 格式错误（非合法 JSON），沿用本地配置。内容预览: %s',
                                    response.text[:200])
                    return None
        except Exception:
            logging.info('检查地址配置异常: ' + traceback.format_exc())
        return None

    def _check_zlibrary_url(self, cloud_zlibrary_url):
        """启动后台探测 zlibrary_url：只检测云端地址，不检测本地配置。
        - 云端为多节点（数组）：并发探测，选延迟最低的可用节点写回 zlibrary_url；
        - 把云端完整候选列表写入 zlibrary_url_candidates（供定时检测与运行时切换，云端不频繁更新，启动拉一次即可）；
        - 兼容旧单字符串格式（视为单元素列表）；
        - 全部候选不可用仍写候选列表，并发 zlibraryUnavailable 信号提示图书功能受限；
        - 无云端地址（url_config.json 无此字段或为空）则不探测，沿用本地配置。
        """
        updates, is_unavailable = self.evaluate_zlibrary(cloud_zlibrary_url)
        # 全不可用也要先把云端候选列表写入（供定时检测/运行时切换），再发不可用提示
        if updates:
            self.urlConfigUpdated.emit(updates)
        if is_unavailable:
            self.zlibraryUnavailable.emit()

    @staticmethod
    def evaluate_zlibrary(cloud_zlibrary_url):
        """启动探测：归一化云端候选 + 写完整候选列表 + 探测全部候选选最优写 zlibrary_url。
        返回 (updates, is_unavailable)。updates=None 表云端无字段（无操作，沿用本地）。
        - 候选列表始终更新为云端完整列表（供定时检测与运行时切换；云端不频繁更新，启动拉一次即可），
          即使全部探测不可用也写入（探测不可用可能是临时网络问题，节点未必失效）；
        - zlibrary_url：探测全部候选选出的最优可用节点（与本地不同才写，重新选优不依赖当前域名）；
        - is_unavailable：全部候选探测不可用。
        """
        candidates = StartupCheckThread._normalize_candidates(cloud_zlibrary_url)
        if not candidates:
            # 云端无 zlibrary_url 字段或为空，沿用本地配置
            return None, False
        logging.info('zlibrary 启动检测云端节点: %s', candidates)
        # 启动：探测全部候选选最优（重新选最优，不依赖当前域名）
        best, _available = StartupCheckThread._pick_best_zlibrary_url(candidates)
        updates = {}
        is_unavailable = not best
        if best and best != cfg.get(cfg.zlibrary_url):
            updates['zlibrary_url'] = best
        # 把云端完整候选列表写入本地（与本地不同才写，避免无意义写配置）
        local = StartupCheckThread._local_candidates()
        if candidates != local:
            updates['zlibrary_url_candidates'] = candidates
        return updates, is_unavailable

    @staticmethod
    def _probe_candidates(candidates):
        """定时检测：先探当前 ZlibraryUrl 是否可用，可用保持；不可用才从候选重新探测选最优。
        返回 (updates, is_unavailable)。updates 只含 zlibrary_url（最优变化时），不写候选
        （候选列表由启动拉云端维护，定时检测只复用本地候选）。
        - 当前域名可用（_probe_zlibrary_url 拿到响应）-> 保持，不重新选优（避免无谓探测全部候选）；
        - 当前不可用 -> 从候选重新探测选最优，更新 zlibrary_url；
        - 全部候选不可用 -> is_unavailable=True。"""
        current = cfg.get(cfg.zlibrary_url)
        logging.info('zlibrary 定时检测节点: %s（当前: %s）', candidates, current)
        # 先探当前域名：可用则保持
        if current and StartupCheckThread._probe_zlibrary_url(current):
            return {}, False
        # 当前不可用：从候选重新探测选最优
        best, _available = StartupCheckThread._pick_best_zlibrary_url(candidates)
        if not best:
            return {}, True
        updates = {}
        if best != current:
            updates['zlibrary_url'] = best
        return updates, False

    @staticmethod
    def _local_candidates():
        """读本地 zlibrary_url_candidates（JSON 字符串数组）解析为列表，异常/空返回 []。"""
        raw = cfg.get(cfg.zlibrary_url_candidates)
        try:
            c = json.loads(raw) if raw else []
            return [str(d).strip() for d in c if str(d).strip()] if isinstance(c, list) else []
        except Exception:
            return []

    @staticmethod
    def _normalize_candidates(cloud_zlibrary_url):
        """归一化云端 zlibrary_url 为候选列表（去重保序）。
        - 兼容旧单字符串格式 -> 单元素列表；
        - 列表/元组 -> 原样去重保序；
        - 其它类型/空 -> 返回 []。"""
        if not cloud_zlibrary_url:
            return []
        if isinstance(cloud_zlibrary_url, str):
            cloud_zlibrary_url = [cloud_zlibrary_url]
        if not isinstance(cloud_zlibrary_url, (list, tuple)):
            return []
        # 去重保序
        seen, result = set(), []
        for item in cloud_zlibrary_url:
            item = str(item).strip() if item else ''
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @staticmethod
    def _pick_best_zlibrary_url(candidates):
        """并发探测候选节点，返回 (best, available_list)。
        - 探测到延迟 < 3s 的可用节点即提前返回，不再等待其余候选；
        - 全部探测完仍无低于 3s 的，取延迟最低的可用节点；
        - best：选中的可用节点（最终落地域名，无 scheme）；
        - available_list：已探测可用的最终落地域名（按延迟升序，去重），供运行时切换；
        - 全不可用返回 (None, [])。"""
        collected = []  # [(final_domain, latency)]
        ex = ThreadPoolExecutor(max_workers=min(8, len(candidates)) or 1)
        futures = {ex.submit(StartupCheckThread._probe_zlibrary_url, c): c for c in candidates}
        try:
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception:
                    r = None
                if r:
                    collected.append(r)
                    # 延迟 < 3s：直接采用，提前返回（不再等其余候选）
                    if r[1] < 3.0:
                        break
        finally:
            # 取消未开始的探测；已运行的不阻塞返回（后台跑完，最多单节点 timeout 6s）
            for f in futures:
                f.cancel()
            ex.shutdown(wait=False)
        if not collected:
            logging.info('zlibrary 所有候选节点探测不可用: %s', candidates)
            return None, []
        # 同一最终落地域名取延迟最低（多候选可能重定向到同一域名）
        best_latency = {}
        for final, latency in collected:
            if final not in best_latency or latency < best_latency[final]:
                best_latency[final] = latency
        ordered = sorted(best_latency.keys(), key=lambda f: best_latency[f])
        logging.info('zlibrary 候选探测结果（按延迟升序）: %s',
                     [(f, round(best_latency[f], 3)) for f in ordered])
        return ordered[0], ordered

    @staticmethod
    def _probe_zlibrary_url(url):
        """探测单个 zlibrary_url 可用性，跟随 HTTP 重定向，返回 (最终可用域名, 延迟秒) 或 None。
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
            # 走系统代理（与浏览器同源）：开了系统代理才探得到被墙节点，否则直连被墙节点必超时返回 None
            proxy = get_system_proxy()
            proxies = {'http': proxy, 'https': proxy} if proxy else None
            start = time.perf_counter()
            resp = requests.get(target, timeout=6, headers=headers, allow_redirects=True, proxies=proxies)
            latency = time.perf_counter() - start
            # 取最终落地域名（无 scheme），与配置存储格式一致；
            # netloc 异常为空时回退到候选地址的域名（target 已补 scheme，netloc 必为纯域名）
            final = urlparse(resp.url).netloc or urlparse(target).netloc
            return (final or url, latency)
        except Exception:
            logging.info('zlibrary_url 探测异常: ' + traceback.format_exc())
            return None


class ZlibraryHealthCheckThread(QThread):
    """zlibrary 定时健康检查线程：复用本地候选列表探测，不拉云端。

    云端不频繁更新，启动检测已把云端完整候选列表写入 cfg.zlibrary_url_candidates；
    定时检测直接读本地候选列表探测选优，更轻量。结果通过信号回主线程，
    由主线程按状态变化决定是否通知用户（恢复/暂不可用）。
    信号：
    - available(updates)：探测到可用节点（updates 可能空 = 本地已最优无需写，或仅 zlibrary_url 变化）；
    - unavailable()：全部候选不可用。
    本地无候选列表时不发信号（沿用本地，不误报）。
    """
    available = pyqtSignal(dict)
    unavailable = pyqtSignal()

    def run(self):
        # 定时检测：不拉云端（启动已拉），直接读本地候选列表探测
        candidates = StartupCheckThread._local_candidates()
        if not candidates:
            # 无候选列表（启动未拉到云端/无字段）：不探测不通知，沿用本地配置
            return
        updates, is_unavailable = StartupCheckThread._probe_candidates(candidates)
        if is_unavailable:
            self.unavailable.emit()
        else:
            self.available.emit(updates)
