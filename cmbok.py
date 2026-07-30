import logging
import multiprocessing
import os
import sys
import traceback

from PyQt5.QtCore import Qt, QTranslator
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from common.config import cfg
from common.sqlite_util import SQLiteDatabase
from view.main_window import Window

if __name__ == '__main__':
    # PyInstaller frozen 下 multiprocessing spawn 子进程会重新执行本脚本，
    # freeze_support 让子进程走自己的逻辑后退出，不再启动第二个 app 窗口
    multiprocessing.freeze_support()
    try:
        # enable dpi scale
        if cfg.get(cfg.dpiScale) == "Auto":
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        else:
            os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
            os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))

        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

        # 初始化数据库
        sqlite_util = SQLiteDatabase()
        sqlite_util.init()

        app = QApplication(sys.argv)
        # internationalization
        locale = cfg.get(cfg.language).value
        translator = FluentTranslator(locale)
        galleryTranslator = QTranslator()
        galleryTranslator.load(locale, "cmbok", ".", ":/cmbok/i18n")

        app.installTranslator(translator)
        app.installTranslator(galleryTranslator)

        w = Window()
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        logging.info("发生异常：", e)
        logging.info(traceback.format_exc())
