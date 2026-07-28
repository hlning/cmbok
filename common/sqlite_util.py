import logging
import os
import sqlite3
import traceback


class Row:
    """表示一行查询结果，允许通过属性访问"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return f"Row({self.__dict__})"


class SQLiteDatabase:
    def __init__(self):
        """初始化数据库连接"""
        self.db_folder = 'app/db'
        os.makedirs(self.db_folder, exist_ok=True)
        self.db_name = os.path.join(self.db_folder, 'cmbok.db')
        self.db_exists = os.path.isfile(self.db_name)
        self.connection = sqlite3.connect(self.db_name)
        self.cursor = self.connection.cursor()

    def __enter__(self):
        """进入上下文管理器时返回自身"""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """退出上下文管理器时关闭连接，并处理异常"""
        if exc_type is not None:  # 如果发生了异常
            self.connection.rollback()  # 回滚事务
        """退出上下文管理器时关闭连接"""
        self.close()

    def init(self):
        # 初始化数据库
        # 创建漫画下载记录表
        # cover 漫画封面
        # name 漫画名称
        # author 漫画作者
        # key 漫画/图书唯一key，漫画：path_word，图书：book_id
        # chapter_name 章节名称 只有漫画有
        # chapter_path_word 章节key 只有漫画有
        # book_hash 图书hash
        # type 类型。1：漫画 2：图书
        # status 状态：-4：今日无法下载 -3：软件退出 -2：无法下载 -1：转换epub失败 1：下载中 2：等待中 3：已完成 0：下载失败
        # process 进度
        # start_time 开始时间
        # finish_time 完成时间

        # 先检测 cmbok.db 是否已存在：已存在则做表结构同步与数据迁移；不存在则新建库
        if self.db_exists:
            logging.info('[DB] 检测到已有 cmbok.db，执行表结构同步与数据迁移')
        else:
            logging.info('[DB] 未检测到 cmbok.db，新建数据库并初始化默认数据')

        # ===== 表结构同步：不存在则按最新结构建表；存在则补齐缺失列（ensure_table 对新建/已有库均幂等）=====

        # 漫画/图书下载记录表
        self.ensure_table('cmbok_download_history',
                          {'id': 'INTEGER PRIMARY KEY', 'cover': 'TEXT', 'name': 'TEXT',
                           'author': 'TEXT', 'key': 'TEXT', 'chapter_name': 'TEXT',
                           'chapter_path_word': 'TEXT', 'book_hash': 'TEXT', 'type': 'INTEGER',
                           'status': 'INTEGER', 'process': 'INTEGER', 'start_time': 'TEXT', 'finish_time': 'TEXT'})

        # 漫画/图书收藏记录表
        self.ensure_table('cmbok_collection_record',
                          {'id': 'INTEGER PRIMARY KEY', 'cover': 'TEXT', 'name': 'TEXT',
                           'author': 'TEXT', 'key': 'TEXT', 'book_hash': 'TEXT', 'book_extension': 'TEXT',
                           'type': 'INTEGER', 'collection_time': 'TEXT', 'folder_id': 'INTEGER'})

        # 收藏文件夹表
        folder_table_new = self.ensure_table('comic_collection_folder',
                                             {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT', 'icon': 'TEXT',
                                              'type': 'INTEGER', 'parent_id': 'INTEGER', 'add_time': 'TEXT'})
        if folder_table_new:
            # 首次创建文件夹表：把已有收藏记录的 folder_id 置 0（根目录）
            self.update_data('cmbok_collection_record', {'folder_id': 0})

        # 站点下载记录表
        self.ensure_table('website_download_record',
                          {'id': 'INTEGER PRIMARY KEY', 'comic_name': 'TEXT', 'chapter_num': 'INTEGER',
                           'downloaded_num': 'INTEGER', 'downloading_num': 'INTEGER', 'is_update': 'INTEGER',
                           'start_time': 'TEXT', 'end_time': 'TEXT'})

        # 漫画站点配置表
        self.ensure_table('comic_website',
                          {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT', 'icon': 'TEXT',
                           'url': 'TEXT', 'comic_cover_dom': 'TEXT', 'comic_name_dom': 'TEXT',
                           'comic_author_dom': 'TEXT', 'chapter_name_dom': 'TEXT', 'chapter_link_dom': 'TEXT',
                           'img_dom': 'TEXT', 'use_frame': 'INTEGER', 'img_attr': 'TEXT', 'img_script': 'TEXT'})

        # ===== 数据迁移：重置 comic_website 为默认站点（每次 init 清空并重建，保证配置为最新默认值）=====
        self._reseed_comic_website()

        # 清理无用遗留表（旧版本残留，代码已不再使用）
        self.cursor.execute('DROP TABLE IF EXISTS comic_mangacopy_history')
        self.cursor.execute('DROP TABLE IF EXISTS cmbok_z_library_account')
        self.cursor.execute('DROP TABLE IF EXISTS cmbok_builtin_download_count')
        self.connection.commit()

        # comic_website 站点配置改为纯本地 sqlite 维护（不再从后台同步）

        self.close()

    def check_table_exists(self, table_name):
        # 查询sqlite_master表，检查指定的表是否存在
        result = self.query_first_data('sqlite_master', {'type': 'table', 'name': table_name})

        # 如果返回的结果为None，表示表不存在
        if result:
            return True
        else:
            return False

    def _reseed_comic_website(self):
        """每次 db init 清空 comic_website 并重置为默认站点列表。"""
        # 默认站点（参考油猴脚本 getImgs 配置；use_frame=1 走独立取图窗口，img_script 为取图JS片段）
        default_sites = [
            {'name': '来漫画', 'icon': 'https://www.comemh8.com/template/skin4_20110501/images/logo.png',
             'url': 'https://www.comemh8.com/', 'comic_cover_dom': '.info_cover .cover img',
             'comic_name_dom': '.intro_l .title h1', 'comic_author_dom': '',
             'chapter_name_dom': '.plist.pnormal ul li a', 'chapter_link_dom': '.plist.pnormal ul a',
             'img_dom': '.img-box.J_shareContent img', 'use_frame': 1, 'img_attr': '',
             'img_script': 'var w = ifr.contentWindow; var h = w.gethost(); return w.getUrlpics().map(function(e){ return h + e; });'},
            {'name': '再漫画', 'icon': 'https://manhua.zaimanhua.com/_nuxt/zmh-logo.d5f02b77.png',
             'url': 'https://manhua.zaimanhua.com/', 'comic_cover_dom': '',
             'comic_name_dom': '.wrap_intro_l_comic h1 a', 'comic_author_dom': '',
             'chapter_name_dom': '.tab-content-selected a', 'chapter_link_dom': '.tab-content-selected a',
             'img_dom': '', 'use_frame': 0, 'img_attr': '', 'img_script': ''},
            {'name': '咚漫', 'icon': 'https://cdn-static.dongmanmanhua.cn/image/pc/newLogo/home_papge_logo_120.png',
             'url': 'https://www.dongmanmanhua.cn/', 'comic_cover_dom': '',
             'comic_name_dom': 'h1.subj', 'comic_author_dom': '',
             'chapter_name_dom': '#_listUl .subj span', 'chapter_link_dom': '#_listUl a',
             'img_dom': '#_imageList img', 'use_frame': 0, 'img_attr': 'data-url', 'img_script': ''},
            {'name': 'MYCOMIC', 'icon': '', 'url': 'https://mycomic.com/cn', 'comic_cover_dom': '',
             'comic_name_dom': '.truncate.whitespace-nowrap', 'comic_author_dom': '',
             'chapter_name_dom': '.mt-8.mb-12 a', 'chapter_link_dom': '.mt-8.mb-12 a',
             'img_dom': '.-mx-6 img', 'use_frame': 1, 'img_attr': '', 'img_script': ''},
        ]
        try:
            self.delete_all_data('comic_website')
            for site in default_sites:
                self.insert_data('comic_website', site)
        except Exception:
            logging.info('重置 comic_website 失败: ' + traceback.format_exc())

    def column_exists(self, table_name, column_name):
        # 执行 PRAGMA table_info 查询以获取表的字段信息
        self.cursor.execute(f"PRAGMA table_info({table_name})")
        columns = self.cursor.fetchall()

        # 遍历字段信息，检查特定字段是否存在
        for column in columns:
            if column[1] == column_name:  # column[1] 是字段名称
                return True

        return False

    def create_table(self, table_name, columns):
        """创建表"""
        columns_with_types = ', '.join([f"{column} {col_type}" for column, col_type in columns.items()])
        sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_with_types});"
        self.cursor.execute(sql)
        self.connection.commit()

    def ensure_table(self, table_name, columns):
        """确保表结构为最新：表不存在则按 columns 建表；表存在则逐列检查，缺失则 ALTER ADD COLUMN 补齐。
        返回 True 表示本次为新建表，False 表示已存在（可能做了列迁移）。"""
        if not self.check_table_exists(table_name):
            self.create_table(table_name, columns)
            return True
        # 表已存在：补齐所有缺失列，使旧库结构与最新建表语句一致
        for col, col_type in columns.items():
            if col == 'id':
                continue  # 主键列已存在，不可 ALTER 添加
            if not self.column_exists(table_name, col):
                self.cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {col} {col_type}')
        self.connection.commit()
        return False

    def insert_data(self, table_name, data):
        """插入数据"""
        columns = ', '.join(data.keys())
        placeholders = ', '.join('?' * len(data))
        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders});"
        self.cursor.execute(sql, tuple(data.values()))
        self.connection.commit()
        return self.cursor.lastrowid  # 返回插入后的 ID

    def query_records(self, conditions=None, order_by=None, limit=None, offset=None):
        sql = '''select id,cover,name,author,key,book_hash,book_extension,'record' is_folder,type,collection_time,folder_id from cmbok_collection_record'''
        return self.query_result(sql, conditions, order_by, limit, offset)

    def query_folder_records(self, conditions=None, order_by=None, limit=None, offset=None):
        sql = '''select * from (select * from (select id,icon cover,name,'' author,'' key,'' book_hash,'' book_extension,'folder' is_folder,type,add_time,parent_id folder_id from comic_collection_folder order by add_time desc) union all select * from (select id,cover,name,author,key,book_hash,book_extension,'record' is_folder,type,collection_time,folder_id from cmbok_collection_record order by collection_time desc))'''
        return self.query_result(sql, conditions, order_by, limit, offset)

    def query_data(self, table_name, conditions=None, order_by=None, limit=None, offset=None):
        """查询数据，支持分页"""
        sql = f"SELECT * FROM {table_name}"
        return self.query_result(sql, conditions, order_by, limit, offset)

    def query_result(self, sql, conditions=None, order_by=None, limit=None, offset=None):
        params = []
        if conditions:
            condition_clauses = []
            for key, value in conditions.items():
                if value is not None and value != '' and value != '%%' and value != '%None%':  # 仅当值不为空时才添加条件
                    if isinstance(value, str) and '%' in value:  # 支持模糊查询
                        condition_clauses.append(f"{key} LIKE ?")
                        params.append(value)
                    elif isinstance(value, tuple) and len(value) == 2:  # 支持不等于
                        condition_clauses.append(f"{key} <= ?")
                        params.append(value[1])  # 使用元组的第二个值
                    else:
                        condition_clauses.append(f"{key} = ?")
                        params.append(value)

            if condition_clauses:
                sql += " WHERE " + " AND ".join(condition_clauses)  # 使用 OR 连接条件

        if order_by:
            sql += f" ORDER BY {order_by}"

        if limit is not None:
            sql += f" LIMIT ?"
            params.append(limit)  # 将 limit 添加到参数列表
            if offset is not None:
                sql += f" OFFSET ?"
                params.append(offset)  # 将 offset 添加到参数列表

        sql += ";"
        rows = self.cursor.execute(sql, params).fetchall()
        # 将查询结果转换为 Row 对象列表
        return [Row(**dict(zip([column[0] for column in self.cursor.description], row))) for row in rows]

    def query_first_data(self, table_name, conditions=None):
        """按条件查询获取第一条数据，返回 Row 格式"""
        result = self.query_data(table_name, conditions=conditions, limit=1)  # 使用 limit=1 获取第一条数据
        return result[0] if result else None  # 返回第一条 Row 数据或 None

    def count_data(self, table_name, conditions=None):
        """查询数据总数"""
        sql = f"SELECT COUNT(*) FROM {table_name}"
        params = []

        if conditions:
            condition_clauses = []
            for key, value in conditions.items():
                if value is not None and value != '' and value != '%%' and value != '%None%':  # 仅当值不为空时才添加条件
                    if isinstance(value, str) and '%' in value:  # 支持模糊查询
                        condition_clauses.append(f"{key} LIKE ?")
                        params.append(value)
                    else:
                        condition_clauses.append(f"{key} = ?")
                        params.append(value)

            if condition_clauses:
                sql += " WHERE " + " AND ".join(condition_clauses)  # 使用 OR 连接条件

        sql += ";"
        return self.cursor.execute(sql, params).fetchone()[0]  # 返回计数结果

    def update_data(self, table_name, data, conditions=None):
        """更新数据"""
        set_str = ', '.join([f"{key} = ?" for key in data.keys()])
        if conditions is not None:
            condition_str = ' AND '.join([f"{key} = ?" for key in conditions.keys()])
            sql = f"UPDATE {table_name} SET {set_str} WHERE {condition_str};"
            self.cursor.execute(sql, tuple(data.values()) + tuple(conditions.values()))
        else:
            sql = f"UPDATE {table_name} SET {set_str};"
            self.cursor.execute(sql, tuple(data.values()))
        self.connection.commit()

    def delete_data(self, table_name, conditions):
        """删除数据"""
        condition_str = ' AND '.join([f"{key} = ?" for key in conditions.keys()])
        sql = f"DELETE FROM {table_name} WHERE {condition_str};"
        self.cursor.execute(sql, tuple(conditions.values()))
        self.connection.commit()

    def delete_all_data(self, table_name):
        """删除数据"""
        sql = f"DELETE FROM {table_name}"
        self.cursor.execute(sql)
        self.connection.commit()

    def delErrorRecord(self, table_name):
        sql = f"DELETE FROM {table_name} WHERE status<=0;"
        self.cursor.execute(sql)
        self.connection.commit()

    def close(self):
        """关闭数据库连接"""
        self.connection.close()

    def rollback(self):
        """回滚事务"""
        self.connection.rollback()
