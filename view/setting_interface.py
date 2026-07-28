# coding:utf-8
import logging
import traceback

import requests
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import QWidget, QLabel, QFileDialog, QDialog, QVBoxLayout
from qfluentwidgets import FluentIcon as FIF, InfoBarIcon, InfoBarPosition, MessageBox
from qfluentwidgets import InfoBar
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, OptionsSettingCard, PushSettingCard,
                            HyperlinkCard, PrimaryPushSettingCard, ScrollArea,
                            ComboBoxSettingCard, ExpandLayout, CustomColorSettingCard,
                            setTheme, setThemeColor, RangeSettingCard)

from common.config import cfg, GITHUBURL, QQ_URL, GITHUB_RELEASE_API
from common.signal_bus import signalBus
from common.style_sheet import StyleSheet
from custom.my_fluent_icon import MyFluentIcon
from view.components.info_bar_tip import show_tip


class SettingInterface(ScrollArea):
    """ Setting interface """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('SettingInterface')

        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        # setting label
        self.settingLabel = QLabel('设置', self)

        # 使用设置
        self.useSettingGroup = SettingCardGroup(
            '使用设置', self.scrollWidget)

        '''
        self.useLocalServerCard = SwitchSettingCard(
            FIF.SEND,
            '使用本地服务',
            '如果你有梯子请打开此开关，会使用本地下载，速度更快',
            configItem=cfg.useLocalServer,
            parent=self.useSettingGroup
        )
        '''
        self.downloadThreadNumCard = RangeSettingCard(
            cfg.downloadThreadNum,
            FIF.IOT,
            '下载最大线程',
            '此设置用于同时可以下载多少漫画章节或多少图书',
            self.useSettingGroup
        )

        self.windowWidthCard = RangeSettingCard(
            cfg.windowWidth,
            MyFluentIcon.WIDTH,
            '窗口宽度',
            '已经把宽度不能调节放开，可以在这里配置适合的宽度',
            self.useSettingGroup
        )

        self.windowHeightCard = RangeSettingCard(
            cfg.windowHeight,
            MyFluentIcon.HEIGHT,
            '窗口高度',
            '已经把高度不能调节放开，可以在这里配置适合的高度',
            self.useSettingGroup
        )

        self.downloadFolderCard = PushSettingCard(
            '选择文件夹',
            FIF.DOWNLOAD,
            '下载目录',
            cfg.get(cfg.downloadFolder),
            self.useSettingGroup
        )

        self.toolSaveFolderCard = PushSettingCard(
            '选择文件夹',
            FIF.SAVE,
            '工具箱文件保存目录',
            cfg.get(cfg.toolSaveFolder),
            self.useSettingGroup
        )

        # Komga设置
        self.komgaSettingGroup = SettingCardGroup(
            'Komga设置（Komga是一款开源阅读器）', self.scrollWidget)

        self.isRunKomgaCard = SwitchSettingCard(
            FIF.FOLDER,
            '软件启动时是否运行komga',
            '如果开启，软件启动时会自动运行komga',
            configItem=cfg.isRunKomga,
            parent=self.komgaSettingGroup
        )

        self.komgaBackgrounderCard = SwitchSettingCard(
            FIF.FOLDER,
            'Komga是否保留后台',
            '如果开启，软件退出后komga依旧会运行',
            configItem=cfg.komgaBackgrounder,
            parent=self.komgaSettingGroup
        )

        # 漫画设置
        self.comicSettingGroup = SettingCardGroup(
            '漫画设置', self.scrollWidget)

        self.epubSaveFolderCard = SwitchSettingCard(
            FIF.FOLDER,
            'epub是否保存到漫画根目录',
            '如果开启，epub文件会保存在漫画根目录下面，不会保存到章节目录下',
            configItem=cfg.epubSaveFolder,
            parent=self.comicSettingGroup
        )

        self.isDelChapterImagesCard = SwitchSettingCard(
            FIF.DELETE,
            '是否删除章节图片',
            '如果开启，合并epub后会删除对应章节下的所有图片',
            configItem=cfg.isDelChapterImages,
            parent=self.comicSettingGroup
        )

        self.isSavePdfCard = SwitchSettingCard(
            MyFluentIcon.PDF,
            '是否合并保存PDF',
            '如果开启，会合并一个PDF文件',
            configItem=cfg.isSavePdf,
            parent=self.comicSettingGroup
        )

        self.isSaveMobiCard = SwitchSettingCard(
            FIF.SYNC,
            '是否转换成Mobi',
            '如果开启，会转换成一个Mobi文件',
            configItem=cfg.isSaveMobi,
            parent=self.comicSettingGroup
        )

        self.calibrePathCard = PushSettingCard(
            '选择文件',
            FIF.TILES,
            'ebook-convert.exe路径，如果开启转换Mobi，需要先安装Calibre',
            cfg.get(cfg.calibrePath),
            self.comicSettingGroup
        )

        self.calibreOutputDeviceCard = ComboBoxSettingCard(
            cfg.calibreOutputDevice,
            FIF.DOCUMENT,
            '转换Mobi页面设置',
            '根据选择的设备，Mobi才能更贴切设备显示，否则可能阅读会出现白页等情况',
            texts=['default', 'kindle', 'kindle_dx', 'kindle_fire', 'kindle_oasis', 'kindle_pw', 'kindle_pw3',
                   'kindle_scribe', 'kindle_voyage', 'ipad', 'ipad3', 'cybookg3', 'cybook_opus', 'hanlinv3', 'hanlinv5',
                   'illiad', 'irexdr1000', 'irexdr800', 'jetbook5', 'kobo', 'msreader', 'mobipocket', 'nook',
                   'nook_color',
                   'nook_hd_plus', 'pocketbook_inkpad3', 'pocketbook_lux', 'pocketbook_hd', 'pocketbook_900',
                   'pocketbook_pro_912',
                   'galaxy', 'sony', 'sony300', 'sony900', 'sony-landscape', 'sonyt3', 'tablet', 'generic_eink_large',
                   'generic_eink',
                   'generic_eink_hd'],
            parent=self.comicSettingGroup
        )

        # 站点设置
        self.websiteSettingGroup = SettingCardGroup(
            '站点设置', self.scrollWidget)

        self.isMergeChapterCard = SwitchSettingCard(
            FIF.MEGAPHONE,
            '漫画是否合并成卷',
            '注意，如果开启每次合并前都会清空漫画目录下的所有文件',
            configItem=cfg.isMergeChapte,
            parent=self.websiteSettingGroup
        )

        self.mergeChapterNumCard = RangeSettingCard(
            cfg.mergeChapterNum,
            FIF.IOT,
            '漫画多少话合并成一卷',
            '需先开启合并成卷，此设置用于站点中的漫画下载合并成一卷',
            self.websiteSettingGroup
        )

        # 图书设置
        self.bookSettingGroup = SettingCardGroup('图书设置', self.scrollWidget)
        self.useBuiltinAccountCard = SwitchSettingCard(
            MyFluentIcon.BOOK, '使用内置账号',
            '开启后图书搜索/下载使用内置账号轮询，每日最多5本，无需登录；关闭则需登录自己的账号',
            configItem=cfg.use_zlibrary_builtin_account,
            parent=self.bookSettingGroup
        )

        # 个性化
        self.personalGroup = SettingCardGroup(
            '个性化', self.scrollWidget)
        self.themeCard = OptionsSettingCard(
            cfg.themeMode,
            FIF.BRUSH,
            '应用主题',
            '调整你的应用外观',
            texts=[
                '浅色',
                '深色',
                '跟随系统'
            ],
            parent=self.personalGroup
        )
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor,
            FIF.PALETTE,
            '主题色',
            '选择你的应用主题色',
            self.personalGroup
        )
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            '毛玻璃效果',
            '开启后窗口启用云母（Mica）半透明效果，关闭可提升部分电脑流畅度（仅 Windows 11 生效）',
            configItem=cfg.micaEnabled,
            parent=self.personalGroup
        )
        self.navigationExpandedCard = SwitchSettingCard(
            FIF.MENU,
            '导航默认展开',
            '开启后启动时导航栏默认展开显示；关闭则折叠为图标模式',
            configItem=cfg.navigationExpanded,
            parent=self.personalGroup
        )
        self.zoomCard = OptionsSettingCard(
            cfg.dpiScale,
            FIF.ZOOM,
            '界面缩放',
            '调整小部件和字体的大小',
            texts=[
                "100%",
                "125%",
                "150%",
                "175%",
                "200%",
                '跟随系统'
            ],
            parent=self.personalGroup
        )

        # 软件更新
        self.updateSoftwareGroup = SettingCardGroup(
            '软件更新', self.scrollWidget)
        self.updateOnStartUpCard = SwitchSettingCard(
            FIF.UPDATE,
            '在应用程序启动时检查更新',
            '新版本将更加稳定并拥有更多功能（建议开启）',
            configItem=cfg.checkUpdateAtStartUp,
            parent=self.updateSoftwareGroup
        )

        # 关于
        self.aboutGroup = SettingCardGroup('关于', self.scrollWidget)
        self.githubCard = HyperlinkCard(
            GITHUBURL,
            '开源地址',
            FIF.GITHUB,
            '本软件已开源',
            'Cmbok已开源，代码写的不好，请多包涵',
            self.aboutGroup
        )

        self.donateCard = PrimaryPushSettingCard(
            '支持作者',
            FIF.HEART,
            '捐赠支持',
            '个人开发不易，如果这个软件帮助到了您，可以请作者喝杯奶茶',
            self.aboutGroup
        )

        self.qqCard = HyperlinkCard(
            QQ_URL,
            '我要加入',
            MyFluentIcon.QQ,
            'QQ群：1003773005',
            '欢迎各位喜欢本软件或有兴趣交流的朋友入群一起沟通',
            self.aboutGroup
        )

        self.aboutCard = PrimaryPushSettingCard(
            '检查更新',
            FIF.INFO,
            '关于',
            f"这是我自从买了一台Kindle之后，开发的下载、阅读漫画和图书的软件，且用且珍惜，当前版本：{cfg.get(cfg.version)}\nPyQt-Fluent-Widgets @{cfg.get(cfg.year)} zhiyiYo",
            self.aboutGroup
        )
        self.aboutCard.clicked.connect(self.aboubt)

        self.__initWidget()

    def aboubt(self):
        try:
            response = requests.get(GITHUB_RELEASE_API, timeout=10)
            if response.status_code == 200:
                release = response.json()
                tag = release.get('tag_name', '')
                if tag and tag != cfg.get(cfg.version):
                    body = release.get('body') or '发现新版本，是否前往下载？'
                    html_url = release.get('html_url') or GITHUBURL
                    w = MessageBox("检测到新版本，是否更新？", body, self.window())
                    if w.exec():
                        QDesktopServices.openUrl(QUrl(html_url))
                else:
                    show_tip(InfoBarIcon.INFORMATION, '温馨提示', '已是最新版本~~', self)
            else:
                show_tip(InfoBarIcon.ERROR, '温馨提示', '版本检测失败，请稍后重试', self)
        except Exception:
            logging.info(traceback.format_exc())
            show_tip(InfoBarIcon.ERROR, '温馨提示', '版本检测失败，请稍后重试', self)

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName('settingInterface')

        # initialize style sheet
        self.scrollWidget.setObjectName('scrollWidget')
        self.settingLabel.setObjectName('settingLabel')
        StyleSheet.SETTING_INTERFACE.apply(self)

        # initialize layout
        self.__initLayout()
        self.__connectSignalToSlot()

    def __initLayout(self):
        self.settingLabel.move(36, 30)

        # add cards to group
        # 使用本地服务
        # self.useSettingGroup.addSettingCard(self.useLocalServerCard)
        # 下载最大线程
        self.useSettingGroup.addSettingCard(self.downloadThreadNumCard)
        # 窗口宽度
        self.useSettingGroup.addSettingCard(self.windowWidthCard)
        # 窗口高度
        self.useSettingGroup.addSettingCard(self.windowHeightCard)
        # 下载目录
        self.useSettingGroup.addSettingCard(self.downloadFolderCard)
        # 工具箱文件保存目录
        self.useSettingGroup.addSettingCard(self.toolSaveFolderCard)
        # cmbok启动是否运行komga
        self.komgaSettingGroup.addSettingCard(self.isRunKomgaCard)
        # Komga是否保留后台
        self.komgaSettingGroup.addSettingCard(self.komgaBackgrounderCard)
        # epub是否保存到漫画根目录
        self.comicSettingGroup.addSettingCard(self.epubSaveFolderCard)
        # 是否删除章节图片
        self.comicSettingGroup.addSettingCard(self.isDelChapterImagesCard)
        # 是否合并保存PDF
        self.comicSettingGroup.addSettingCard(self.isSavePdfCard)
        # 是否转换成Mobi
        self.comicSettingGroup.addSettingCard(self.isSaveMobiCard)
        # ebook-convert.exe路径
        self.comicSettingGroup.addSettingCard(self.calibrePathCard)
        # 转换Mobi页面设置
        self.comicSettingGroup.addSettingCard(self.calibreOutputDeviceCard)
        # 是否合并成卷
        self.websiteSettingGroup.addSettingCard(self.isMergeChapterCard)
        # 站点漫画多少话合并成一个章节
        self.websiteSettingGroup.addSettingCard(self.mergeChapterNumCard)
        # 图书设置
        self.bookSettingGroup.addSettingCard(self.useBuiltinAccountCard)

        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.micaCard)
        self.personalGroup.addSettingCard(self.navigationExpandedCard)
        self.personalGroup.addSettingCard(self.zoomCard)

        self.updateSoftwareGroup.addSettingCard(self.updateOnStartUpCard)

        self.aboutGroup.addSettingCard(self.githubCard)
        self.aboutGroup.addSettingCard(self.donateCard)
        self.aboutGroup.addSettingCard(self.qqCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.useSettingGroup)
        self.expandLayout.addWidget(self.komgaSettingGroup)
        self.expandLayout.addWidget(self.comicSettingGroup)
        self.expandLayout.addWidget(self.websiteSettingGroup)
        self.expandLayout.addWidget(self.bookSettingGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.updateSoftwareGroup)
        self.expandLayout.addWidget(self.aboutGroup)

        # 捐赠按钮宽度与检查更新按钮保持一致
        self.donateCard.button.setFixedWidth(self.aboutCard.button.sizeHint().width())

    def __showRestartTooltip(self):
        """ show restart tooltip """
        InfoBar.success(
            self.tr('Updated successfully'),
            self.tr('Configuration takes effect after restart'),
            duration=1500,
            parent=self
        )

    def __onDownloadFolderCardClicked(self, type):
        folder = QFileDialog.getExistingDirectory(
            self, '选择m目录', cfg.get(cfg.downloadFolder))
        if not folder or cfg.get(cfg.downloadFolder) == folder:
            return

        if type == 1:
            cfg.set(cfg.downloadFolder, folder)
            self.downloadFolderCard.setContent(folder)
        elif type == 2:
            cfg.set(cfg.toolSaveFolder, folder)
            self.toolSaveFolder.setContent(folder)

    def __onCalibrePathCardClicked(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_name, _ = QFileDialog.getOpenFileName(self, "选择文件", "",
                                                   "Exe Files (*.exe);;All Files (*)",
                                                   options=options)

        if not file_name or cfg.get(cfg.calibrePath) == file_name:
            return

        cfg.set(cfg.calibrePath, file_name)
        self.calibrePathCard.setContent(file_name)

    def __connectSignalToSlot(self):
        """ connect signal to slot """
        cfg.appRestartSig.connect(self.__showRestartTooltip)

        self.downloadFolderCard.clicked.connect(
            lambda: self.__onDownloadFolderCardClicked(1))

        self.toolSaveFolderCard.clicked.connect(
            lambda: self.__onDownloadFolderCardClicked(2))

        # ebook-convert.exe路径选择监听
        self.calibrePathCard.clicked.connect(
            self.__onCalibrePathCardClicked)

        # personalization
        cfg.themeChanged.connect(setTheme)
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c))
        # 毛玻璃效果：开关变化时即时应用到主窗口
        self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged.emit)

        # 捐赠
        self.donateCard.clicked.connect(self._onDonateClicked)

    def _onDonateClicked(self):
        w = MessageBox(
            '我是甜甜🥰',
            '个人开发不易，如果这个项目帮助到了您，可以考虑请我喝一杯奶茶🍵。您的支持就是作者开发和维护项目的动力🚀',
            self
        )
        w.yesButton.setText('来啦')
        w.cancelButton.setText('下次一定')
        if w.exec():
            # 二维码弹窗居中显示
            dlg = QDialog(self)
            dlg.setWindowTitle('微信捐赠')
            layout = QVBoxLayout(dlg)
            label = QLabel(dlg)
            label.setPixmap(QPixmap(':/cmbok/images/wx.png'))
            layout.addWidget(label)
            dlg.adjustSize()
            win = self.window()
            fg = win.frameGeometry()
            dlg.move(fg.center() - dlg.rect().center())
            dlg.exec()
