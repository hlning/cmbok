import asyncio
import json
import logging
import math
import os
import queue
import re
import time
import traceback
import uuid
from dataclasses import dataclass

import aiohttp
import httpx
import requests
from PyQt5.QtCore import QThread, QMutex, pyqtSignal
from ebooklib import epub
from natsort import natsorted

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from service.zlibrary_client import Zlibrary
try:
    from service.builtin_accounts import BUILTIN_ACCOUNTS
except ImportError:
    BUILTIN_ACCOUNTS = []
from utils.base_utils import get_current_time, get_file_extension, deal_url
from utils.client_util import create_api_client
from utils.utils_book_type_convert import img_to_pdf, convert_epub_to_mobi
from utils.utils_files_and_folders import del_file, del_folder, del_folder_images
from view.download_interface import book_process_signals, download_signals, comic_process_signals

comic_search_lock = QMutex()
book_search_lock = QMutex()
download_comic_lock = QMutex()

# 内置账号 token 缓存：email -> (remix_userid, remix_userkey, cache_time)
# 避免每次搜索/下载都 POST /eapi/user/login，触发 Cloudflare 429 限流
_builtin_token_cache = {}
_builtin_token_lock = QMutex()
_BUILTIN_TOKEN_TTL = 600  # 10 分钟


def _get_builtin_zlibrary(email, password):
    """获取内置账号的 Zlibrary 实例：优先用缓存的 token 走 profile 校验，失效再 login。
    返回已登录的 Z；地址不可用（404）时返回 isUnavailable()=True 的 Z 供调用方判断；其余失败返回 None。"""
    _builtin_token_lock.lock()
    cached = _builtin_token_cache.get(email)
    _builtin_token_lock.unlock()
    if cached:
        remix_userid, remix_userkey, ts = cached
        if time.time() - ts < _BUILTIN_TOKEN_TTL:
            Z = Zlibrary(remix_userid=remix_userid, remix_userkey=remix_userkey)
            if Z.isLoggedIn():
                return Z
            if Z.isUnavailable():
                return Z  # 地址不可用（404），回传给调用方判断
    # 缓存失效/校验失败，重新 login
    Z = Zlibrary(email=email, password=password)
    if Z.isLoggedIn():
        remix_userid, remix_userkey = Z.getRemixToken()
        if remix_userid and remix_userkey:
            _builtin_token_lock.lock()
            _builtin_token_cache[email] = (remix_userid, remix_userkey, time.time())
            _builtin_token_lock.unlock()
        return Z
    if Z.isUnavailable():
        return Z  # 地址不可用（404），回传给调用方判断
    return None


# 搜索图书
@dataclass
class Book:
    book_name: str
    start_date: str
    end_date: str
    language: str
    extensions: str


class BookSearch(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, book, index=0):
        super(BookSearch, self).__init__()
        self.book = book
        self.index = index

    def run(self):
        book_search_lock.lock()
        try:
            if cfg.get(cfg.use_zlibrary_builtin_account):
                # 内置账号模式：轮询内置账号搜索
                results = self._search_with_builtin_account()
                if results is None:
                    self.success.emit('no_account', None)
                elif results.get('rate_limited'):
                    self.success.emit('rate_limited', None)
                elif results.get('unavailable'):
                    self.success.emit('unavailable', None)
                else:
                    self._emit_success(results)
            else:
                # 自有账号模式：用登录 token
                remix_userid = cfg.get(cfg.zlibrary_remix_userid)
                remix_userkey = cfg.get(cfg.zlibrary_remix_userkey)
                if not remix_userid or not remix_userkey:
                    self.success.emit('no_login', None)
                    return
                Z = Zlibrary(remix_userid=remix_userid, remix_userkey=remix_userkey)
                if not Z.isLoggedIn():
                    # 地址不可用（404）与登录失效区分提示
                    if Z.isUnavailable():
                        self.success.emit('unavailable', None)
                    else:
                        self.success.emit('no_login', None)
                    return
                results = self._do_search(Z)
                if results and results.get('rate_limited'):
                    self.success.emit('rate_limited', None)
                elif results and results.get('unavailable'):
                    self.success.emit('unavailable', None)
                elif results is None or not results.get('success'):
                    self.success.emit('fail', None)
                else:
                    self._emit_success(results)
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('查询图书失败')
        finally:
            book_search_lock.unlock()

    def _do_search(self, Z):
        return Z.search(
            message=self.book.book_name,
            yearFrom=(None if self.book.start_date == '起始年份' else self.book.start_date),
            yearTo=(None if self.book.end_date == '截止年份' else self.book.end_date),
            languages=(None if self.book.language == 'language' else self.book.language),
            extensions=(None if self.book.extensions == '格式' else self.book.extensions),
            page=self.index,
            limit=60
        )

    def _emit_success(self, results):
        # 精简字段，保持与原后台返回结构一致
        new_books = []
        for book in results.get('books', []):
            new_books.append({
                'id': book.get('id'),
                'hash': book.get('hash'),
                'title': book.get('title'),
                'author': book.get('author'),
                'cover': book.get('cover'),
                'year': book.get('year'),
                'language': book.get('language'),
                'filesizeString': book.get('filesizeString'),
                'extension': book.get('extension')
            })
        results['books'] = new_books
        self.success.emit('success', results)

    def _search_with_builtin_account(self):
        for account in BUILTIN_ACCOUNTS:
            Z = _get_builtin_zlibrary(account['email'], account['password'])
            if not Z:
                continue
            # 地址不可用（404）：所有账号都会失败，停止轮询
            if Z.isUnavailable():
                return {'unavailable': True}
            results = self._do_search(Z)
            if results and results.get('success'):
                return results
            if results and results.get('unavailable'):
                return results
            if results and results.get('rate_limited'):
                # 被限流，停止轮询其他账号，避免加剧 429
                return results
        return None


