# -*- coding: utf-8 -*-
"""图片恢复算法：对站点防盗链/打乱切片的图片按算法就地还原（覆盖原文件）。

算法按名称分发，当前内置：
- 腐漫（boylove.cc）：图片被纵向切成 13 条并倒序拼接，还原即再倒序拼回。
"""
import logging
import os
import traceback

from PIL import Image


def restore_image(path, algorithm):
    """按指定算法就地还原图片（覆盖原文件）。

    algorithm 为空或未知算法则不处理；还原异常时记日志并保留原图，不抛出。
    """
    if not algorithm:
        return
    try:
        if algorithm == '腐漫':
            _restore_fuman(path)
        else:
            logging.info(f'[图片恢复] 未知算法，跳过: {algorithm}')
    except Exception:
        # 还原失败不中断下载，保留原（打乱的）图
        logging.info('[图片恢复] 还原失败: ' + traceback.format_exc())


def _restore_fuman(path):
    """腐漫算法（boylove.cc）：图被纵向切成 13 条并倒序拼接，再倒序拼回即还原。

    超高图 h>=4000 站点未打乱，直接保留原图。
    先写临时文件再 os.replace，避免写坏原图。
    """
    img = Image.open(path)
    w, h = img.size
    fmt = img.format  # 保留原格式（WEBP/PNG/JPEG...），存临时文件时显式指定
    if h >= 4000:
        # 站点对超高图不重排，直接保留
        img.close()
        return
    n = 13
    sw = w // n
    if sw <= 0:
        img.close()
        return
    strips = []
    for i in range(n):
        left = i * sw
        right = w if i == n - 1 else (i + 1) * sw
        strips.append(img.crop((left, 0, right, h)))
    strips.reverse()  # 倒序拼回
    result = Image.new(img.mode, (w, h))
    x = 0
    for s in strips:
        result.paste(s, (x, 0))
        x += s.width
    tmp = path + '.restore_tmp'
    result.save(tmp, format=fmt)  # 显式指定格式，避免 PIL 从 .restore_tmp 扩展名推断失败
    img.close()
    os.replace(tmp, path)
