# coding:utf-8
"""跨设备传书后台服务（电脑端）。

与手机端对称的 P2P：本机既可作接收方（ThreadingHTTPServer + zeroconf 广播），
也可作发送方（zeroconf 发现 + requests 推送）。协议一致：
`POST /transfer/offer` -> 轮询 `GET /transfer/offer/{id}` -> `POST /transfer`
-> `POST /transfer/offer/{id}/done`。

鉴权 token-per-peer：每对设备配对时生成一个共享 token。配对折叠进接收方
「首次接受」：未配对对端发邀约时携带 X-Pair-Request，接收方接受后生成 token
随 accept 响应回传，发送方持久化到 app/config/peer_transfer.json。

线程模型：HTTP 服务跑在 daemon 线程（ThreadingHTTPServer 每请求一线程），
通过 pyqtSignal 把「收到邀约 / 对端变化」投递回 UI 线程；发送走 BookSendThread(QThread)。
"""
import json
import logging
import os
import platform
import secrets
import socket
import threading

import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceStateChange

from common.config import cfg

K_SERVICE_TYPE = '_cmbok._tcp.local.'
K_DEFAULT_PORT = 25601
K_OFFER_TIMEOUT = 120  # 秒
K_STATE_FILE = os.path.join('app', 'config', 'peer_transfer.json')

# 接收后视为「书」的扩展名（仅影响弹窗文案；电脑端一律存入接收目录）
BOOK_EXTS = {'epub', 'txt', 'pdf', 'mobi', 'azw', 'azw3'}


