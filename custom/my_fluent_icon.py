from enum import Enum

from qfluentwidgets import getIconColor, Theme, FluentIconBase


class MyFluentIcon(FluentIconBase, Enum):
    """ Custom icons """

    HAVE_COLLECT = "have_collect"
    COLLECT = "collect"
    COMIC = "comic"
    BOOK = "book"
    PDF = "pdf"
    CLEAR = "clear"
    QQ = "qq"

    def path(self, theme=Theme.AUTO):
        # getIconColor() 根据主题返回字符串 "white" 或者 "black"
        color = getIconColor(theme)
        name = self.value
        return f':/cmbok/images/{name}_{getIconColor(theme)}.svg'
