import glob
import json
import logging
import os
import shutil
import subprocess
import traceback
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from PIL import Image


# 获取当前时间字符串
def get_current_time():
    # 获取当前时间
    now = datetime.now()
    # 将当前时间格式化为字符串
    return now.strftime("%Y-%m-%d %H:%M:%S")


# 超过多少字符添加省略号
def truncate_string(s, length=10):
    if len(s) > length:
        return s[:length].rstrip() + '...'
    return s


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


def del_folder_images(directory):
    # 定义图片文件的扩展名
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.bmp']
    # 遍历所有指定格式的图片文件
    for ext in image_extensions:
        # 使用 glob.glob() 查找匹配的文件
        files = glob.glob(os.path.join(directory, ext))
        for file in files:
            try:
                os.remove(file)  # 删除文件
            except Exception as e:
                logging.info(f"删除文件失败: {e}")


def del_file(file_path):
    if os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except PermissionError:
            logging.info(f"没有权限删除文件 {file_path}。")
        except Exception as e:
            logging.info(f"删除文件时发生错误：{e}")
    else:
        logging.info(f"文件 {file_path} 不存在。")


def clean_file(file_path):
    if os.path.isfile(file_path):
        try:
            # 清空文件内容
            with open(file_path, 'w') as file:
                pass  # 什么都不做，直接打开并关闭文件
        except Exception as e:
            logging.info(f"清空文件时发生错误：{e}")
    else:
        logging.info(f"文件 {file_path} 不存在。")


def del_folder(directory):
    # 检查目录是否存在
    if os.path.exists(directory):
        try:
            # 遍历目录中的所有文件和子目录
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):  # 如果是文件
                    os.remove(file_path)  # 删除文件
                elif os.path.isdir(file_path):  # 如果是子目录
                    shutil.rmtree(file_path)  # 删除子目录及其内容
            # 删除空目录
            os.rmdir(directory)
        except Exception as e:
            logging.info(f"处理过程中发生错误: {e}")
    else:
        logging.info(f"目录不存在: {directory}")


def img_to_pdf(image_files, folder_path, output_pdf_path):
    # 创建一个空列表来存放图像对象
    images = []
    # 打开每张图片，并将其添加到列表中
    for image_file in image_files:
        image_path = os.path.join(folder_path, image_file)
        logging.info(image_path)
        img = Image.open(image_path)
        # 将图像转换为 RGB 模式（PDF 需要 RGB 模式）
        img = img.convert('RGB')
        images.append(img)

    # 保存为 PDF 文件
    if images:
        images[0].save(output_pdf_path, save_all=True, append_images=images[1:])
        logging.info(f"成功将图片合并为 PDF: {output_pdf_path}")
    else:
        logging.info("没有找到 JPG 图片。")


def convert_epub_to_mobi(calibrePath, calibreOutputDevice, title, epub_file, mobi_file):
    try:
        # 检查文件是否存在
        if not os.path.isfile(epub_file):
            logging.info(f"文件 {epub_file} 不存在！")
            return

        # 调用 calibre 的 ebook-convert 命令
        subprocess.run([f'{calibrePath}', epub_file, mobi_file,
                        '--output-profile', f'{calibreOutputDevice}',
                        '--title', f'{title}'
                        ], check=True)
        logging.info(f"转换成功！MOBI 文件已保存为 {mobi_file}")
    except subprocess.CalledProcessError as e:
        logging.info(f"转换过程中发生错误: {e}")
    except Exception as e:
        logging.info(traceback.format_exc())
        logging.info(f"发生异常: {e}")


def check_url(url):
    try:
        # 发送 HEAD 请求
        response = requests.head(url, allow_redirects=True, timeout=5)
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


def delete_files_with_character(directory, character):
    # 遍历目录中的所有文件
    for root, dirs, files in os.walk(directory):
        for filename in files:
            # 检查文件名中是否包含指定字符
            if character in filename:
                file_path = os.path.join(root, filename)
                try:
                    os.remove(file_path)  # 删除文件
                    print(f'已删除文件: {file_path}')
                except Exception as e:
                    print(f'无法删除文件 {file_path}: {e}')