def _local_ip():
    """取本机局域网 IP（连 UDP 探测，不发数据）。取不到返回 None。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip if not ip.startswith('127.') else None
    except Exception:
        return None


def _platform_name():
    sysn = platform.system()
    if sysn == 'Windows':
        return 'windows'
    if sysn == 'Darwin':
        return 'macos'
    return sysn.lower() if sysn else 'other'


def _sanitize_filename(name):
    clean = name.replace('/', '_').replace('\\', '_').strip()
    return clean or 'file.bin'


def _ext_of(filename):
    dot = filename.rfind('.')
    return '' if dot <= 0 else filename[dot + 1:].lower()


def _title_of(filename):
    dot = filename.rfind('.')
    return filename if dot <= 0 else filename[:dot]


def _mime_of(ext):
    return {
        'epub': 'application/epub+zip',
        'pdf': 'application/pdf',
        'txt': 'text/plain',
        'mobi': 'application/x-mobipocket-ebook',
    }.get(ext, 'application/octet-stream')


class PeerDevice:
    """对端设备（与手机端字段一致）。"""

    def __init__(self, id, name, platform, token=None, host=None, port=None,
                 online=False):
        self.id = id
        self.name = name
        self.platform = platform
        self.token = token
        self.host = host
        self.port = port
        self.online = online

    @property
    def paired(self):
        return self.token is not None

    @property
    def address(self):
        if self.host and self.port:
            return f'{self.host}:{self.port}'
        return None

    def to_json(self):
        d = {'id': self.id, 'name': self.name, 'platform': self.platform}
        if self.token:
            d['token'] = self.token
        return d

    @staticmethod
    def from_json(j):
        return PeerDevice(
            id=j['id'], name=j.get('name', j['id']),
            platform=j.get('platform', 'unknown'), token=j.get('token'),
        )


class _OfferState:
    """邀约运行态。"""

    def __init__(self, offer_id, peer_id, peer_name, peer_platform, files,
                 kind, token=None, pairing=False):
        self.offer_id = offer_id
        self.peer_id = peer_id
        self.peer_name = peer_name
        self.peer_platform = peer_platform
        self.files = files  # [{name,size,mime,kind}]
        self.kind = kind
        self.status = 'pending'  # pending/accepted/rejected/done
        self.dir = None
        self.created_at = _now()
        self.pairing = pairing
        # 邀约创建时快照的鉴权 token。配对竞态下对端可能已重新配对拿到新
        # token，而 peers 里仍存旧 token，故鉴权以本邀约创建时的 token 为准。
        self.token = token

    def to_offer(self):
        """供 UI 使用的字典。"""
        return {
            'id': self.offer_id,
            'peerId': self.peer_id,
            'peerName': self.peer_name,
            'peerPlatform': self.peer_platform,
            'files': self.files,
            'kind': self.kind,
            'status': self.status,
            'dir': self.dir,
        }


_now = lambda: int(__import__('time').time())


class PeerTransferService(QObject):
    """传书后台服务（单例，UI 线程持有）。"""

    # 收到对端传书邀约（UI 弹「是否接收」窗）
    incomingOffer = pyqtSignal(object)
    # 对端列表变化
    peersChanged = pyqtSignal()
    # 发送进度 (offerId, sent, total, fileIndex, fileCount)
    sendProgress = pyqtSignal(str, int, int, int, int)
    # 发送结束 (offerId, ok)
    sendFinished = pyqtSignal(str, bool)
    # 接收模式因长时间无连接自动停止
    receiveAutoStopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peer_id = ''
        self.peer_name = ''
        self.peers = {}        # 已配对（持久化）+ 已发现（运行时补 host/port/online）
        self._pending = {}     # 配对进行中（待定，未持久化）
        self._offers = {}      # offer_id -> _OfferState
        self._lock = threading.Lock()

        self._server = None
        self._server_thread = None
        self._port = K_DEFAULT_PORT
        self._zeroconf = None
        self._zc_info = None
        self._browser = None

        # 接收空闲检测：开启接收后长时间无邀约则自动停（UI 线程 QTimer 周期检查）
        self._last_offer_ts = 0
        self._idleLimit = 600  # 秒
        self._idleTimer = QTimer(self)
        self._idleTimer.setInterval(30000)
        self._idleTimer.timeout.connect(self._checkIdle)

        self._load_state()

    # ===================== 状态持久化 =====================

    def _load_state(self):
        try:
            os.makedirs(os.path.dirname(K_STATE_FILE), exist_ok=True)
            if os.path.exists(K_STATE_FILE):
                with open(K_STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.peer_id = data.get('peerId') or ''
                self.peer_name = data.get('peerName') or ''
                for j in data.get('peers', []):
                    p = PeerDevice.from_json(j)
                    self.peers[p.id] = p
        except Exception as e:
            logging.info('加载传书状态失败: %s' % e)
        if not self.peer_id:
            self.peer_id = secrets.token_hex(16)
        if not self.peer_name:
            host = socket.gethostname() or 'Cmbok电脑'
            self.peer_name = '%s-%s' % (host, self.peer_id[:4])
        self._save_state()

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(K_STATE_FILE), exist_ok=True)
            data = {
                'peerId': self.peer_id,
                'peerName': self.peer_name,
                'peers': [p.to_json() for p in self.peers.values()],
            }
            with open(K_STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.info('保存传书状态失败: %s' % e)

    def info_body(self):
        return {'id': self.peer_id, 'name': self.peer_name,
                'platform': _platform_name(), 'ver': '1'}

    # ===================== 接收模式 / 发送模式 =====================

    def enter_receive_mode(self):
        """接收模式：起服务 + zeroconf 广播。电脑端无需前台保活。"""
        ok = self._start_server()
        if not ok:
            return False
        self._start_broadcast()
        self._last_offer_ts = _now()
        self._idleTimer.start()
        return True

    def exit_receive_mode(self):
        self._idleTimer.stop()
        self._stop_broadcast()
        self._stop_server()
        with self._lock:
            self._offers.clear()

    def _checkIdle(self):
        """UI 线程周期回调：接收开启后长时间无邀约则自动停止。"""
        if not self._server:
            return
        if _now() - self._last_offer_ts > self._idleLimit:
            logging.info('接收空闲超时，自动停止接收')
            self._idleTimer.stop()
            self.exit_receive_mode()
            self.receiveAutoStopped.emit()

    def enter_send_mode(self):
        """发送模式：发现对端。"""
        self._start_discovery()

    def exit_send_mode(self):
        self._stop_discovery()

    # ===================== HTTP 接收服务 =====================

    def _start_server(self):
        if self._server:
            return True
        port = K_DEFAULT_PORT
        srv = None
        for p in range(port, port + 6):
            try:
                srv = ThreadingHTTPServer(('', p), _TransferHandler)
                self._port = p
                break
            except OSError:
                continue
        if srv is None:
            try:
                srv = ThreadingHTTPServer(('', 0), _TransferHandler)
                self._port = srv.server_address[1]
            except OSError as e:
                logging.info('绑定传书服务失败: %s' % e)
                return False
        _TransferHandler.service = self
        srv.daemon_threads = True
        self._server = srv
        self._server_thread = threading.Thread(target=srv.serve_forever,
                                               daemon=True)
        self._server_thread.start()
        logging.info('传书接收服务已启动 @ 0.0.0.0:%d' % self._port)
        return True

    def _stop_server(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._server_thread = None

    # ---- 路由（由 _TransferHandler 调用）----

    def handle_offer(self, h):
        length = int(h.headers.get('Content-Length', 0) or 0)
        raw = h.rfile.read(length) if length else b''
        try:
            body = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            body = {}
        caller_id = h.headers.get('X-Peer-Id', '')
        auth = h.headers.get('Authorization', '')
        pair_req = h.headers.get('X-Pair-Request') == '1'
        if not caller_id:
            return h._json(400, {'ok': False, 'message': '缺少 X-Peer-Id'})

        peer_name = body.get('peerName', caller_id)
        peer_platform = body.get('peerPlatform', 'unknown')
        files = body.get('files', []) or []
        kind = body.get('kind', 'file')

        with self._lock:
            peer = self.peers.get(caller_id) or self._pending.get(caller_id)
            pairing = False
            pair_token = None
            if peer and peer.token and auth == 'Bearer %s' % peer.token:
                pass  # 已配对
            elif pair_req:
                pairing = True
                pair_token = secrets.token_hex(16)
                peer = PeerDevice(id=caller_id, name=peer_name,
                                  platform=peer_platform, token=pair_token)
                self._pending[caller_id] = peer
            else:
                return h._json(401, {'ok': False, 'message': '未授权，需重新配对'})

            # 记录对端可达地址
            try:
                peer.host = h.client_address[0]
            except Exception:
                pass
            peer.online = True

            offer_id = secrets.token_hex(6)
            st = _OfferState(offer_id, caller_id, peer_name, peer_platform,
                             files, kind, token=peer.token, pairing=pairing)
            self._offers[offer_id] = st
            self._last_offer_ts = _now()  # 有设备连接，刷新空闲计时

        # 通知 UI 弹窗（跨线程安全）
        self.incomingOffer.emit(st.to_offer())
        resp = {'offerId': offer_id, 'status': 'pending'}
        if pairing and pair_token:
            resp['pairToken'] = pair_token
        h._json(202, resp)

    def _check_offer_auth(self, h, st):
        caller_id = h.headers.get('X-Peer-Id', '')
        if caller_id != st.peer_id:
            return False
        if not st.token:
            return False
        auth = h.headers.get('Authorization', '')
        return auth == 'Bearer %s' % st.token

    def handle_poll(self, h, offer_id):
        with self._lock:
            st = self._offers.get(offer_id)
        if not st:
            return h._json(404, {'ok': False, 'message': '邀约不存在或已过期'})
        if not self._check_offer_auth(h, st):
            return h._json(401, {'ok': False, 'message': '未授权'})
        m = {'status': st.status}
        if st.status == 'accepted' and st.dir:
            m['dir'] = st.dir
        h._json(200, m)

    def handle_transfer(self, h):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(h.path).query)
        offer_id = (qs.get('offerId') or [''])[0]
        with self._lock:
            st = self._offers.get(offer_id)
        if not st:
            return h._json(404, {'ok': False, 'message': '邀约不存在'})
        if not self._check_offer_auth(h, st):
            return h._json(401, {'ok': False, 'message': '未授权'})
        if st.status != 'accepted':
            return h._json(409, {'ok': False, 'message': '对端尚未接受'})

        filename = h.headers.get('X-Filename', 'file.bin')
        try:
            from urllib.parse import unquote
            filename = unquote(filename)
        except Exception:
            pass
        d = st.dir or self._default_receive_dir()
        os.makedirs(d, exist_ok=True)
        safe = _sanitize_filename(filename)
        dest = os.path.join(d, safe)
        cl = int(h.headers.get('Content-Length', 0) or 0)
        try:
            with open(dest, 'wb') as f:
                remaining = cl
                while remaining > 0:
                    chunk = h.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except Exception as e:
            try:
                os.remove(dest)
            except Exception:
                pass
            return h._json(500, {'ok': False, 'message': '写入失败: %s' % e})
        h._json(200, {'ok': True, 'savedPath': dest})

    def handle_done(self, h, offer_id):
        with self._lock:
            st = self._offers.get(offer_id)
            if st:
                if not self._check_offer_auth(h, st):
                    return h._json(401, {'ok': False, 'message': '未授权'})
                st.status = 'done'
                self._offers.pop(offer_id, None)
        h._json(200, {'ok': True})

    def _default_receive_dir(self):
        return os.path.join(cfg.get(cfg.downloadFolder), 'transfer')

    # ---- 接收方：响应邀约（UI 线程调用）----

    def respond_to_offer(self, offer_id, accept, dir=None):
        with self._lock:
            st = self._offers.get(offer_id)
            if not st:
                return
            if accept:
                st.status = 'accepted'
                st.dir = dir or self._default_receive_dir()
                pending = self._pending.pop(st.peer_id, None)
                if pending:
                    self.peers[pending.id] = pending
            else:
                st.status = 'rejected'
                self._pending.pop(st.peer_id, None)
        if accept:
            self._save_state()

    # ===================== mDNS =====================

    def _start_broadcast(self):
        if self._zeroconf:
            return
        ip = _local_ip()
        addrs = [socket.inet_aton(ip)] if ip else None
        self._zc_info = ServiceInfo(
            type_=K_SERVICE_TYPE,
            name='%s.%s' % (self.peer_id, K_SERVICE_TYPE),
            port=self._port,
            properties={'id': self.peer_id, 'dev': self.peer_name,
                        'plat': _platform_name(), 'ver': '1'},
            addresses=addrs,
        )
        self._zeroconf = Zeroconf()
        try:
            self._zeroconf.register_service(self._zc_info)
            logging.info('已广播 %s @ :%d' % (self.peer_name, self._port))
        except Exception as e:
            logging.info('广播失败: %s' % e)

    def _stop_broadcast(self):
        if self._zeroconf:
            try:
                if self._zc_info:
                    self._zeroconf.unregister_service(self._zc_info)
            except Exception:
                pass
            try:
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None
            self._zc_info = None

    def _start_discovery(self):
        if self._browser:
            return
        if not self._zeroconf:
            self._zeroconf = Zeroconf()
        self._browser = ServiceBrowser(self._zeroconf, K_SERVICE_TYPE,
                                       handlers=[self._on_service_state_change])

    def _stop_discovery(self):
        # 浏览器随 zeroconf.close 终止；这里仅置空并标记离线
        self._browser = None
        for p in self.peers.values():
            p.online = False
        self.peersChanged.emit()

    def _on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name, timeout=2000)
            if not info:
                return
            props = info.properties or {}
            pid = (props.get(b'id') or b'').decode('utf-8', 'ignore') or name
            pname = (props.get(b'dev') or b'').decode('utf-8', 'ignore') or pid
            pplat = (props.get(b'plat') or b'').decode('utf-8', 'ignore') or 'unknown'
            addrs = info.parsed_addresses()
            host = addrs[0] if addrs else None
            with self._lock:
                peer = self.peers.get(pid)
                if not peer:
                    peer = PeerDevice(id=pid, name=pname, platform=pplat)
                    self.peers[pid] = peer
                peer.name = pname
                peer.host = host
                peer.port = info.port
                peer.online = True
            self.peersChanged.emit()
        elif state_change == ServiceStateChange.Removed:
            # name 形如 peerId._cmbok._tcp.
            pid = name.split('.')[0] if name else ''
            with self._lock:
                peer = self.peers.get(pid)
                if peer:
                    peer.online = False
            self.peersChanged.emit()

    def online_peers(self):
        return [p for p in self.peers.values() if p.online]

    # ===================== 发送 =====================

    def send_book(self, peer_id, file_paths):
        """启动一个发送线程（不阻塞 UI）。"""
        peer = self.peers.get(peer_id)
        if not peer:
            logging.info('未知对端: %s' % peer_id)
            self.sendFinished.emit('', False)
            return
        t = BookSendThread(self, peer, file_paths)
        t.sendProgress.connect(self.sendProgress)
        t.sendFinished.connect(self.sendFinished)
        # 持有线程引用防 GC（见 CLAUDE.md 线程模型约束）
        if not hasattr(self, '_send_threads'):
            self._send_threads = set()
        self._send_threads.add(t)
        t.finished.connect(lambda t=t: self._send_threads.discard(t))
        t.start()

    def _save_peer_token(self, peer_id, token):
        with self._lock:
            peer = self.peers.get(peer_id)
            if peer:
                peer.token = token
        self._save_state()


class _TransferHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。service 由 PeerTransferService 启动前注入为类属性。"""

    service = None  # type: PeerTransferService
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # 静默访问日志

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if path == '/info':
            return self._json(200, self.service.info_body())
        if path.startswith('/transfer/offer/'):
            offer_id = path[len('/transfer/offer/'):]
            return self.service.handle_poll(self, offer_id)
        self._json(404, {'ok': False, 'message': 'not found'})

    def do_POST(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if path == '/transfer/offer':
            return self.service.handle_offer(self)
        if path == '/transfer':
            return self.service.handle_transfer(self)
        if path.startswith('/transfer/offer/') and path.endswith('/done'):
            offer_id = path[len('/transfer/offer/'):-len('/done')]
            return self.service.handle_done(self, offer_id)
        self._json(404, {'ok': False, 'message': 'not found'})


class BookSendThread(QThread):
    """向对端推送文件（照抄 BookDownload 的线程范式）。"""

    sendProgress = pyqtSignal(str, int, int, int, int)  # offerId,sent,total,idx,count
    sendFinished = pyqtSignal(str, bool)

    def __init__(self, service, peer, file_paths):
        super().__init__()
        self.service = service
        self.peer = peer
        self.file_paths = file_paths

    def run(self):
        peer = self.peer
        if not peer.address:
            logging.info('对端不可达: %s' % peer.id)
            self.sendFinished.emit('', False)
            return
        base = 'http://%s' % peer.address
        try:
            # 构造文件清单
            files = []
            for p in self.file_paths:
                if not os.path.exists(p):
                    logging.info('文件不存在: %s' % p)
                    continue
                name = os.path.basename(p)
                size = os.path.getsize(p)
                ext = _ext_of(name)
                files.append({
                    'name': name, 'size': size,
                    'kind': 'book' if ext in BOOK_EXTS else 'file',
                    'mime': _mime_of(ext), 'path': p,
                })
            if not files:
                self.sendFinished.emit('', False)
                return
            kind = 'book' if all(f['kind'] == 'book' for f in files) else 'file'

            # 1) 发邀约（401 则清 token 重配一次）
            offer_id, pair_token = self._post_offer(base, peer, files, kind)
            if not offer_id:
                self.sendFinished.emit('', False)
                return
            if pair_token and pair_token != peer.token:
                peer.token = pair_token
                self.service._save_peer_token(peer.id, pair_token)

            auth = {'X-Peer-Id': self.service.peer_id,
                    'Authorization': 'Bearer %s' % peer.token}

            # 2) 轮询等待接受
            status = 'pending'
            deadline = _now() + K_OFFER_TIMEOUT
            while _now() < deadline:
                import time
                time.sleep(1.5)
                try:
                    r = requests.get('%s/transfer/offer/%s' % (base, offer_id),
                                     headers=auth, timeout=10)
                    s = r.json().get('status')
                    if s == 'accepted':
                        status = 'accepted'
                        break
                    if s in ('rejected', 'expired'):
                        status = 'rejected'
                        break
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        status = 'rejected'
                        break
                except Exception as e:
                    logging.info('轮询异常: %s' % e)
            if status != 'accepted':
                logging.info('对端未接受或超时')
                self.sendFinished.emit(offer_id, False)
                return

            # 3) 逐个传文件（流式 + 进度）
            for i, f in enumerate(files):
                ok = self._upload_file(base, offer_id, auth, f, i, len(files))
                if not ok:
                    self.sendFinished.emit(offer_id, False)
                    return

            # 4) 完成
            try:
                requests.post('%s/transfer/offer/%s/done' % (base, offer_id),
                              headers=auth, timeout=10)
            except Exception:
                pass
            logging.info('传书完成: %d 个文件 -> %s' % (len(files), peer.name))
            self.sendFinished.emit(offer_id, True)
        except Exception as e:
            logging.info('传书异常: %s' % e)
            self.sendFinished.emit('', False)

    def _post_offer(self, base, peer, files, kind):
        for attempt in range(2):
            pairing = peer.token is None
            headers = {'X-Peer-Id': self.service.peer_id,
                       'Content-Type': 'application/json'}
            if not pairing:
                headers['Authorization'] = 'Bearer %s' % peer.token
            else:
                headers['X-Pair-Request'] = '1'
            body = {
                'files': [{k: v for k, v in f.items() if k != 'path'}
                          for f in files],
                'kind': kind,
                'peerName': self.service.peer_name,
                'peerPlatform': _platform_name(),
            }
            try:
                r = requests.post('%s/transfer/offer' % base, json=body,
                                  headers=headers, timeout=15)
                data = r.json()
                return data.get('offerId'), data.get('pairToken')
            except requests.HTTPError as e:
                if (e.response is not None and e.response.status_code == 401
                        and peer.token and attempt == 0):
                    logging.info('配对失效，重新配对')
                    peer.token = None
                    continue
                logging.info('发邀约失败: %s' % e)
                return None, None
            except Exception as e:
                logging.info('发邀约异常: %s' % e)
                return None, None
        return None, None

    def _upload_file(self, base, offer_id, auth, f, idx, count):
        path = f['path']
        total = f['size']
        headers = dict(auth)
        headers.update({
            'Content-Type': 'application/octet-stream',
            # 不设 Content-Length：生成器 body 无 __len__，requests 会加
            # Transfer-Encoding: chunked；若两者共存，http.client 不做 chunk
            # 分帧却仍发 chunked 头，接收端按 chunked 解析原始字节必失败(10053)。
            # 文件大小仍经 X-Filesize 传递，接收端不依赖 Content-Length。
            'X-Filename': _quote(f['name']),
            'X-Filesize': str(total),
            'X-Mime': f.get('mime', 'application/octet-stream'),
            'X-Kind': f['kind'],
        })
        try:
            with open(path, 'rb') as fp:
                sent = [0]

                def gen():
                    while True:
                        chunk = fp.read(65536)
                        if not chunk:
                            break
                        sent[0] += len(chunk)
                        self.sendProgress.emit(offer_id, sent[0], total,
                                               idx, count)
                        yield chunk

                r = requests.post(
                    '%s/transfer?offerId=%s' % (base, offer_id),
                    data=gen(), headers=headers, timeout=600)
                return r.status_code == 200
        except Exception as e:
            logging.info('上传失败: %s' % e)
            return False


def _quote(s):
    from urllib.parse import quote
    return quote(s)


# 模块级单例，UI 直接 import 使用
peerTransfer = PeerTransferService()
