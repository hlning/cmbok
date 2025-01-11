import asyncio
import datetime
import logging
import os
import queue
import time
import traceback

import aiohttp
import requests
from PyQt5.QtCore import QThread, QMutex, pyqtSignal
from bs4 import BeautifulSoup
from ebooklib import epub
from natsort import natsorted

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from common.util import get_current_time, analyze_data, del_folder_images, del_folder, img_to_pdf, \
    convert_epub_to_mobi, del_file, delete_files_with_character
from view.download_interface import book_process_signals, download_signals, comic_process_signals

comic_search_lock = QMutex()
book_search_lock = QMutex()
download_comic_lock = QMutex()

URL = 'https://www.mangacopy.com/'
WEBSITE = 'https://www.copymanga.com/'
SEARCH_WEBSITE = 'https://api.mangacopy.com/'
CMBOK_WEBSITE = 'https://bluemood.xiaomy.net/'
API_HEADER = {
    'User-Agent': 'duoTuoCartoon/3.2.4 (iPhone; iOS 18.0.1; Scale/3.00) iDOKit/1.0.0 RSSX/1.0.0',
    'version': datetime.datetime.now().strftime("%Y.%m.%d"),
    'region': '0',
    'webp': '0',
    "platform": "1",
    "referer": WEBSITE
}


# 搜索图书
class BookSearch(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, book_name, index=0):
        super(BookSearch, self).__init__()
        self.book_name = book_name
        self.index = index

    def run(self):
        book_search_lock.lock()
        try:
            url = f'{CMBOK_WEBSITE}cmbok/zlibrary/search/{self.book_name}/{self.index}'
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            if response.status_code == 200:
                results = response.json()
                if results is None:
                    self.success.emit('fail', None)
                else:
                    if results['success'] == 1:
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
            logging.info('查询图书失败')
        finally:
            book_search_lock.unlock()


