# coding:utf-8
import logging
import traceback

import requests
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QLabel, QFileDialog
from qfluentwidgets import FluentIcon as FIF, InfoBarIcon, MessageBox
from qfluentwidgets import InfoBar
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, OptionsSettingCard, PushSettingCard,
                            HyperlinkCard, PrimaryPushSettingCard, ScrollArea,
                            ComboBoxSettingCard, ExpandLayout, CustomColorSettingCard,
                            setTheme, setThemeColor, RangeSettingCard)

from common.config import cfg, HELP_URL, VERSION, QQ_URL, GITHUBURL
from common.style_sheet import StyleSheet
from common.util import check_url
from common.view_util import info_bar_tip
from custom.my_fluent_icon import MyFluentIcon


class SettingInterface(ScrollArea):
    """ Setting interface """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
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

        self.downloadFolderCard = PushSettingCard(
            '选择文件夹',
            FIF.DOWNLOAD,
            '下载目录',
            cfg.get(cfg.downloadFolder),
            self.useSettingGroup
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
        self.helpCard = HyperlinkCard(
            HELP_URL,
            '前往反馈',
            FIF.HELP,
            '反馈',
            '如果有问题或者建议，可以反馈给我',
            self.aboutGroup
        )

        self.githubCard = HyperlinkCard(
            GITHUBURL,
            '开源地址',
            FIF.GITHUB,
            '本软件已开源',
            'Cmbok已开源，代码写的不好，请多包涵',
            self.aboutGroup
        )

        self.qqCard = HyperlinkCard(
            QQ_URL,
            '我要加入',
            MyFluentIcon.QQ,
            'QQ群：927528211',
            '欢迎各位喜欢本软件或有兴趣交流的朋友入群一起沟通',
            self.aboutGroup
        )

        self.aboutCard = PrimaryPushSettingCard(
            '检查更新',
            FIF.INFO,
            '关于',
            f"这是我自从买了一台Kindle之后，做来下载漫画和图书用的，目前还在完善中，当前版本" + VERSION + "\nPyQt-Fluent-Widgets @2025 zhiyiYo",
            self.aboutGroup
        )
        self.aboutCard.clicked.connect(self.aboubt)

        self.__initWidget()

    def aboubt(self):
        try:
            url = 'https://bluemood.xiaomy.net/cmbok/version/version'
            if check_url(url):
                response = requests.get(url)
                response.raise_for_status()
                if response.status_code == 200:
                    results = response.json()
                    version = results['version']
                    if version is not None and version != '':
                        w = MessageBox("检测到新版本，是否更新？", version['content'], self.window())
                        if w.exec():
                            url = QUrl(version['url'])  # 要打开的链接
                            QDesktopServices.openUrl(url)
                        else:
                            logging.info('取消')
                    else:
                        info_bar_tip(InfoBarIcon.INFORMATION, '温馨提示', '没有新版本发布~~', self)
            else:
                self.get_notification()
        except Exception:
            logging.info(traceback.format_exc())
            logging.info('服务器已关闭')

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
        # 下载目录
        self.useSettingGroup.addSettingCard(self.downloadFolderCard)

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

        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.zoomCard)

        self.updateSoftwareGroup.addSettingCard(self.updateOnStartUpCard)

        self.aboutGroup.addSettingCard(self.helpCard)
        self.aboutGroup.addSettingCard(self.qqCard)
        self.aboutGroup.addSettingCard(self.githubCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.useSettingGroup)
        self.expandLayout.addWidget(self.comicSettingGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.updateSoftwareGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def __showRestartTooltip(self):
        """ show restart tooltip """
        InfoBar.success(
            self.tr('Updated successfully'),
            self.tr('Configuration takes effect after restart'),
            duration=1500,
            parent=self
        )

    def __onDownloadFolderCardClicked(self):
        folder = QFileDialog.getExistingDirectory(
            self, '选择m目录', cfg.get(cfg.downloadFolder))
        if not folder or cfg.get(cfg.downloadFolder) == folder:
            return

        cfg.set(cfg.downloadFolder, folder)
        self.downloadFolderCard.setContent(folder)

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
            self.__onDownloadFolderCardClicked)

        # ebook-convert.exe路径选择监听
        self.calibrePathCard.clicked.connect(
            self.__onCalibrePathCardClicked)

        # personalization
        cfg.themeChanged.connect(setTheme)
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c))
