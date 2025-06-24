import json
import logging
import os
import urllib.parse
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from natsort import natsorted


# 获取当前时间字符串
def get_current_time(format_str='%Y-%m-%d %H:%M:%S'):
    # 获取当前时间
    now = datetime.now()
    # 将当前时间格式化为字符串
    return now.strftime(format_str)


# 超过多少字符添加省略号
def get_display_length(s):
    """计算字符串的可视长度"""
    length = 0
    for char in s:
        # 英文字符和数字占用1个宽度，中文字符占用2个宽度
        if char.isascii():  # 判断是否为英文或数字
            length += 1
        else:
            length += 2  # 中文字符
    return length


def truncate_string(s, length=10):
    # 如果字符串的可视长度小于等于所需长度，直接返回
    if get_display_length(s) <= length:
        return s

    truncated = ""
    current_length = 0

    for char in s:
        # 计算当前字符的可视长度
        char_length = 1 if char.isascii() else 2

        # 检查添加字符后的总可视长度是否超过限制
        if current_length + char_length > length:
            break

        # 添加字符并更新当前可视长度
        truncated += char
        current_length += char_length

    return truncated.rstrip() + '...'


def format_text(text, max_length=5, max_lines=2):
    """
    格式化字符串，使其最多显示 max_lines 行，每行最多包含 max_length 个字符。
    超过的部分用省略号替代，并在最后一行添加省略号。

    :param text: 待处理的字符串
    :param max_length: 每行最大字符数
    :param max_lines: 最大行数
    :return: 格式化后的字符串
    """
    # 如果文本长度小于或等于最大长度，直接返回
    if len(text) <= max_length:
        return text

    formatted_lines = []
    current_line = ""
    line_count = 0

    # 按字符遍历文本
    for char in text:
        current_line += char

        # 检查当前行的长度
        if len(current_line) == max_length:  # 到达最大长度
            formatted_lines.append(current_line)  # 添加当前行到结果列表
            current_line = ""  # 重置当前行
            line_count += 1  # 增加行计数

            # 如果达到最大行数，停止处理
            if line_count >= max_lines:
                break

    # 添加最后一行的剩余字符
    if current_line and line_count < max_lines:
        formatted_lines.append(current_line)
        line_count += 1

    # 在最后一行添加省略号
    if line_count >= max_lines and len(text) > max_length * max_lines:
        formatted_lines[-1] = formatted_lines[-1].rstrip() + "..."  # 在最后一行添加省略号

    return "\n".join(formatted_lines)


# 根据图书信息更新封面文件名
def get_book_cover(obj):
    cover = obj['cover']
    name = obj['title']
    id = obj['id']
    suffix = os.path.splitext(cover)[1]
    return name + '_' + id + suffix


# 根据漫画信息更新封面文件名
def get_comic_cover(obj):
    cover = obj['cover']
    name = obj['name']
    author = obj['author'][0]['name']
    suffix = os.path.splitext(cover)[1]
    return name + '_' + author + suffix


def aes_cbc_decrypt(ciphertext, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return decrypted.decode('utf-8')


def string_to_hex(input_string):
    return bytes.fromhex(input_string)


def analyze_data(enc_data):
    ciphertext = string_to_hex(enc_data[16:])
    iv = enc_data[:16].encode('utf-8')
    key = b"xxxmanga.woo.key"
    return json.loads(aes_cbc_decrypt(ciphertext, key, iv))


def check_url(url):
    try:
        # 发送 HEAD 请求
        response = requests.head(url, allow_redirects=True, timeout=1)
        # 检查状态码
        if response.status_code == 200:
            logging.info(f"URL有效")
            return True
        else:
            logging.info(f"URL无效，状态码：{response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logging.info(f"URL无效，错误信息：{e}")
        return False


def get_file_extension(url):
    # 使用 urllib.parse 的 urlparse 解析 URL
    parsed_url = urllib.parse.urlparse(url)

    # 提取路径部分
    path = parsed_url.path

    # 使用 os.path.splitext 获取文件名和扩展名
    _, file_extension = os.path.splitext(path)

    # 返回扩展名，去掉前面的点（.）
    return file_extension if file_extension != '' else '.jpeg'


def deal_url(url):
    if '?' in url:
        base_url, query_string = url.split('?', 1)  # 将网址分为基本部分和查询部分
        # 替换查询字符串中的斜杠
        modified_query_string = query_string.replace('/', '%2F')
        # 组合回新的网址
        modified_url = f"{base_url}?{modified_query_string}"
    else:
        modified_url = url  # 如果没有问号，则不做任何更改

    return modified_url


def get_directories(path):
    """获取指定路径下的所有目录，并按自然排序"""
    return natsorted([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])
