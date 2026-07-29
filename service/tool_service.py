import logging
import multiprocessing
import os
import shutil
import time
import traceback
from pathlib import Path
from uuid import uuid4

import pypandoc
from PyQt5.QtCore import QThread, pyqtSignal
from pdf2docx import Converter
from pymupdf import pymupdf
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from common.config import cfg
from utils.utils_files_and_folders import del_file


def _pdf_to_doc_proc(pdf_path, docx_path, ignore_header_footer):
    """在独立进程中执行 pdf->docx，避免 pdf2docx 持有 GIL 卡住主线程 UI。"""
    from pdf2docx import Converter
    convert_settings = {
        "ignore_footer": ignore_header_footer,
        "ignore_header": ignore_header_footer,
    }
    cv = Converter(pdf_path)
    cv.convert(docx_path, **convert_settings)
    cv.close()


# 转换工具
class ConvertTool(QThread):
    process = pyqtSignal()
    finished = pyqtSignal(object, object)

    def __init__(self, files, type, merge_file_name):
        super(ConvertTool, self).__init__()
        self.files = files
        self.type = type
        self.merge_file_name = merge_file_name

    def run(self):
        self.process.emit()
        # 加点延时，让提示正在转换先显示
        time.sleep(0.5)

        # 转pdf
        if self.type == 1:
            self.convert_to_pdf()
        # 合并pdf
        elif self.type == 2:
            self.merge_to_pdf()
        # 转epub
        elif self.type == 3:
            self.convert_to_epub()
        # 转doc
        elif self.type == 4:
            self.convert_to_doc()
        # 合并epub
        elif self.type == 5:
            self.merge_to_epub()

    # 转pdf
    def convert_to_pdf(self):
        error_files = []
        for file_path in self.files:
            try:
                # 保存到download目录convert下
                file_name = Path(file_path).stem
                save_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{file_name}.pdf')
                # 转pdf
                self.to_pdf(file_path, save_path)
            except Exception as e:
                error_files.append(file_path)
                logging.info(f"{file_path}转换失败: {traceback.format_exc()}")
        self.finished.emit('finished', error_files)

    # 合并成pdf
    def merge_to_pdf(self):
        error_files = []
        try:
            # 先创建一个空pdf（临时文件名加 uuid，避免并发/重入冲突）
            tmp_pdf_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'temp_{uuid4().hex}.pdf')
            tmp_pdf = self.create_tmp_pdf(tmp_pdf_path)
            doc_a = pymupdf.open(tmp_pdf)
            for file_path in self.files:
                doc_b = None
                try:
                    base_name, extension = os.path.splitext(file_path)
                    doc_b = pymupdf.open(file_path)
                    # 将需要转换的文件，插入到pdf中
                    if extension == '.pdf':
                        doc_a.insert_pdf(doc_b)
                    else:
                        doc_a.insert_file(doc_b)
                except Exception as e:
                    error_files.append(file_path)
                    logging.info(f"{file_path}合并失败: {e}")
                finally:
                    if doc_b is not None:
                        doc_b.close()
            # 删除第一页
            doc_a.delete_page(0)
            # 保存合并后的pdf
            save_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{self.merge_file_name}.pdf')
            doc_a.save(save_path)
            doc_a.close()
            # 删除空pdf
            del_file(tmp_pdf)
            self.finished.emit('finished', error_files)
        except Exception as e:
            logging.info(f"合并失败: {traceback.format_exc()}")
            self.finished.emit('error', error_files)

    # 合并成epub
    def merge_to_epub(self):
        error_files = []
        tmp_dir = None
        try:
            import tempfile
            save_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{self.merge_file_name}.epub')
            # pandoc 直接合并多文件（尤其含 epub）时会触发 "Couldn't extract ePub file" 失败，
            # 且混合格式无法统一推断输入格式。改为：先把每个输入转成 docx 中间文件，再合并 docx 输出 epub；
            # 单个文件转换失败只跳过该文件，不影响其余合并。
            tmp_dir = tempfile.mkdtemp(prefix='merge_epub_')
            docx_files = []
            for file_path in self.files:
                try:
                    stem = Path(file_path).stem
                    tmp_docx = os.path.join(tmp_dir, f'{stem}_{uuid4().hex}.docx')
                    pypandoc.convert_file(file_path, 'docx', outputfile=tmp_docx)
                    if os.path.exists(tmp_docx):
                        docx_files.append(tmp_docx)
                    else:
                        error_files.append(file_path)
                except Exception:
                    error_files.append(file_path)
                    logging.info(f"{file_path}合并epub预处理失败: {traceback.format_exc()}")
            if not docx_files:
                raise RuntimeError('没有可合并的有效文件')
            pypandoc.convert_file(docx_files, 'epub', outputfile=save_path)
            self.finished.emit('finished', error_files)
        except Exception as e:
            logging.info(f"合并epub失败: {traceback.format_exc()}")
            self.finished.emit('error', error_files)
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # 转epub
    def convert_to_epub(self):
        error_files = []
        for file_path in self.files:
            pdf_path = None
            is_temp_pdf = False
            try:
                base_name, extension = os.path.splitext(file_path)

                # 保存到download目录convert下
                file_name = Path(file_path).stem
                pdf_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{file_name}.pdf')
                if extension != '.pdf':
                    # 先转成pdf
                    self.to_pdf(file_path, pdf_path)
                    is_temp_pdf = True
                else:
                    # 源已是 pdf，直接复用源文件，避免 copy/del 误删源文件
                    pdf_path = file_path

                epub_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{file_name}.epub')
                # 转epub
                self.pdf_to_epub(pdf_path, epub_path)
            except Exception as e:
                error_files.append(file_path)
                logging.info(f"{file_path}转换失败: {traceback.format_exc()}")
            finally:
                # 仅删除中间产物 pdf，源文件不删
                if is_temp_pdf and pdf_path:
                    del_file(pdf_path)
        self.finished.emit('finished', error_files)

    # 转doc
    def convert_to_doc(self):
        error_files = []
        for file_path in self.files:
            pdf_path = None
            is_temp_pdf = False
            try:
                base_name, extension = os.path.splitext(file_path)
                # 保存到download目录convert下
                file_name = Path(file_path).stem
                # 输出 docx 路径始终在输出目录（源为 pdf 时不能由源路径推导，否则会写到源目录）
                docx_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{file_name}.docx')
                if extension != '.pdf':
                    # 先转成pdf（中间产物）
                    pdf_path = os.path.join(cfg.get(cfg.toolSaveFolder), f'{file_name}.pdf')
                    self.to_pdf(file_path, pdf_path)
                    is_temp_pdf = True
                else:
                    # 源已是 pdf，直接复用源文件，避免 copy/del 误删源文件
                    pdf_path = file_path

                # 转doc
                self.pdf_to_doc(pdf_path, docx_path)
            except Exception as e:
                error_files.append(file_path)
                logging.info(f"{file_path}转换失败: {traceback.format_exc()}")
            finally:
                # 仅删除中间产物 pdf，源文件不删
                if is_temp_pdf and pdf_path:
                    del_file(pdf_path)
        self.finished.emit('finished', error_files)

    # 转pdf方法
    def to_pdf(self, file_path, save_path):
        tmp_pdf = None
        doc_a = None
        doc_b = None
        try:
            # 先创建一个空pdf
            tmp_pdf = self.create_tmp_pdf(save_path)
            # 将需要转换的文件，插入到pdf中
            doc_a = pymupdf.open(tmp_pdf)
            doc_b = pymupdf.open(file_path)
            doc_a.insert_file(doc_b)
            # 删除第一页
            doc_a.delete_page(0)
            # 保存合并后的pdf
            doc_a.save(save_path)
        except Exception as e:
            logging.info(f"{file_path}转pdf失败: {traceback.format_exc()}")
            raise e
        finally:
            if doc_a is not None:
                doc_a.close()
            if doc_b is not None:
                doc_b.close()
            # 删除空pdf
            del_file(tmp_pdf)

    # pdf转pub
    def pdf_to_epub(self, pdf_path, epub_path, ignore_header_footer=True):
        docx_path = None
        try:
            # 先把pdf转成docx
            docx_path = pdf_path.replace('.pdf', '.docx')
            self.pdf_to_doc(pdf_path, docx_path)

            # 使用pandoc把docx转epub
            pypandoc.convert_file(docx_path, 'epub', outputfile=epub_path)
        except Exception as e:
            logging.info(f"{pdf_path}转epub失败: {traceback.format_exc()}")
            raise e
        finally:
            # 删除docx
            del_file(docx_path)

    # pdf转doc
    def pdf_to_doc(self, pdf_path, docx_path, ignore_header_footer=True):
        # 在独立进程执行，避免 pdf2docx 持有 GIL 导致主线程 UI 卡死
        p = multiprocessing.Process(target=_pdf_to_doc_proc,
                                    args=(pdf_path, docx_path, ignore_header_footer))
        p.start()
        p.join()
        if p.exitcode != 0:
            raise RuntimeError(f'pdf转doc失败，进程退出码 {p.exitcode}')

    # 创建一个空pdf
    def create_tmp_pdf(self, file_path):
        # 获取文件夹路径
        folder_path = os.path.dirname(file_path)
        # 获取文件名称 (不带扩展名)
        file_name, file_extension = os.path.splitext(os.path.basename(file_path))

        # 创建新的文件名，添加 '_tmp'
        new_file_name = f"{file_name}_tmp.pdf"

        # 构建新的文件路径
        new_file_path = os.path.join(folder_path, new_file_name)

        c = canvas.Canvas(new_file_path, pagesize=letter)
        c.showPage()  # 创建一个空白页面
        c.save()  # 保存 PDF 文件

        return new_file_path
