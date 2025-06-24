# coding:utf-8
import logging
import os
import subprocess
import traceback

from PIL import Image


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
