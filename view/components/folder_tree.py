# coding:utf-8
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QTreeWidgetItem
from qfluentwidgets import TreeWidget

from common.sqlite_util import SQLiteDatabase
from common.style_sheet import StyleSheet


class Frame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(0, 8, 0, 0)

        self.setObjectName('frame')
        StyleSheet.VIEW_INTERFACE.apply(self)

    def addWidget(self, widget):
        self.hBoxLayout.addWidget(widget)


class TreeFrame(Frame):
    def __init__(self, type, parent=None):
        super().__init__(parent)
        self.tree = TreeWidget(self)
        self.addWidget(self.tree)

        # 查询所有文件夹
        with SQLiteDatabase() as db:
            self.items = db.query_data('comic_collection_folder', {'type': type}, 'add_time DESC')

        home_item = QTreeWidgetItem([self.tr('首页')])
        self.tree.addTopLevelItem(home_item)

        for item in self.items:
            parent_id = item.parent_id
            if parent_id == 0:  # 根节点
                tree_item = QTreeWidgetItem([item.name])
                self.tree.addTopLevelItem(tree_item)
                self.add_children(tree_item, item.id)

        self.tree.expandAll()
        self.tree.setHeaderHidden(True)

        self.setFixedSize(300, 380)

    def add_children(self, parent_item, parent_id):
        for item in self.items:
            if item.parent_id == parent_id:
                child_item = QTreeWidgetItem([item.name])
                parent_item.addChild(child_item)
                self.add_children(child_item, item.id)