# 下载图书
# 全局图书当前下载数量
book_active_downloads = 0
# 下载队列
book_waiting_queue = queue.Queue()
# 持有所有运行中的 BookDownload 引用，防止队列派生的线程被 GC 导致闪退（QThread 运行中被回收会 segfault）
book_download_threads = set()
# 内置账号每日下载计数（持久化到 app/config/builtin_count.json，跨日重置，每日最多5本，重启不丢）
BUILTIN_DAILY_LIMIT = 5
BUILTIN_COUNT_FILE = os.path.join('app', 'config', 'builtin_count.json')
builtin_count_lock = QMutex()


def _read_builtin_count():
    """读取持久化的 (date, count)"""
    try:
        with open(BUILTIN_COUNT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('date', ''), int(data.get('count', 0))
    except Exception:
        return '', 0


def _write_builtin_count(date, count):
    try:
        os.makedirs(os.path.dirname(BUILTIN_COUNT_FILE), exist_ok=True)
        with open(BUILTIN_COUNT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'date': date, 'count': count}, f)
    except Exception:
        logging.info('写入内置账号计数失败: ' + traceback.format_exc())


def get_builtin_download_count():
    """今日内置账号已下载数量（跨日自动归零），供 UI 下载前检查"""
    builtin_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, count = _read_builtin_count()
        return count if date == today else 0
    finally:
        builtin_count_lock.unlock()


def _reserve_builtin_download():
    """原子检查并预留一个下载名额（计数+1）。返回 (ok, start_index)；超限返回 (False, 0)。"""
    builtin_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, count = _read_builtin_count()
        if date != today:
            count = 0
        if count >= BUILTIN_DAILY_LIMIT:
            return False, 0
        count += 1
        _write_builtin_count(today, count)
        return True, (count - 1) % max(len(BUILTIN_ACCOUNTS), 1)
    finally:
        builtin_count_lock.unlock()


def _release_builtin_download():
    """下载失败时释放预留的名额（计数-1）"""
    builtin_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, count = _read_builtin_count()
        if date == today and count > 0:
            _write_builtin_count(today, count - 1)
    finally:
        builtin_count_lock.unlock()


# 登录账号每日下载计数（按账号 userid 分账户，持久化到 app/config/logged_count.json，
# 跨日重置，每个账号每日最多10本，重启不丢）
LOGGED_DAILY_LIMIT = 10
LOGGED_COUNT_FILE = os.path.join('app', 'config', 'logged_count.json')
logged_count_lock = QMutex()


def _read_logged_count():
    """读取持久化的 (date, accounts_dict)"""
    try:
        with open(LOGGED_COUNT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('date', ''), data.get('accounts', {}) or {}
    except Exception:
        return '', {}


def _write_logged_count(date, accounts):
    try:
        os.makedirs(os.path.dirname(LOGGED_COUNT_FILE), exist_ok=True)
        with open(LOGGED_COUNT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'date': date, 'accounts': accounts}, f)
    except Exception:
        logging.info('写入登录账号计数失败: ' + traceback.format_exc())


def get_logged_download_count(userid=None):
    """今日指定账号已下载数量（跨日自动归零）；userid 为空返回 0"""
    if not userid:
        return 0
    userid = str(userid)
    logged_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, accounts = _read_logged_count()
        if date != today:
            return 0
        return int(accounts.get(userid, 0))
    finally:
        logged_count_lock.unlock()


def _reserve_logged_download(userid=None):
    """原子检查并预留一个下载名额（该账号计数+1）。超限返回 False。"""
    if not userid:
        return False
    userid = str(userid)
    logged_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, accounts = _read_logged_count()
        if date != today:
            accounts = {}
        count = int(accounts.get(userid, 0))
        if count >= LOGGED_DAILY_LIMIT:
            return False
        accounts[userid] = count + 1
        _write_logged_count(today, accounts)
        return True
    finally:
        logged_count_lock.unlock()


def _release_logged_download(userid=None):
    """下载失败时释放预留的名额（该账号计数-1）"""
    if not userid:
        return
    userid = str(userid)
    logged_count_lock.lock()
    try:
        today = get_current_time('%Y-%m-%d')
        date, accounts = _read_logged_count()
        if date == today and accounts.get(userid, 0) > 0:
            accounts[userid] = int(accounts[userid]) - 1
            _write_logged_count(today, accounts)
    finally:
        logged_count_lock.unlock()


