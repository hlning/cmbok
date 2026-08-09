# coding:utf-8
"""非模态遮罩弹窗呈现辅助。

详情弹窗、站点新增/修改弹窗、搜索页收藏弹窗等沿用 MessageBoxBase（参考工具箱 ToolMessageBox
的遮罩弹窗形式），改用非模态 show 显示，parent 取当前导航页（stackedWidget.currentWidget）：
弹窗作为当前页子 widget，切换导航时随页面被 QStackedWidget 隐藏（不叠到新页面），切回时随页面
恢复显示（保留弹窗与表单状态）；遮罩盖当前页（=内容区），导航栏为浮层不受影响。

show 非模态返回后局部引用会丢失，需持引用防 GC；对话框关闭后自动 deleteLater 清理。
"""

# 活跃非模态弹窗引用，防 show 后被 GC
_active_detail_dialogs = set()


def content_parent(win):
    """取主窗口当前导航页（stackedWidget.currentWidget）作为弹窗 parent。

    parent 为当前页而非 stackedWidget.view：弹窗作为当前页子 widget，切换导航时随页面被
    QStackedWidget 隐藏（不叠到新页面），切回时随页面恢复（保留弹窗与表单）。遮罩盖当前页
    （=内容区），导航栏为浮层不受影响（与工具箱 ToolMessageBox parent=self 同款做法）。
    win 通常是 self.window()；取不到当前页时退回 win 本身。
    """
    sw = getattr(win, 'stackedWidget', None)
    view = getattr(sw, 'view', None) if sw else None
    if view is not None:
        cur = view.currentWidget()
        if cur is not None:
            return cur
    return win


def present_detail_dialog(dlg):
    """非模态呈现弹窗：show 而非 exec，主窗口导航栏可继续操作。

    持引用防 GC；accept/reject 触发 done 淡出动画后才 hide，连 deleteLater 在动画结束后清理。
    调用方若需在确认后执行动作，先 dlg.accepted.connect(回调) 再调用本函数（回调先于 deleteLater
    执行，此时控件仍存活，可安全读取表单数据）。
    """
    _active_detail_dialogs.add(dlg)
    dlg.destroyed.connect(lambda *a: _active_detail_dialogs.discard(dlg))
    dlg.accepted.connect(dlg.deleteLater)
    dlg.rejected.connect(dlg.deleteLater)
    dlg.show()
