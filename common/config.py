# coding:utf-8
from datetime import date
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

    # 工具箱文件保存目录
    toolSaveFolder = ConfigItem(
        "Folders", "ToolSaveFolder", "app/download/convert", FolderValidator())

    # 去白边预设（JSON 数组：[{name, threshold, padding, width, height}]）
    trim_presets = ConfigItem("Tool", "TrimPresets", '[]')

    # 窗口宽度
    windowWidth = RangeConfigItem("Width", "WindowWidth", 1225, RangeValidator(950, 1920))

    # 窗口高度
    windowHeight = RangeConfigItem("Height", "WindowHeight", 900, RangeValidator(450, 1080))

    # komga是否随cmbok启动运行
    isRunKomga = ConfigItem("Komga", "IsRunKomga", True, BoolValidator())

    komgaFolder = ConfigItem(
        "Komga", "komgaFolder", "komga", FolderValidator())

    # komga是否保留后台
    komgaBackgrounder = ConfigItem("Komga", "KomgaBackgrounder", False, BoolValidator())

    # Komga 自定义地址（配置后不启动内置 Komga，点击菜单直接打开该地址；留空使用内置 127.0.0.1:25600）
    customKomgaUrl = ConfigItem("Komga", "CustomKomgaUrl", '')

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

    # 个性化：毛玻璃效果（Mica，默认开启；仅 Windows 11 生效）
    micaEnabled = ConfigItem("Personalization", "MicaEnabled", True, BoolValidator())

    # 个性化：导航默认展开（默认开启）
    navigationExpanded = ConfigItem("Personalization", "NavigationExpanded", True, BoolValidator())

    # software update
    checkUpdateAtStartUp = ConfigItem("Update", "CheckUpdateAtStartUp", True, BoolValidator())

    version = ConfigItem("Update", "Version", 'V2.0.2')

    year = ConfigItem("Update", "Year", date.today().year)

    # 公告：上次用户主动关闭的公告标识（md5），相同内容下次启动不再弹出
    lastNotificationId = ConfigItem("Notification", "LastNotificationId", '')

    # 拷贝漫画地址
    copy_url = ConfigItem("CopyVersion", "CopyUrl", 'https://api.copy3000.com/')

    zlibrary_url = ConfigItem("ZlibraryVersion", "ZlibraryUrl", 'zh.zlibrary.by')
    # z-library 候选节点列表（JSON 字符串数组，按延迟升序；启动探测选优后写入，运行时连接失败自动切换）
    zlibrary_url_candidates = ConfigItem("ZlibraryVersion", "ZlibraryUrlCandidates", '[]')

    # 拷贝漫画 authorization token（可选，留空则匿名访问；参考 Breeze 插件 auth.token）
    copy_token = ConfigItem("CopyVersion", "CopyToken", '')

    # 拷贝漫画代理（可选，梯子本地端口如 http://127.0.0.1:7890；留空=直连，适合 TUN 模式全局路由）
    copy_proxy = ConfigItem("CopyVersion", "CopyProxy", '')

    # z-library 账号登录态（登录成功后保存 token，下次免登录；不存密码）
    zlibrary_email = ConfigItem("Zlibrary", "Email", '')
    zlibrary_username = ConfigItem("Zlibrary", "Username", '')
    zlibrary_remix_userid = ConfigItem("Zlibrary", "RemixUserid", '')
    zlibrary_remix_userkey = ConfigItem("Zlibrary", "RemixUserkey", '')
    # 登录邮箱历史（JSON 字符串，登录成功后记录，下拉选择）
    zlibrary_email_history = ConfigItem("Zlibrary", "EmailHistory", '[]')

    # 是否使用内置 z-library 账号（轮询下载，全局每日5本，无需登录）
    use_zlibrary_builtin_account = ConfigItem("Book", "UseBuiltinAccount", False, BoolValidator())

    # 分页每页条数记忆（各页面独立保存，下次启动按记忆数量显示）
    comicPageSize = ConfigItem("Pagination", "ComicPageSize", 9)
    bookPageSize = ConfigItem("Pagination", "BookPageSize", 10)
    collectPageSize = ConfigItem("Pagination", "CollectPageSize", 15)
    downloadPageSize = ConfigItem("Pagination", "DownloadPageSize", 10)

    # 搜索历史（JSON 字符串数组，最新在前；漫画/图书/收藏/下载 四页各自独立）
    comic_search_history = ConfigItem("SearchHistory", "Comic", '[]')
    book_search_history = ConfigItem("SearchHistory", "Book", '[]')
    collect_search_history = ConfigItem("SearchHistory", "Collect", '[]')
    download_search_history = ConfigItem("SearchHistory", "Download", '[]')

VERSION_NO = 'V2.0.2'
YEAR = date.today().year
AUTHOR = "甜甜的王甜甜"
HELP_URL = "https://support.qq.com/products/656074"
GITHUBURL = "https://github.com/hlning/cmbok"
# 版本检测：GitHub Releases API（无需后台）
GITHUB_RELEASE_API = "https://api.github.com/repos/hlning/cmbok/releases/latest"
# 公告：仓库内 notification.json，经 jsDelivr CDN 拉取（国内可访问）
NOTIFICATION_URL = "https://cdn.jsdelivr.net/gh/hlning/cmbok@main/notification.json"
# 地址配置：仓库内 url_config.json，启动时拉取更新 copy_url/zlibrary_url
URL_CONFIG_URL = "https://cdn.jsdelivr.net/gh/hlning/cmbok@main/url_config.json"
QQ_URL = "https://qun.qq.com/universal-share/share?ac=1&authKey=UJg9rCpoodLcpWGfFguhn9aRBO8i%2FMeQROFiMa5Xaw1DoTtz7JOEOvRcobUAhxAf&busi_data=eyJncm91cENvZGUiOiIxMDAzNzczMDA1IiwidG9rZW4iOiJnQ0dBWlRkOVdKQ3BteGhjSkFNcnVlZ1RPcmRQK3JFaVJuWS9mblNheXBZVUxwaEVNTVRCVENDaVdXTUxlQ2RiIiwidWluIjoiMjMyODg5MzYxMiJ9&data=eR26EQcAE3uiE4QF0IUFlX0NH1JUHyxoAGZbJnsHiT_-88NWV2Ybbp8q9OwC3va4LBGNHTyq_dJqeEZd14dK7Q&svctype=4&tempid=h5_group_info"
# 作者个人主页（软件/版本发布更新地）
SITE_URL = "https://bluemood.xiaomy.net/"
LOG_PATH = 'app/app.log'

cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load('app/config/config.json', cfg)