class BookDownload(QThread):
    success = pyqtSignal(object)

    def __init__(self, book):
        super(BookDownload, self).__init__()
        self.book = book
        self.cover = book['cover']
        self.book_name = book['title']
        self.book_author = book['author']
        self.book_id = book['id']
        self.book_hash = book['hash']
        self.book_extension = book['extension']
        self.process = 0
        # 持有自身引用，防止队列派生时被 GC（QThread 运行中被回收会闪退），finished 后移除
        book_download_threads.add(self)
        self.finished.connect(lambda: book_download_threads.discard(self))

    def _stream_download(self, ddl, headers, history_id, output_file):
        """流式下载文件并实时更新进度，返回 'success' / 'error'"""
        response = requests.get(ddl, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
        total = int(response.headers.get('Content-Length', 0))
        downloaded = 0
        last_process = 0
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        self.process = int(downloaded * 100 / total)
                        if self.process >= 100:
                            self.process = 99
                        # 每变化 >=2% 才写库+发信号，减少开销
                        if self.process - last_process >= 2 or self.process == 99:
                            sqlite_util = SQLiteDatabase()
                            try:
                                sqlite_util.update_data('cmbok_download_history',
                                                        {'process': self.process},
                                                        {'id': history_id})
                                book_process_signals.success.emit(history_id, self.process)
                            except Exception:
                                sqlite_util.rollback()
                            finally:
                                sqlite_util.close()
                            last_process = self.process
        return 'success'

    def _download_file_stream(self, history_id):
        """自有账号模式：用登录 token 获取下载链接并流式下载，每个账号每日最多10本（按 userid 计数，预留名额防竞态）"""
        remix_userid = cfg.get(cfg.zlibrary_remix_userid)
        remix_userkey = cfg.get(cfg.zlibrary_remix_userkey)
        # 原子检查并预留一个名额，超限直接返回
        if not _reserve_logged_download(remix_userid):
            return 'no_num'

        Z = Zlibrary(remix_userid=remix_userid, remix_userkey=remix_userkey)
        if not Z.isLoggedIn():
            _release_logged_download(remix_userid)
            return 'no_account'

        allow, filename, ddl, headers = Z.getDownloadLink(self.book_id, self.book_hash)
        if not allow or not ddl:
            _release_logged_download(remix_userid)
            return 'error'

        invalid_chars = r'[<>:"/\\|?*]'
        sanitized_filename = re.sub(invalid_chars, '', self.book_name)
        output_file = os.path.join(cfg.get(cfg.downloadFolder),
                                   f'{sanitized_filename}_{self.book_id}.{self.book_extension}')
        status = self._stream_download(ddl, headers, history_id, output_file)
        if status != 'success':
            _release_logged_download(remix_userid)
        return status

    def _download_with_builtin_account(self, history_id):
        """内置账号模式：轮询硬编码内置账号下载，每日最多5本（持久化计数，预留名额防竞态）"""
        # 原子检查并预留一个名额，超限直接返回
        reserved, start = _reserve_builtin_download()
        if not reserved:
            return 'no_num'

        if not BUILTIN_ACCOUNTS:
            _release_builtin_download()
            return 'no_account'

        invalid_chars = r'[<>:"/\\|?*]'
        sanitized_filename = re.sub(invalid_chars, '', self.book_name)
        output_file = os.path.join(cfg.get(cfg.downloadFolder),
                                   f'{sanitized_filename}_{self.book_id}.{self.book_extension}')

        # 按计数轮转起点，均匀分散到各账号
        for i in range(len(BUILTIN_ACCOUNTS)):
            account = BUILTIN_ACCOUNTS[(start + i) % len(BUILTIN_ACCOUNTS)]
            Z = _get_builtin_zlibrary(account['email'], account['password'])
            if not Z or Z.isUnavailable():
                continue
            allow, filename, ddl, headers = Z.getDownloadLink(self.book_id, self.book_hash)
            if not allow or not ddl:
                continue
            status = self._stream_download(ddl, headers, history_id, output_file)
            if status == 'success':
                return 'success'  # 成功，保留预留名额
        # 所有账号都失败，释放预留名额
        _release_builtin_download()
        return 'no_account'

    def download_success(self, history_id):
        global book_active_downloads
        with SQLiteDatabase() as db:
            # 下载完成
            book_active_downloads -= 1
            db.update_data('cmbok_download_history',
                           {'status': 3, 'process': 100, 'finish_time': get_current_time()},
                           {'id': history_id})
            download_signals.success.emit('success', self.book_name, self.book_author, 2)

    def download_fail(self, download_status, history_id):
        global book_active_downloads
        with SQLiteDatabase() as db:
            # 下载失败
            book_active_downloads -= 1
            if download_status == 'error':
                db.update_data('cmbok_download_history',
                               {'status': 0, 'finish_time': get_current_time()},
                               {'id': history_id})
                download_signals.success.emit('error', self.book_name, self.book_author, 2)
            elif download_status == 'no_account':
                db.update_data('cmbok_download_history',
                               {'status': -4, 'finish_time': get_current_time()},
                               {'id': history_id})
                download_signals.success.emit('no_account', self.book_name, self.book_author, 2)
            elif download_status == 'no_num':
                db.update_data('cmbok_download_history',
                               {'status': -5, 'finish_time': get_current_time()},
                               {'id': history_id})
                download_signals.success.emit('no_num', self.book_name, self.book_author, 2)

    def run(self):
        global book_active_downloads
        sqlite_util = SQLiteDatabase()
        history_id = 0

        try:
            self.success.emit('success')
            # 先保存下载记录
            history_id = sqlite_util.insert_data('cmbok_download_history', {'cover': '',
                                                                            'name': self.book_name,
                                                                            'author': self.book_author,
                                                                            'key': self.book_id,
                                                                            'book_hash': self.book_hash,
                                                                            'book_extension': self.book_extension,
                                                                            'process': 0,
                                                                            'type': 2,
                                                                            'status': 2})
            # 队列是否已满
            if book_active_downloads < cfg.get(cfg.downloadThreadNum):
                # 开始下载
                book_active_downloads += 1
                sqlite_util.update_data('cmbok_download_history',
                                        {'status': 1, 'start_time': get_current_time()},
                                        {'id': history_id})

                # 本地直连 z-library 下载（按模式切换）
                if cfg.get(cfg.use_zlibrary_builtin_account):
                    download_status = self._download_with_builtin_account(history_id)
                else:
                    download_status = self._download_file_stream(history_id)
                if download_status == 'success':
                    self.download_success(history_id)
                else:
                    self.download_fail(download_status, history_id)

                # 继续下一个等待的下载任务（如果有的话）
                if not book_waiting_queue.empty():
                    next_book = book_waiting_queue.get()
                    bookDownload = BookDownload(book=next_book)
                    bookDownload.start()
            else:
                book_waiting_queue.put(self.book)
        except Exception:
            sqlite_util.rollback()
            self.download_fail('error', history_id)
            # 继续下一个等待的下载任务（如果有的话）
            if not book_waiting_queue.empty():
                next_book = book_waiting_queue.get()
                bookDownload = BookDownload(book=next_book)
                bookDownload.start()
            logging.info(traceback.format_exc())
            logging.info('下载图书失败')
        finally:
            sqlite_util.close()


# 下载图书


# 搜索漫画
class ComicSearch(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, comic_name, offset=0):
        super(ComicSearch, self).__init__()
        self.comic_name = comic_name
        self.offset = offset
        self.PROXIES = {}

    def run(self):
        comic_search_lock.lock()
        try:
            url = f"{cfg.get(cfg.copy_url)}api/v3/search/comic?format=json&platform=1&q={self.comic_name}&limit=27&offset={self.offset * 27}"
            api_client = create_api_client()
            response = api_client("GET", url)
            if response.status_code == 200:
                data = json.loads(response.text)
                results = data["results"]
                self.success.emit('success', results)
            else:
                self.success.emit('fail', None)
        except requests.exceptions.Timeout:
            self.success.emit('timeout', None)
            logging.info(traceback.format_exc())
            logging.info('请求超时')
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('查询漫画失败')
        finally:
            comic_search_lock.unlock()


# 获取漫画分组信息
class ComicGroups(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, path_word):
        super(ComicGroups, self).__init__()
        self.path_word = path_word

    def run(self):
        try:
            url = f"{cfg.get(cfg.copy_url)}api/v3/comic2/{self.path_word}"
            api_client = create_api_client()
            response = api_client("GET", url)
            if response.status_code == 200:
                data = json.loads(response.text)
                results = {'comic_path_word': self.path_word, 'groups': data['results']['groups']}
                self.success.emit('success', results)
            else:
                self.success.emit('fail', None)
        except requests.exceptions.Timeout:
            self.success.emit('timeout', None)
            logging.info(traceback.format_exc())
            logging.info('请求超时')
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('获取漫画分组信息失败')


# 获取漫画章节信息
class ComicChapters(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, comic_path_word, group_path_word, group_count):
        super(ComicChapters, self).__init__()
        self.comic_path_word = comic_path_word
        self.group_path_word = group_path_word
        self.group_count = group_count

    def run(self):
        chapters = []
        limit = 500  # 每次请求的数量
        offset = 0
        try:
            while offset < self.group_count:
                url = f"{cfg.get(cfg.copy_url)}api/v3/comic/{self.comic_path_word}/group/{self.group_path_word}/chapters?limit={limit}&offset={offset}"
                api_client = create_api_client()
                response = api_client("GET", url)
                if response.status_code == 200:
                    data = json.loads(response.text)
                    list_data = data['results'].get('list', [])
                    chapters.extend(list_data)
                    # 更新 offset
                    offset += limit
                    # 如果剩余的数量少于 limit，可能最后一次请求不到 limit 数量
                    if len(list_data) < limit:
                        self.success.emit('success', chapters)
                        break
                else:
                    self.success.emit('fail', None)
                    return  # 请求失败就退出
        except requests.exceptions.Timeout:
            self.success.emit('timeout', None)
            logging.info(traceback.format_exc())
            logging.info('请求超时')
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('获取漫画章节信息失败')


# 查询收藏记录
class ComicCollects(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, index, text, type, folder_id, limit):
        super(ComicCollects, self).__init__()
        self.index = index
        self.text = text
        self.type = type
        self.folder_id = folder_id
        self.limit = limit

    def run(self):
        sqlite_util = SQLiteDatabase()
        try:
            # 查询文件夹 + 收藏记录
            if self.text is not None and self.text != '':
                datas = sqlite_util.query_records(
                    conditions={'name': f'%{self.text}%', 'type': self.type},
                    order_by='collection_time DESC', limit=self.limit,
                    offset=self.index * self.limit)
            else:
                datas = sqlite_util.query_folder_records(
                    conditions={'name': f'%{self.text}%', 'type': self.type, 'folder_id': self.folder_id},
                    order_by='is_folder, add_time DESC, id',
                    limit=self.limit,
                    offset=self.index * self.limit)

            self.success.emit('success', datas)
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('获取漫画目录信息失败')
        finally:
            sqlite_util.close()


# 拷贝漫画——获取漫画目录下所有图片
download_locked = False


class ComicChapterImages(QThread):
    success = pyqtSignal(object)

    def __init__(self, comic_name, comic_path_word, comic_author, checked_chapters):
        super(ComicChapterImages, self).__init__()
        self.comic_name = comic_name
        self.comic_path_word = comic_path_word
        self.checked_chapters = checked_chapters
        self.comic_author = comic_author

    def run(self):
        global download_locked
        if download_locked:
            self.success.emit('lock')
        else:
            download_comic_lock.lock()
            download_locked = True
            try:
                self.success.emit('success')
                comicDownload = ComicDownload()
                asyncio.run(
                    comicDownload.start_download_chapter(self.checked_chapters, self.comic_path_word, self.comic_name,
                                                         self.comic_author))
            except Exception as e:
                self.success.emit('error')
                logging.info(traceback.format_exc())
                logging.info('获取漫画目录下所有图片失败')

            finally:
                download_comic_lock.unlock()
            download_locked = False


class ComicDownload(QThread):
    success = pyqtSignal()

    def __init__(self):
        super(ComicDownload, self).__init__()
        self.process = 0

    # 下载单个图片的异步函数
    async def async_download_image(self, url, save_path, filename, history_id, shared_data, process):
        sqlite_util = SQLiteDatabase()
        # 保存图片，文件名可根据需要修改
        try:
            filename = filename.replace('/', '')
            if not os.path.exists(os.path.join(save_path, filename)):
                proxy = (cfg.get(cfg.copy_proxy) or '').strip() or None
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(sock_read=20)) as session:
                    async with session.get(url, proxy=proxy) as response:
                        response.raise_for_status()  # 抛出HTTP错误
                        if response.status == 200:
                            image_data = await response.read()
                            with open(os.path.join(save_path, filename), 'wb') as f:
                                f.write(image_data)
                            # 更新进度
                            shared_data['process'] += process
                            if shared_data['process'] >= 100:
                                shared_data['process'] = 99
                            sqlite_util.update_data('cmbok_download_history',
                                                    {'process': shared_data['process']},
                                                    {'id': history_id})
                            comic_process_signals.success.emit(history_id, shared_data['process'])
                        else:
                            logging.info(f"Failed to download {url}")
        except asyncio.TimeoutError:
            logging.info(traceback.format_exc())
            logging.info("请求超时")
        except Exception as e:
            logging.info(traceback.format_exc())
            logging.info(f'图片url：{url}，图片名称：{filename}')
            logging.info('下载图片异常')
        finally:
            sqlite_util.close()

    # 下载章节图片
    async def start_download_chapter(self, chapters, comic_path_word, comic_name, comic_author):
        async with aiohttp.ClientSession() as session:
            sqlite_util = SQLiteDatabase()
            try:
                chapter_tasks = []
                id_map = {}
                for chapter in chapters:
                    # 先保存保存下载记录
                    history_id = sqlite_util.insert_data('cmbok_download_history', {'cover': '',
                                                                                    'name': comic_name,
                                                                                    'author': comic_author,
                                                                                    'key': comic_path_word,
                                                                                    'chapter_name': chapter['name'],
                                                                                    'chapter_path_word': chapter[
                                                                                        'uuid'],
                                                                                    'status': 2,
                                                                                    'process': 0,
                                                                                    'type': 1,
                                                                                    'start_time': ''})
                    id_map[comic_path_word + chapter['uuid']] = history_id

                for chapter in chapters:
                    chapter_images = self.get_chapter_images(comic_path_word, chapter['uuid'])

                    if chapter_images is not None:
                        shared_data = {'process': 0}
                        # 每次同时下载指定数量的章节
                        task = asyncio.create_task(
                            self.start_download_chapter_images(id_map[comic_path_word + chapter['uuid']],
                                                               chapter_images,
                                                               comic_path_word, comic_name,
                                                               comic_author,
                                                               chapter['name'], shared_data))
                        chapter_tasks.append(task)
                        # 下载记录更新状态
                        sqlite_util.update_data('cmbok_download_history',
                                                {'status': 1, 'start_time': get_current_time()},
                                                {'id': id_map[comic_path_word + chapter['uuid']]})
                        download_signals.success.emit('update', comic_name, chapter['name'], 1)
                        # 如果达到并发章节限制，则等待当前任务完成
                        if len(chapter_tasks) >= cfg.get(cfg.downloadThreadNum):
                            # 等待第一个完成的任务
                            done, pending = await asyncio.wait(chapter_tasks, return_when=asyncio.FIRST_COMPLETED)
                            for completed in done:
                                chapter_tasks.remove(completed)  # 移除已完成的任务
                    else:
                        # 下载记录更新状态
                        sqlite_util.update_data('cmbok_download_history',
                                                {'status': -2},
                                                {'id': id_map[comic_path_word + chapter['uuid']]})
                        download_signals.success.emit('fail', comic_name, chapter['name'], 1)

                # 等待剩余的任务完成
                if chapter_tasks:
                    await asyncio.gather(*chapter_tasks)
            except Exception:
                download_signals.success.emit('fail', comic_name, chapter['name'], 1)
                logging.info(traceback.format_exc())
                logging.info('下载异常')
            finally:
                sqlite_util.close()

    async def start_download_chapter_images(self, history_id, chapter_images, comic_path_word, comic_name, comic_author,
                                            chapter_name, shared_data):
        tasks = [self.download_chapter_images(history_id, chapter_images, comic_path_word, comic_name, comic_author,
                                              chapter_name, shared_data)]
        await asyncio.gather(*tasks)

    async def download_chapter_images(self, history_id, image_urls, comic_id, comic_name, comic_author, chapter_name,
                                      shared_data):
        logging.info(f'{comic_name}{chapter_name}图片开始下载')
        download_folder = cfg.get(cfg.downloadFolder)
        invalid_chars = r'[<>:"/\\|?*]'
        # 替换特殊字符为空字符
        chapter_name = re.sub(invalid_chars, '', chapter_name)
        path = f"{download_folder}/{comic_name}/{chapter_name}"
        os.makedirs(path, exist_ok=True)
        process = int(100 / len(image_urls))
        size = math.ceil(len(image_urls) / 100)
        tasks = [
            self.async_download_image(url, path, 'Cmbok_' + str(index) + get_file_extension(url), history_id,
                                      shared_data, (process if process > 0 else 1) if index % size == 0 else 0)
            for
            index, url in
            enumerate(image_urls)]
        await asyncio.gather(*tasks)
        logging.info(f'{comic_name}{chapter_name}图片下载完成')
        # 下载完成，合并epub
        self.images_to_epub(history_id, download_folder, comic_id, comic_name, comic_author, chapter_name)

    # 下载章节图片

    # 生成epub
    def images_to_epub(self, history_id, download_folder, comic_id, comic_name, comic_author, chapter_name):
        logging.info(f'{comic_name}{chapter_name}开始转换epub')
        sqlite_util = SQLiteDatabase()
        try:
            book = epub.EpubBook()
            book.set_identifier(str(comic_id))
            book.set_title(chapter_name)
            book.set_language('en')
            book.add_author(comic_author)
            path = f"{download_folder}/{comic_name}/{chapter_name}"
            # 获取目录下的所有文件
            files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            # 进行自然排序
            sorted_files = natsorted(files)
            # 漫画图片目录
            for index, file_name in enumerate(sorted_files):
                img_item = epub.EpubItem(uid=file_name, file_name=file_name,
                                         media_type='image/jpeg')
                with open(f'{path}/{file_name}', 'rb') as f:
                    img_item.set_content(f.read())
                    # if index == 0:
                    #    book.add_item(epub.EpubItem(uid="cover", file_name=file_name,
                    #                                media_type='image/jpeg',
                    #                                content=f.read()))
                book.add_item(img_item)

                chapter = epub.EpubHtml(title=f'Image {index}', file_name=f'chap_{index}.xhtml', lang='en')
                chapter.set_content(f'<html><body><img src="{img_item.file_name}" /></body></html>')
                book.add_item(chapter)
                book.spine.append(chapter)
            nav = epub.EpubNav()
            book.add_item(nav)

            # epub是否保存到漫画根目录
            epubSaveFolder = cfg.get(cfg.epubSaveFolder)
            if epubSaveFolder:
                save_path = f"{download_folder}/{comic_name}"
            else:
                save_path = f"{path}"
            epub.write_epub(os.path.join(save_path, f'{comic_name}_{chapter_name}.epub'), book)

            # 更新下载记录
            sqlite_util.update_data('cmbok_download_history', {'status': 3, 'process': 100,
                                                               'finish_time': get_current_time()},
                                    {'id': history_id})

            # 是否生成pdf
            isSavePdf = cfg.get(cfg.isSavePdf)
            if isSavePdf:
                img_to_pdf(sorted_files, path, f'{save_path}/{comic_name}_{chapter_name}.pdf')

            # 是否转换mobi
            if cfg.get(cfg.isSaveMobi):
                # 先生成pdf
                if not isSavePdf:
                    img_to_pdf(sorted_files, path, f'{save_path}/{comic_name}_{chapter_name}.pdf')
                # 转mobi，需要配置ebook-convert
                calibrePath = cfg.get(cfg.calibrePath)
                calibre_bin = 'ebook-convert.exe' if os.name == 'nt' else 'ebook-convert'
                if calibrePath != '' and os.path.isfile(calibrePath) and os.path.basename(
                        calibrePath) == calibre_bin:
                    convert_epub_to_mobi(calibrePath, cfg.get(cfg.calibreOutputDevice),
                                         f'{comic_name}_{chapter_name}', f'{save_path}/{comic_name}_{chapter_name}.pdf',
                                         f'{save_path}/{comic_name}_{chapter_name}.mobi')
                    # 转换完成删除pdf
                    if not isSavePdf:
                        del_file(f'{save_path}/{comic_name}_{chapter_name}.pdf')

            # 合并epub之后，根据配置是否删除章节图片
            if cfg.get(cfg.isDelChapterImages):
                if epubSaveFolder:
                    del_folder(path)
                else:
                    del_folder_images(path)

            download_signals.success.emit('success', comic_name, chapter_name, 1)
        except Exception:
            sqlite_util.rollback()
            # 下载记录更新状态
            sqlite_util.update_data('cmbok_download_history',
                                    {'status': -1},
                                    {'id': history_id})
            logging.info(traceback.format_exc())
            logging.info('保存下载记录异常')
        finally:
            sqlite_util.close()
        logging.info(f'{comic_name}{chapter_name}转换epub完成')

    def get_chapter_images(self, comic_path_word, chapter_id):
        # 热辣线路用 chapter，copy 线路用 chapter2；两者回退（参考 Breeze 插件）
        for path in ('chapter', 'chapter2'):
            try:
                url = f"{cfg.get(cfg.copy_url)}api/v3/comic/{comic_path_word}/{path}/{chapter_id}"
                api_client = create_api_client()
                response = api_client("GET", url)
                if response.status_code == 200:
                    data = json.loads(response.text)
                    contents = data.get('results', {}).get('chapter', {}).get('contents')
                    if contents:
                        return [i['url'] for i in contents]
            except Exception:
                logging.info(traceback.format_exc())
                logging.info('获取图片失败')
        return None


