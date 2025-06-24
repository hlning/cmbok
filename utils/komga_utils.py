import logging
import os
import subprocess
import traceback

import psutil

from common.config import cfg


# 启动komga
def start_komga():
    logging.info('启动komga...')
    try:
        # 检测端口是否被占用
        is_run = komga_is_run()
        if not is_run:
            komga_dir = cfg.get(cfg.komgaFolder)
            java_bin = "java.exe" if os.name == "nt" else "java"
            jre_path = os.path.join(komga_dir, "jre", "bin", java_bin)
            jar_path = os.path.join(komga_dir, "komga-1.21.2.jar")

            process = subprocess.Popen(
                [jre_path, "-jar", jar_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,  # 可选：捕获输出
                stderr=subprocess.PIPE,  # 可选：捕获错误
                start_new_session=True,  # 防止子进程随主进程退出
            )
            logging.info(f'kmoga启动成功，PID: {process.pid}')
    except Exception:
        logging.info(traceback.format_exc())
        logging.info('kmoga启动失败')


# 停止komga
def stop_komga():
    # 是否保留后台
    if cfg.get(cfg.komgaBackgrounder):
        return False
    port = 25600
    """检查端口占用并杀掉对应进程"""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    logging.info(f"端口 {port} 被进程 {proc.pid} ({proc.name()}) 占用，正在终止...")
                    proc.kill()
                    logging.info(f"进程 {proc.pid} 已终止")
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    logging.info(f"端口 {port} 未被占用")
    return False


# komga是否在运行
def komga_is_run():
    port = 25600
    """检查端口占用并杀掉对应进程"""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    logging.info(f"端口 {port} 被进程 {proc.pid} ({proc.name()}) 占用")
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    logging.info(f"端口 {port} 未被占用")
    return False
