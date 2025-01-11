import os
import sqlite3


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
        if not self.db_exists:
            # 创建漫画下载记录表
            # cover 漫画封面
            # name 漫画名称
            # author 漫画作者
            # key 漫画/图书唯一key，漫画：path_word，图书：book_id
            # chapter_name 章节名称 只有漫画有
            # chapter_path_word 章节key 只有漫画有
            # book_hash 图书hash
            # type 类型。1：漫画 2：图书
            # status 状态：-3：软件退出 -2：无法下载 -1：转换epub失败 1：下载中 2：等待中 3：已完成 0：下载失败
            # process 进度
            # start_time 开始时间
            # finish_time 完成时间
            self.create_table('cmbok_download_history',
                              {'id': 'INTEGER PRIMARY KEY', 'cover': 'TEXT', 'name': 'TEXT',
                               'author': 'TEXT', 'key': 'TEXT', 'chapter_name': 'TEXT',
                               'chapter_path_word': 'TEXT', 'book_hash': 'TEXT', 'type': 'INTEGER',
                               'status': 'INTEGER', 'process': 'INTEGER', 'start_time': 'TEXT', 'finish_time': 'TEXT'})

            # 创建漫画/图书收藏记录表
            # cover 漫画/图书封面
            # name 漫画/图书名称
            # author 漫画/图书作者
            # key 漫画/图书唯一key，漫画path_word，图书：book_id
            # book_hash 图书：book_hash，用于在收藏页下载
            # book_extension 图书文件类型
            # type 类型。1：漫画 2：图书
            # collection_time 收藏时间
            self.create_table('cmbok_collection_record',
                              {'id': 'INTEGER PRIMARY KEY', 'cover': 'TEXT', 'name': 'TEXT',
                               'author': 'TEXT', 'key': 'TEXT', 'book_hash': 'TEXT', 'book_extension': 'TEXT',
                               'type': 'INTEGER', 'collection_time': 'TEXT'})
            self.close()

    def create_table(self, table_name, columns):
        """创建表"""
        columns_with_types = ', '.join([f"{column} {col_type}" for column, col_type in columns.items()])
        sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_with_types});"
        self.cursor.execute(sql)
        self.connection.commit()

    def insert_data(self, table_name, data):
        """插入数据"""
        columns = ', '.join(data.keys())
        placeholders = ', '.join('?' * len(data))
        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders});"
        self.cursor.execute(sql, tuple(data.values()))
        self.connection.commit()
        return self.cursor.lastrowid  # 返回插入后的 ID

    def query_data(self, table_name, conditions=None, order_by=None, limit=None, offset=None):
        """查询数据，支持分页"""
        sql = f"SELECT * FROM {table_name}"
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
                sql += " WHERE " + " OR ".join(condition_clauses)  # 使用 OR 连接条件

        sql += ";"
        return self.cursor.execute(sql, params).fetchone()[0]  # 返回计数结果

    def update_data(self, table_name, data, conditions):
        """更新数据"""
        set_str = ', '.join([f"{key} = ?" for key in data.keys()])
        condition_str = ' AND '.join([f"{key} = ?" for key in conditions.keys()])
        sql = f"UPDATE {table_name} SET {set_str} WHERE {condition_str};"
        self.cursor.execute(sql, tuple(data.values()) + tuple(conditions.values()))
        self.connection.commit()

    def delete_data(self, table_name, conditions):
        """删除数据"""
        condition_str = ' AND '.join([f"{key} = ?" for key in conditions.keys()])
        sql = f"DELETE FROM {table_name} WHERE {condition_str};"
        self.cursor.execute(sql, tuple(conditions.values()))
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