# 下载图书
# 全局图书当前下载数量
book_active_downloads = 0
# 下载队列
book_waiting_queue = queue.Queue()


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

    async def download_chunk(self, session, url, start, end, chunk_id, sem, history_id, process):
        async with sem:
            for attempt in range(99):
                sqlite_util = SQLiteDatabase()
                try:
                    headers = {'Range': f'bytes={start}-{end}'}
                    async with session.get(url, headers=headers,
                                           timeout=aiohttp.ClientTimeout(sock_read=30)) as response:
                        response.raise_for_status()
                        if response.status == 206:  # 206 Partial Content
                            content = await response.read()
                            file_path = os.path.join('app/chunks',
                                                     f'{self.book_id}_{self.book_hash}_{chunk_id}.part')
                            with open(file_path, 'wb') as f:
                                f.write(content)
                            # 更新进度
                            self.process += process
                            sqlite_util.update_data('cmbok_download_history',
                                                    {'process': self.process},
                                                    {'id': history_id})
                            book_process_signals.success.emit(history_id, self.process)
                            break
                except Exception as e:
                    sqlite_util.rollback()
                    logging.info(f'Chunk {chunk_id} error: {start}-{end}')
                    logging.info(traceback.format_exc())
                    logging.info(f'下载过程中出现错误: {e}')
                    if attempt < 99 - 1:
                        logging.info(f"正在重试... (尝试次数: {attempt + 1})")
                        time.sleep(1)  # 等待重试
                    else:
                        logging.info("达到最大重试次数，下载失败。")
                        raise e
                finally:
                    sqlite_util.close()

    async def download_file(self, url, total_parts, history_id, max_concurrent_chunks=5):
        sem = asyncio.Semaphore(max_concurrent_chunks)
        async with aiohttp.ClientSession() as session:
            tasks = []
            process = int(100 / len(total_parts))
            for start, end, index in total_parts:
                tasks.append(self.download_chunk(session, url, start, end, index, sem, history_id, process))
            await asyncio.gather(*tasks)

            # 合并文件
            output_file = os.path.join(cfg.get(cfg.downloadFolder),
                                       f'{self.book_name}_{self.book_id}.{self.book_extension}')
            self.merge_files(total_parts, output_file)
            self.download_success(history_id)

    def merge_files(self, total_parts, output_file):
        with open(output_file, 'wb') as merged_file:
            for start, end, index in total_parts:
                part_filename = os.path.join('app/chunks',
                                             f'{self.book_id}_{self.book_hash}_{index}.part')
                with open(part_filename, 'rb') as part_file:
                    merged_file.write(part_file.read())
            logging.info(f'merged {output_file} finish!!!')

        for start, end, index in total_parts:
            part_filename = os.path.join('app/chunks',
                                         f'{self.book_id}_{self.book_hash}_{index}.part')
            os.remove(part_filename)

    def download_success(self, history_id):
        global book_active_downloads
        with SQLiteDatabase() as db:
            # 下载完成
            book_active_downloads -= 1
            db.update_data('cmbok_download_history',
                           {'status': 3, 'process': 100, 'finish_time': get_current_time()},
                           {'id': history_id})
            download_signals.success.emit('success', self.book_name, self.book_author, 2)

    def download_fail(self, history_id):
        global book_active_downloads
        with SQLiteDatabase() as db:
            # 下载失败
            book_active_downloads -= 1
            db.update_data('cmbok_download_history',
                           {'status': 0, 'finish_time': get_current_time()},
                           {'id': history_id})
            download_signals.success.emit('error', self.book_name, self.book_author, 2)

    def run(self):
        global book_active_downloads
        sqlite_util = SQLiteDatabase()
        history_id = 0

        try:
            self.success.emit('success')
            # 先保存保存下载记录
            history_id = sqlite_util.insert_data('cmbok_download_history', {'cover': '',
                                                                            'name': self.book_name,
                                                                            'author': self.book_author,
                                                                            'key': self.book_id,
                                                                            'book_hash': self.book_hash,
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

                url = f'{CMBOK_WEBSITE}cmbok/zlibrary/download/{self.book_id}/{self.book_hash}/{self.book_extension}'
                response = requests.get(url)
                response.raise_for_status()
                if response.status_code == 200:
                    results = response.json()
                    download_status = results['download_status']
                    if download_status:
                        file_name = f'{self.book_id}_{self.book_hash}.{self.book_extension}'
                        # 先获取文件大小
                        head = requests.head(f'{CMBOK_WEBSITE}static/files/{file_name}')

                        if head.status_code == 200:
                            file_size = int(head.headers.get('Content-Length'))
                            chunk_size = 1024 * 512  # 每个块0.5MB
                            # 计算块的数量
                            chunks = [(i, min(i + chunk_size - 1, file_size - 1), index)
                                      for index, i in enumerate(range(0, file_size, chunk_size))]
                            # 下载每个块
                            url = f'{CMBOK_WEBSITE}cmbok/zlibrary/download_file/{self.book_id}/{self.book_hash}/{self.book_extension}'

                            os.makedirs('app/chunks', exist_ok=True)

                            asyncio.run(self.download_file(url, chunks, history_id, max_concurrent_chunks=10))
                        else:
                            self.download_fail(history_id)
                    else:
                        self.download_fail(history_id)

                    # 继续下一个等待的下载任务（如果有的话）
                    if not book_waiting_queue.empty():
                        next_book = book_waiting_queue.get()
                        bookDownload = BookDownload(book=next_book)
                        bookDownload.start()
            else:
                book_waiting_queue.put(self.book)
        except Exception:
            sqlite_util.rollback()
            delete_files_with_character('app/chunks', f'{self.book_id}_{self.book_hash}')
            self.download_fail(history_id)
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
            url = f"{SEARCH_WEBSITE}api/v3/search/comic?format=json&platform=3&q={self.comic_name}&limit=27&offset={self.offset * 27}"
            response = requests.get(url, headers=API_HEADER, proxies=self.PROXIES, timeout=15)
            if response.status_code == 200:
                data = response.json()
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


# 获取漫画目录信息
class ComicChapters(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, path_word):
        super(ComicChapters, self).__init__()
        self.path_word = path_word

    def run(self):
        comic_search_lock.lock()
        try:
            response = requests.get(f"{URL}comicdetail/{self.path_word}/chapters", timeout=30)
            if response.status_code == 200:
                data = response.json()
                results = analyze_data(str(data['results']))
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
            logging.info('获取漫画目录信息失败')
        finally:
            comic_search_lock.unlock()


# 查询收藏记录
class ComicCollects(QThread):
    success = pyqtSignal(object, object)

    def __init__(self, index, text, type):
        super(ComicCollects, self).__init__()
        self.index = index
        self.text = text
        self.type = type

    def run(self):
        sqlite_util = SQLiteDatabase()
        try:
            # 查询收藏记录
            comics = sqlite_util.query_data('cmbok_collection_record',
                                            conditions={'name': f'%{self.text}%', 'type': self.type},
                                            order_by='collection_time DESC', limit=16,
                                            offset=self.index * 16)

            self.success.emit('success', comics)
        except Exception as e:
            self.success.emit('error', None)
            logging.info(traceback.format_exc())
            logging.info('获取漫画目录信息失败')
        finally:
            sqlite_util.close()


# 获取漫画目录下所有图片
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
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(sock_read=20)) as session:
                    async with session.get(url) as response:
                        response.raise_for_status()  # 抛出HTTP错误
                        if response.status == 200:
                            image_data = await response.read()
                            with open(os.path.join(save_path, filename), 'wb') as f:
                                f.write(image_data)
                            # 更新进度
                            shared_data['process'] += process
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
                                                                                    'chapter_path_word': chapter['id'],
                                                                                    'status': 2,
                                                                                    'process': 0,
                                                                                    'type': 1,
                                                                                    'start_time': ''})
                    id_map[comic_path_word + chapter['id']] = history_id

                for chapter in chapters:
                    chapter_images = self.get_chapter_images(comic_path_word, chapter['id'])

                    if chapter_images is not None:
                        shared_data = {'process': 0}
                        # 每次同时下载指定数量的章节
                        task = asyncio.create_task(
                            self.start_download_chapter_images(id_map[comic_path_word + chapter['id']], chapter_images,
                                                               comic_path_word, comic_name,
                                                               comic_author,
                                                               chapter['name'], shared_data))
                        chapter_tasks.append(task)
                        # 下载记录更新状态
                        sqlite_util.update_data('cmbok_download_history',
                                                {'status': 1, 'start_time': get_current_time()},
                                                {'id': id_map[comic_path_word + chapter['id']]})
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
                                                {'id': id_map[comic_path_word + chapter['id']]})
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
        path = f"{download_folder}/{comic_name}/{chapter_name}"
        os.makedirs(path, exist_ok=True)
        process = int(100 / len(image_urls))
        tasks = [
            self.async_download_image(url, path, 'Cmbok_' + str(index) + os.path.splitext(url)[1], history_id,
                                      shared_data, process)
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
                    if index == 0:
                        book.add_item(epub.EpubItem(uid="cover", file_name=file_name,
                                                    media_type='image/jpeg',
                                                    content=f.read()))
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
                if calibrePath != '' and os.path.isfile(calibrePath) and os.path.basename(
                        calibrePath) == 'ebook-convert.exe':
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

    def get_chapter_images(self, book_name, chapter_id):
        try:
            response = requests.get(f"{URL}/comic/{book_name}/chapter/{chapter_id}").content
            data = analyze_data(
                BeautifulSoup(response, 'html.parser').find(name="div", attrs={"class": "imageData"}).attrs[
                    'contentkey'])
            return [i['url'] for i in data]
        except Exception as e:
            logging.info('获取图片失败')
