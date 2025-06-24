# coding:utf-8
from enum import Enum

from PyQt5.QtCore import QLocale
from qfluentwidgets import (qconfig, QConfig, ConfigItem, OptionsConfigItem, BoolValidator,
                            OptionsValidator, RangeConfigItem, RangeValidator,
                            Theme, FolderValidator, ConfigSerializer, FileValidator)


class Language(Enum):
    """ Language enumeration """

    CHINESE_SIMPLIFIED = QLocale(QLocale.Chinese, QLocale.China)
    CHINESE_TRADITIONAL = QLocale(QLocale.Chinese, QLocale.HongKong)
    ENGLISH = QLocale(QLocale.English)
    AUTO = QLocale()


class LanguageSerializer(ConfigSerializer):
    """ Language serializer """

    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


class Config(QConfig):
    """ Config of application """
    # 使用本地服务
    useLocalServer = ConfigItem("Local", "UseLocalServer", False, BoolValidator())

    # 下载最大线程
    downloadThreadNum = RangeConfigItem("Thread", "DownloadThreadNum", 2, RangeValidator(1, 5))

    # 下载目录
    downloadFolder = ConfigItem(
        "Folders", "DownloadFolder", "app/download", FolderValidator())

<<<<<<< HEAD
    # 工具箱文件保存目录
    toolSaveFolder = ConfigItem(
        "Folders", "ToolSaveFolder", "app/download/convert", FolderValidator())

    # 窗口宽度
    windowWidth = RangeConfigItem("Width", "WindowWidth", 965, RangeValidator(900, 1080))

    # 窗口高度
    windowHeight = RangeConfigItem("Height", "WindowHeight", 750, RangeValidator(450, 950))

    # komga是否随cmbok启动运行
    isRunKomga = ConfigItem("Komga", "IsRunKomga", True, BoolValidator())

    komgaFolder = ConfigItem(
        "Komga", "komgaFolder", "komga", FolderValidator())

    # komga是否保留后台
    komgaBackgrounder = ConfigItem("Komga", "KomgaBackgrounder", False, BoolValidator())
=======
    # 窗口高度
    windowHeight = RangeConfigItem("Height", "WindowHeight", 550, RangeValidator(450, 900))
>>>>>>> origin/main

    # epub是否保存到漫画根目录
    epubSaveFolder = ConfigItem("Folders", "EpubSaveFolder", True, BoolValidator())

    # 是否删除章节图片
    isDelChapterImages = ConfigItem("Chapter", "IsDelChapterImages", True, BoolValidator())

    # 是否合并保存PDF
    isSavePdf = ConfigItem("Comic", "IsSavePdf", False, BoolValidator())

    # 是否转换成Mobi
    isSaveMobi = ConfigItem("Comic", "ISaveMobi", False, BoolValidator())

    # ebook-convert.exe路径
    calibrePath = ConfigItem("Comic", "CalibrePath", "", FileValidator())

    # 转换Mobi页面设置
    calibreOutputDevice = OptionsConfigItem("Comic", "CalibreOutputDevice", 'default', OptionsValidator(
        ['default', 'kindle', 'kindle_dx', 'kindle_fire', 'kindle_oasis', 'kindle_pw', 'kindle_pw3',
         'kindle_scribe', 'kindle_voyage', 'ipad', 'ipad3', 'cybookg3', 'cybook_opus', 'hanlinv3', 'hanlinv5', 'illiad',
         'irexdr1000', 'irexdr800', 'jetbook5', 'kobo', 'msreader', 'mobipocket', 'nook', 'nook_color', 'nook_hd_plus',
         'pocketbook_inkpad3', 'pocketbook_lux', 'pocketbook_hd', 'pocketbook_900', 'pocketbook_pro_912', 'galaxy',
         'sony', 'sony300', 'sony900', 'sony-landscape', 'sonyt3', 'tablet', 'generic_eink_large', 'generic_eink',
         'generic_eink_hd']))

    # 是否合并成卷
    isMergeChapte = ConfigItem("Website", "IsMergeChapte", False, BoolValidator())
    # 站点多少话合并成一个章节
    mergeChapterNum = RangeConfigItem("Website", "mergeChapterNum", 1, RangeValidator(1, 20))

    # main window
    dpiScale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto", OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]), restart=True)
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO, OptionsValidator(Language), LanguageSerializer(), restart=True)

    # software update
    checkUpdateAtStartUp = ConfigItem("Update", "CheckUpdateAtStartUp", True, BoolValidator())

<<<<<<< HEAD
    version = ConfigItem("Update", "Version", 'V1.0.5')
=======
    version = ConfigItem("Update", "Version", 'V1.0.3')

>>>>>>> origin/main

VERSION_NO = 'V1.0.5'
YEAR = 2025
AUTHOR = "甜甜的王甜甜"
HELP_URL = "https://support.qq.com/products/656074"
GITHUBURL = "https://github.com/hlning/cmbok"
QQ_URL = "http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=5FjE0PlWCd4oestQLV2mrFuJRq8Ti-o5&authKey=X2t8fw62TNezzfFlvOtvBUbuffHRXuSOQzXOk4xHxtbEPO8Yciwn6pBFXoFXFztK&noverify=0&group_code=927528211"
LOG_PATH = 'app/app.log'

cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load('app/config/config.json', cfg)
