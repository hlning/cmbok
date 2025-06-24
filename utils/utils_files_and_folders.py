# coding:utf-8

import glob
import logging
import os
import re
import shutil


def move_files(base_path, directories, target_directory):
    """将目录中的文件移动到目标目录"""
    for directory in directories:
        src_path = os.path.join(base_path, directory)
        for file_name in os.listdir(src_path):
            file_path = os.path.join(src_path, file_name)
            if os.path.isfile(file_path):
                shutil.move(file_path, target_directory)
        # 删除原目录
        os.rmdir(src_path)


def del_file(file_path):
    if file_path is not None and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except PermissionError:
            logging.info(f"没有权限删除文件 {file_path}。")
        except Exception as e:
            logging.info(f"删除文件时发生错误：{e}")
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


def is_valid_filename(filename):
    # 检查文件名是否为空或仅包含空白字符
    if not filename or filename.isspace():
        return False

    # 检查文件名长度
    if len(filename) > 255:
        return False

    # 定义不允许出现的字符
    invalid_characters = r'[<>:"/\\|?*]'

    # 检测是否包含不允许的字符
    if re.search(invalid_characters, filename):
        return False

    return True
