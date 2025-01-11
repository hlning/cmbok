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

    # main window
    dpiScale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto", OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]), restart=True)
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO, OptionsValidator(Language), LanguageSerializer(), restart=True)

    # software update
    checkUpdateAtStartUp = ConfigItem("Update", "CheckUpdateAtStartUp", True, BoolValidator())


YEAR = 2025
AUTHOR = "甜甜的王甜甜"
VERSION = '1.0.0'
HELP_URL = "https://support.qq.com/products/656074"
GITHUBURL = "https://github.com/hlning/cmbok"
QQ_URL = "http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=5FjE0PlWCd4oestQLV2mrFuJRq8Ti-o5&authKey=X2t8fw62TNezzfFlvOtvBUbuffHRXuSOQzXOk4xHxtbEPO8Yciwn6pBFXoFXFztK&noverify=0&group_code=927528211"
LOG_PATH = 'app/app.log'

cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load('app/config/config.json', cfg)
