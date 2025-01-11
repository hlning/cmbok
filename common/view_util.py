from PyQt5.QtCore import Qt
from qfluentwidgets import InfoBar, InfoBarPosition


def info_bar_tip(info_bar_icon, title, content, parent, position=InfoBarPosition.TOP, orient=Qt.Horizontal,
                 is_closable=True, duration=3000):
    w = InfoBar(
        icon=info_bar_icon,
        title=title,
        content=content,
        orient=orient,
        isClosable=is_closable,
        position=position,
        duration=duration,
        parent=parent
    )
    w.show()
