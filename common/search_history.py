# coding:utf-8
"""搜索历史读写封装

历史以 JSON 字符串数组形式存于 config.json（参考 zlibrary_email_history 模式），
最新在前、自动去重、上限 max_count 条。四页（漫画/图书/收藏/下载）各自绑定一个 ConfigItem。
"""
import json
import logging

from common.config import cfg

logger = logging.getLogger(__name__)


class SearchHistory:
    """绑定一个 ConfigItem 的搜索历史读写器"""

    def __init__(self, config_item, max_count=15):
        self._item = config_item
        self._max_count = max_count

    def get_all(self):
        """返回历史列表（最新在前）；JSON 损坏时回退空列表，不抛异常"""
        try:
            data = cfg.get(self._item)
            items = json.loads(data) if data else []
            if not isinstance(items, list):
                return []
            # 仅保留非空字符串
            return [str(k).strip() for k in items if str(k).strip()]
        except Exception as e:
            logger.warning(f'[SearchHistory] 读取历史失败，回退空列表: {e}')
            return []

    def add(self, keyword):
        """记录一条搜索词：strip、去重、插到头部、截断上限"""
        keyword = (keyword or '').strip()
        if not keyword:
            return
        items = self.get_all()
        items = [k for k in items if k != keyword]
        items.insert(0, keyword)
        items = items[:self._max_count]
        self._save(items)

    def remove(self, keyword):
        """删除单条历史"""
        keyword = (keyword or '').strip()
        items = [k for k in self.get_all() if k != keyword]
        self._save(items)

    def clear(self):
        """清空全部历史"""
        self._save([])

    def _save(self, items):
        try:
            cfg.set(self._item, json.dumps(items, ensure_ascii=False))
        except Exception as e:
            logger.warning(f'[SearchHistory] 保存历史失败: {e}')