# 漫画站点——获取漫画目录下所有图片

class WebsiteChapterFetchThread(QThread):
    """漫画站点章节取图（直连模式，use_frame=0）

    对应油猴脚本 getImage 的 useFrame:false 分支：直接 requests 请求章节页 HTML，
    用 BeautifulSoup 按 img_dom 选择器限定范围提取图片地址，并跟随"下一页"链接合并多页图片。
    """
    success = pyqtSignal(str, str, list, str)

    def __init__(self, comic_name, chapter_name, url, img_dom, img_attr, parent=None):
        super(WebsiteChapterFetchThread, self).__init__(parent)
        self.comic_name = comic_name
        self.chapter_name = chapter_name
        self.url = url
        self.img_dom = (img_dom or '').strip()
        self.img_attr = (img_attr or '').strip()

    def run(self):
        try:
            if 'zaimanhua.com' in self.url:
                # 再漫画：阅读器为 Nuxt SPA，直连章节接口取 page_url
                imgs = self._fetch_zaimanhua_api()
            else:
                imgs = self._fetch_all_pages()
            # 去重保序
            seen = set()
            out = []
            for u in imgs:
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
            logging.info(f'[站点下载] 直连取图完成: {len(out)} 张 | 章节: {self.chapter_name}')
            self.success.emit(self.comic_name, self.chapter_name, out, self.url)
        except Exception:
            logging.info(traceback.format_exc())
            self.success.emit(self.comic_name, self.chapter_name, [], self.url)

    def _fetch_zaimanhua_api(self):
        # 再漫画阅读器是 Nuxt SPA，图片由接口返回；章节URL: /view/<slug>/<comic_id>/<chapter_id>
        m = re.search(r'/view/[^/]+/(\d+)/(\d+)', self.url)
        if not m:
            logging.info(f'[站点下载] 再漫画URL无法解析章节号: {self.url}')
            return []
        comic_id, chapter_id = m.group(1), m.group(2)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.url,
        }
        api = self._origin() + 'api/v1/comic2/chapter/detail'
        resp = requests.get(api, headers=headers, params={'chapter_id': chapter_id, 'comic_id': comic_id}, timeout=20)
        data = resp.json() or {}
        if data.get('errno') != 0:
            logging.info(f'[站点下载] 再漫画接口返回错误: {data.get("errmsg")} | comic_id={comic_id} chapter_id={chapter_id}')
            return []
        page_url = ((data.get('data') or {}).get('chapterInfo') or {}).get('page_url') or []
        logging.info(f'[站点下载] 再漫画接口取图: {len(page_url)} 张 | chapter_id={chapter_id}')
        return page_url

    def _fetch_all_pages(self):
        from urllib.parse import urljoin
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self._origin(),
        }
        imgs = []
        url = self.url
        visited = set()
        for _ in range(8):
            if not url or url in visited:
                break
            visited.add(url)
            resp = requests.get(url, headers=headers, timeout=20)
            html = resp.text or ''
            imgs.extend(self._extract_imgs(html))
            # 跟随"下一页"链接（包子漫画 next_chapter 形式）
            m = re.search(r'next_chapter"[^>]*?href="([^"]+)"', html)
            if m:
                url = urljoin(url, m.group(1))
            else:
                break
        return imgs

    def _extract_imgs(self, html):
        if not html:
            return []
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')
        # 按 img_dom 选择器限定范围（如 #_imageList img），未配置则取全部 img
        if self.img_dom:
            nodes = soup.select(self.img_dom)
        else:
            nodes = soup.find_all('img')
        found = []
        for node in nodes:
            if self.img_attr:
                # 按配置属性名取（如 data-url、data-original），取不到回退 src
                src = node.get(self.img_attr) or node.get('src')
            else:
                # 未配置属性时取 src（对标油猴脚本包子漫画 <img.*src 逻辑，避免误取懒加载占位图）
                src = node.get('src')
            if src:
                found.append(src)
        # 过滤图标/占位/加载图
        bad = ('logo', 'data:image', 'blank', 'placeholder', 'loading.gif', 'load.gif', 'favicon')
        return [u for u in found if not any(b in u.lower() for b in bad)]

    def _origin(self):
        try:
            from urllib.parse import urlparse
            p = urlparse(self.url)
            return f'{p.scheme}://{p.netloc}/'
        except Exception:
            return ''


