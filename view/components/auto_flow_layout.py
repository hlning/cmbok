# coding:utf-8
"""自适应流式布局：每行固定 N 个、卡片宽度随容器自适应。

qfluentwidgets 的 FlowLayout 按 item.sizeHint() 排列，而 sizeHint 不随
setFixedWidth 变化（PyQt5 的 QWidgetItem.sizeHint 不展开 minimumSize），
导致动态设置卡片宽度时每行卡片数不会改变。AutoFlowLayout 重写 _doLayout，
改用卡片的 fixedWidth/Height（maximumSize）决定排列，使 setFixedWidth 生效。
"""
from PyQt5.QtCore import QPoint, QRect, QSize
from qfluentwidgets import FlowLayout

_QWIDGETSIZE_MAX = 16777215


class AutoFlowLayout(FlowLayout):
    """每行 N 个、卡片宽度自适应的 FlowLayout"""

    def _doLayout(self, rect, move):
        aniRestart = False
        margin = self.contentsMargins()
        x = rect.x() + margin.left()
        y = rect.y() + margin.top()
        rowHeight = 0
        spaceX = self.horizontalSpacing()
        spaceY = self.verticalSpacing()

        for i, item in enumerate(self._items):
            w = item.widget()
            if w and not w.isVisible() and self.isTight:
                continue

            sh = item.sizeHint()
            # 优先用卡片的 fixedWidth/Height（maximumSize），fallback 到 sizeHint
            mw = w.maximumWidth() if w else _QWIDGETSIZE_MAX
            mh = w.maximumHeight() if w else _QWIDGETSIZE_MAX
            iw = mw if 0 < mw < _QWIDGETSIZE_MAX else sh.width()
            ih = mh if 0 < mh < _QWIDGETSIZE_MAX else sh.height()

            nextX = x + iw + spaceX
            if nextX - spaceX > rect.right() - margin.right() and rowHeight > 0:
                x = rect.x() + margin.left()
                y = y + rowHeight + spaceY
                nextX = x + iw + spaceX
                rowHeight = 0

            if move:
                target = QRect(QPoint(x, y), QSize(iw, ih))
                if not self.needAni:
                    item.setGeometry(target)
                elif target != self._anis[i].endValue():
                    self._anis[i].stop()
                    self._anis[i].setEndValue(target)
                    aniRestart = True

            x = nextX
            rowHeight = max(rowHeight, ih)

        if self.needAni and aniRestart:
            self._aniGroup.stop()
            self._aniGroup.start()

        return y + rowHeight + margin.bottom() - rect.y()