class ComicWebsiteChapterImages(QThread):
    success = pyqtSignal(object)

    def __init__(self, comic_name, chapter_name, chapter_images, referer=''):
        super(ComicWebsiteChapterImages, self).__init__()
        self.comic_name = comic_name
        self.chapter_images = chapter_images
        self.chapter_name = chapter_name
        self.referer = referer or ''

    def run(self):
        try:
            asyncio.run(self.download_chapter_images(self.chapter_images, self.comic_name, self.chapter_name))

        except Exception as e:
            self.success.emit(self.comic_name)
            logging.info(traceback.format_exc())
            logging.info('下载所有图片失败')

    # 下载单个图片的异步函数（失败重试 3 次）
    async def async_download_image(self, url, save_path, filename):
        filename = filename.replace('/', '')
        target = os.path.join(save_path, filename)
        if os.path.exists(target):
            return
        # 完整浏览器请求头，避免 Cloudflare 等 bot 检测返回 403
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "sec-ch-ua": '"Google Chrome";v="120", "Chromium";v="120", "Not.A/Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Referer": self.referer or 'https://www.google.com/',
        }
        last_err = ''
        for attempt in range(3):
            try:
                # 直连优先(trust_env=False)，失败后走系统代理(trust_env=True)重试：
                # 兼顾直连可达站(如 mwappimgs.cc)与需代理站(如 s1.bzcdn.net)。
                # connect 阶段 5s 超时，让直连不通的站快速失败走代理，避免每张图等满 30s
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=True, trust_env=(attempt >= 1)) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        with open(target, 'wb') as file:
                            file.write(response.content)
                        return
                    last_err = f'status={response.status_code}'
            except Exception as e:
                # 带异常类型，避免 ConnectTimeout 等异常 str() 为空时 last_err 误导排查
                last_err = f'{type(e).__name__}: {e}'
            # 失败后退避重试
            await asyncio.sleep(1 + attempt)
        logging.info(f'图片下载失败(重试3次): {url} | {last_err}')

    async def download_chapter_images(self, image_urls, comic_name, chapter_name):
        logging.info(f'{comic_name}{chapter_name}图片开始下载')
        download_folder = cfg.get(cfg.downloadFolder)
        invalid_chars = r'[<>:"/\\|?*]'
        # 替换特殊字符为空字符
        chapter_name = re.sub(invalid_chars, '', chapter_name)
        path = f"{download_folder}/{comic_name}/{chapter_name}"
        os.makedirs(path, exist_ok=True)
        tasks = [
            self.async_download_image(deal_url(url), path,
                                      chapter_name.split('_')[0] + '_Cmbok_' + str(index) + get_file_extension(
                                          url))
            for
            index, url in
            enumerate(image_urls)]
        await asyncio.gather(*tasks)
        logging.info(f'{comic_name}{chapter_name}图片下载完成')
        self.success.emit(comic_name)

    # 下载章节图片


class EpubThread(QThread):
    success = pyqtSignal()

    def __init__(self, path, comic_name):
        super(EpubThread, self).__init__()
        self.path = path
        self.comic_name = comic_name

    def run(self):
        self.images_to_epub(self.path, self.comic_name)

    # 生成epub
    def images_to_epub(self, download_folder, comic_name):
        try:
            # 顶层目录（卷/章节）按自然排序，确保按章节顺序生成
            for entry in natsorted(os.listdir(download_folder)):
                path = os.path.join(download_folder, entry)
                if os.path.isdir(path):  # 检查是否为目录
                    chapter_name = entry
                    logging.info(f'{comic_name}{chapter_name}开始转换epub')
                    book = epub.EpubBook()
                    book.set_identifier(str(uuid.uuid1()).lower().replace('-', ''))
                    book.set_title(chapter_name)
                    book.set_language('en')
                    book.add_author('')
                    # 获取目录下的所有文件
                    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                    # 进行自然排序
                    sorted_files = natsorted(files)
                    # 漫画图片目录
                    for index, file_name in enumerate(sorted_files):
                        img_item = epub.EpubItem(uid=file_name, file_name=file_name,
                                                 media_type='image/jpeg')
                        with open(f'{path}/{file_name}', 'rb') as f:
                            img_item.set_content(f.read())
                            # if index == 0:
                            #     book.add_item(epub.EpubItem(uid="cover", file_name=file_name,
                            #                                 media_type='image/jpeg',
                            #                                 content=f.read()))
                        book.add_item(img_item)

                        chapter = epub.EpubHtml(title=f'Image {index}', file_name=f'chap_{index}.xhtml', lang='en')
                        chapter.set_content(f'<html><body><img src="{img_item.file_name}" /></body></html>')
                        book.add_item(chapter)
                        book.spine.append(chapter)
                    nav = epub.EpubNav()
                    book.add_item(nav)

                    # epub是否保存到漫画根目录
                    epubSaveFolder = cfg.get(cfg.epubSaveFolder)
                    if epubSaveFolder:
                        save_path = f"{download_folder}"
                    else:
                        save_path = f"{path}"
                    epub.write_epub(os.path.join(save_path, f'{comic_name}_{chapter_name}.epub'), book)

                    # 是否生成pdf
                    isSavePdf = cfg.get(cfg.isSavePdf)
                    if isSavePdf:
                        img_to_pdf(sorted_files, path, f'{save_path}/{comic_name}_{chapter_name}.pdf')

                    # 是否转换mobi
                    if cfg.get(cfg.isSaveMobi):
                        # 先生成pdf
                        if not isSavePdf:
                            img_to_pdf(sorted_files, path, f'{save_path}/{comic_name}_{chapter_name}.pdf')
                        # 转mobi，需要配置ebook-convert
                        calibrePath = cfg.get(cfg.calibrePath)
                        calibre_bin = 'ebook-convert.exe' if os.name == 'nt' else 'ebook-convert'
                        if calibrePath != '' and os.path.isfile(calibrePath) and os.path.basename(
                                calibrePath) == calibre_bin:
                            convert_epub_to_mobi(calibrePath, cfg.get(cfg.calibreOutputDevice),
                                                 f'{comic_name}_{chapter_name}',
                                                 f'{save_path}/{comic_name}_{chapter_name}.pdf',
                                                 f'{save_path}/{comic_name}_{chapter_name}.mobi')
                            # 转换完成删除pdf
                            if not isSavePdf:
                                del_file(f'{save_path}/{comic_name}_{chapter_name}.pdf')

                    # 合并epub之后，根据配置是否删除章节图片
                    if cfg.get(cfg.isDelChapterImages):
                        if epubSaveFolder:
                            del_folder(path)
                        else:
                            del_folder_images(path)
                    logging.info(f'{comic_name}{chapter_name}转换epub完成')
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('生成epub异常')
        finally:
            self.success.emit()
