# -*- coding: utf-8 -*-
"""漫画去白边：裁掉 epub 内图片内容边界外的空白，并注入 CSS 保证显示时不放大。

- 纯裁剪（PIL crop），1:1 保留内容像素；默认不放大（zoom=100）。
- 可选「图片放大」：裁剪后按百分比用 LANCZOS 重采样放大像素，等比夹在设备屏幕内
  （宽≤屏宽、高≤屏高，不裁切），保证各阅读器显示尺寸/清晰度一致（zoom>100 生效）。
- epub 重打包前给含图页面注入 max-width:100% 的 img 样式，使图片按原始像素显示
  （超屏缩小、窄屏居中留白）；预放大的图片同样适用。
"""
import logging
import os
import shutil
import tempfile
import traceback
import zipfile

from PIL import Image

IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
# 小于该尺寸的图视为图标/logo，跳过不裁
_MIN_CONTENT_SIZE = 100
# 注入的图片样式：不放大（按原始像素，超屏才缩小）
_INJECT_STYLE = (
    '<style type="text/css">'
    'img{max-width:100%!important;height:auto!important;width:auto!important;}'
    '</style>'
)


def trim_image_whitespace(img, threshold=245, padding=0):
    """裁掉图片四周白边，纯 crop 不缩放。

    返回裁剪后的 Image；若无明显白边或无内容则返回 None（调用方跳过，不重写文件）。
    threshold: 亮度 >= 此值视为白边（0-255）。
    padding: 裁剪后四周保留的像素边距。
    """
    w, h = img.size
    if w < _MIN_CONTENT_SIZE or h < _MIN_CONTENT_SIZE:
        return None

    has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
    if has_alpha:
        rgba = img.convert('RGBA')
        alpha = rgba.split()[-1]
        a_min, _ = alpha.getextrema()
        if a_min > 0:
            # 实际无透明像素，退回亮度判断白边
            content = rgba.convert('L').point(lambda p: 255 if p < threshold else 0)
        else:
            content = alpha.point(lambda p: 255 if p > 0 else 0)
    else:
        content = img.convert('L').point(lambda p: 255 if p < threshold else 0)

    bbox = content.getbbox()
    if bbox is None:
        return None  # 无内容
    left, top, right, bottom = bbox
    # 加 padding 并 clamp 到原图边界
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(w, right + padding)
    bottom = min(h, bottom + padding)
    # 无白边（内容即整图）则跳过
    if left <= 0 and top <= 0 and right >= w and bottom >= h:
        return None
    return img.crop((left, top, right, bottom))


def resize_for_zoom(img, zoom, dev_w, dev_h):
    """按放大百分比重采样图片，等比夹在设备屏幕内（宽≤屏宽、高≤屏高，不裁切）。

    zoom 为百分比（100=原尺寸）。用 LANCZOS 高质量重采样；zoom≤100、未给设备
    分辨率、或图片已达屏幕上限（放大后仍会超出屏幕）时返回原图（不复制），调用方
    据此判断是否需要重写文件。调色板/灰度等模式先转 RGB/RGBA 保证重采样质量。
    """
    if zoom <= 100 or dev_w <= 0 or dev_h <= 0:
        return img
    w, h = img.size
    if w <= 0 or h <= 0:
        return img
    factor = zoom / 100.0
    scale = min(factor, dev_w / w, dev_h / h)
    if scale <= 1.0:
        return img  # 图片已达屏幕上限，无法在不超屏前提下放大
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    # 调色板/灰度等模式先转 RGB/RGBA，保证 LANCZOS 高质量重采样
    if img.mode == 'RGBA':
        src = img
    elif img.mode == 'LA':
        src = img.convert('RGBA')
    elif img.mode == 'P':
        src = img.convert('RGBA') if 'transparency' in img.info else img.convert('RGB')
    elif img.mode in ('L', 'RGB'):
        src = img
    else:
        src = img.convert('RGB')
    return src.resize((new_w, new_h), Image.LANCZOS)


def _trim_one_image(img_path, threshold, padding, zoom=100, dev_w=0, dev_h=0):
    """就地裁剪单张图片（覆盖原文件）。无白边且未放大则不动。"""
    img = Image.open(img_path)
    fmt = img.format  # 保留原格式（WEBP/PNG/JPEG...），存临时文件时显式指定
    if getattr(img, 'is_animated', False):
        # 多帧 gif 跳过
        img.close()
        return
    trimmed = trim_image_whitespace(img, threshold, padding)
    base = trimmed if trimmed is not None else img
    # 放大重采样（夹在设备屏幕内，zoom<=100 不放大）
    resized = resize_for_zoom(base, zoom, dev_w, dev_h) if zoom and zoom > 100 else base
    try:
        if resized is base and trimmed is None:
            return  # 既未裁剪也未放大
        tmp = img_path + '.trim_tmp'
        out = resized
        # JPEG 不支持透明通道，存前转 RGB
        if fmt == 'JPEG' and out.mode in ('RGBA', 'LA', 'P'):
            out = out.convert('RGB')
        out.save(tmp, format=fmt)
        os.replace(tmp, img_path)
    finally:
        if resized is not base:
            resized.close()
        if trimmed is not None:
            trimmed.close()
        img.close()


def _detect_fxl(src_dir):
    """检测是否固定布局（FXL）epub。"""
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith('.opf'):
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as fp:
                        text = fp.read()
                    if 'fixed-layout' in text or 'pre-paginated' in text:
                        return True
                except Exception:
                    pass
    return False


def _inject_no_stretch_css(src_dir):
    """给含图片的 xhtml/html 注入不放大样式（覆盖原 width:100% 撑满行为）。"""
    for root, _, files in os.walk(src_dir):
        for f in files:
            if not f.lower().endswith(('.xhtml', '.html', '.htm')):
                continue
            full = os.path.join(root, f)
            try:
                with open(full, 'r', encoding='utf-8') as fp:
                    text = fp.read()
                if '<img' not in text.lower():
                    continue
                if _INJECT_STYLE in text:
                    continue
                low = text.lower()
                if '</head>' in low:
                    idx = low.index('</head>')
                    text = text[:idx] + _INJECT_STYLE + text[idx:]
                elif '<head>' in low:
                    idx = low.index('<head>') + len('<head>')
                    text = text[:idx] + _INJECT_STYLE + text[idx:]
                else:
                    text = _INJECT_STYLE + text
                with open(full, 'w', encoding='utf-8') as fp:
                    fp.write(text)
            except Exception:
                logging.info(f'[去白边] 注入CSS失败 {full}: {traceback.format_exc()}')


def _repack_epub(src_dir, out_path):
    """重新打包 epub：mimetype 首条且 STORE 不压缩，其余 DEFLATE。"""
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        mimetype_path = os.path.join(src_dir, 'mimetype')
        if os.path.isfile(mimetype_path):
            zout.write(mimetype_path, 'mimetype', zipfile.ZIP_STORED)
        for root, _, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src_dir).replace(os.sep, '/')
                if rel == 'mimetype':
                    continue
                zout.write(full, rel, zipfile.ZIP_DEFLATED)


def strip_calibre_cover(epub_path, out_path):
    """去除 calibre mobi->epub 注入的封面页，避免转回 mobi 时封面（首页/末页）重复。

    calibre 的 mobi->epub 会把封面抽成 titlepage.xhtml（guide 里 type="cover" 引用）+
    calibre_cover.jpg（<meta name="cover"> 指向）。直接转回 mobi 时 calibre 既嵌入 EXTH
    封面又保留 titlepage 内容页，且原封面图常在内容流里也留一份，导致封面在阅读器里重复
    显示（用户看到的「第一页/最后一页多复制一页」）。

    - calibre_cover 与某张内容图同字节（原 mobi 无 EXTH 封面、封面即内容页的常见情况）：
      删 titlepage + calibre_cover + cover 元数据 + guide，转回 mobi 后 coverOffset=None，
      与原书一致。
    - calibre_cover 是独立封面（原 mobi 有 EXTH 封面）：仅删 titlepage，保留 cover 元数据，
      转回 mobi 后封面只作为 EXTH 封面显示一次。
    无 titlepage/封面时为 no-op，直接拷贝。返回是否改动过。
    """
    import hashlib
    import re as _re

    tmp_dir = tempfile.mkdtemp(prefix='stripcover_')
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin:
            zin.extractall(tmp_dir)

        # 定位 opf
        opf_path = None
        for root, _, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith('.opf'):
                    opf_path = os.path.join(root, f)
                    break
            if opf_path:
                break
        if not opf_path:
            _copy_zip(epub_path, out_path)
            return False
        with open(opf_path, 'r', encoding='utf-8') as fp:
            text = fp.read()
        opf_dir = os.path.dirname(opf_path)

        # titlepage href：guide 里 type="cover" 的 reference
        titlepage_href = None
        m = _re.search(r'<reference\b[^>]*\btype="cover"[^>]*/>', text, _re.I)
        if m:
            mh = _re.search(r'\bhref="([^"]+)"', m.group(0))
            if mh:
                titlepage_href = mh.group(1)
        if not titlepage_href:
            # 退而求其次：找带 calibre:cover 标记的 xhtml
            for root, _, files in os.walk(tmp_dir):
                for f in files:
                    if f.lower().endswith(('.xhtml', '.html', '.htm')):
                        full = os.path.join(root, f)
                        try:
                            with open(full, 'r', encoding='utf-8') as fp:
                                if 'calibre:cover' in fp.read().lower():
                                    titlepage_href = os.path.relpath(full, opf_dir).replace(os.sep, '/')
                                    break
                        except Exception:
                            pass
                if titlepage_href:
                    break
        if not titlepage_href:
            _copy_zip(epub_path, out_path)
            return False

        # titlepage item id
        titlepage_id = _find_item_id(text, titlepage_href)

        # cover 图片：<meta name="cover" content="ID"> -> manifest item
        cover_img_id = None
        cover_img_href = None
        mc = _re.search(r'<meta\b[^>]*\bname="cover"[^>]*/>', text, _re.I)
        if mc:
            mv = _re.search(r'\bcontent="([^"]+)"', mc.group(0))
            if mv:
                cover_img_id = mv.group(1)
        if cover_img_id:
            mi = _re.search(r'<item\b[^>]*\bid="%s"[^>]*/>' % _re.escape(cover_img_id), text, _re.I)
            if mi:
                mh = _re.search(r'\bhref="([^"]+)"', mi.group(0))
                if mh:
                    cover_img_href = mh.group(1)

        # 判断 calibre_cover 是否与某张内容图同字节（封面即内容页）
        is_dup = False
        if cover_img_href:
            cover_fp = os.path.normpath(os.path.join(opf_dir, cover_img_href))
            if os.path.isfile(cover_fp):
                with open(cover_fp, 'rb') as fp:
                    cover_hash = hashlib.md5(fp.read()).hexdigest()
                for root, _, files in os.walk(tmp_dir):
                    for f in files:
                        if not f.lower().endswith(IMG_EXTS):
                            continue
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, opf_dir).replace(os.sep, '/')
                        if rel == cover_img_href:
                            continue
                        try:
                            with open(full, 'rb') as fp:
                                if hashlib.md5(fp.read()).hexdigest() == cover_hash:
                                    is_dup = True
                                    break
                        except Exception:
                            continue
                    if is_dup:
                        break

        changed = False
        # 删 titlepage 的 spine itemref 与 manifest item（始终）
        if titlepage_id:
            text, n1 = _re.subn(r'<itemref\b[^>]*\bidref="%s"[^>]*/>\s*' % _re.escape(titlepage_id), '', text, flags=_re.I)
            text, n2 = _re.subn(r'<item\b[^>]*\bid="%s"[^>]*/>\s*' % _re.escape(titlepage_id), '', text, flags=_re.I)
            if n1 or n2:
                changed = True
        # 删 guide 的 cover reference（titlepage 已删，引用悬空）
        text, n = _re.subn(r'<reference\b[^>]*\btype="cover"[^>]*/>\s*', '', text, flags=_re.I)
        if n:
            changed = True
        text, n = _re.subn(r'<guide>\s*</guide>\s*', '', text, flags=_re.I)
        if n:
            changed = True
        # 封面即内容页：再删 calibre_cover + cover 元数据，让转回 mobi 后无 EXTH 封面
        if is_dup and cover_img_id:
            text, n = _re.subn(r'<item\b[^>]*\bid="%s"[^>]*/>\s*' % _re.escape(cover_img_id), '', text, flags=_re.I)
            if n:
                changed = True
            text, n = _re.subn(r'<meta\b[^>]*\bname="cover"[^>]*/>\s*', '', text, flags=_re.I)
            if n:
                changed = True

        # 删文件
        for href in [titlepage_href] + ([cover_img_href] if is_dup and cover_img_href else []):
            if href:
                fp = os.path.normpath(os.path.join(opf_dir, href))
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        changed = True
                    except Exception:
                        pass

        if not changed:
            _copy_zip(epub_path, out_path)
            return False
        with open(opf_path, 'w', encoding='utf-8') as fp:
            fp.write(text)
        _repack_epub(tmp_dir, out_path)
        return True
    except Exception:
        logging.info(f'[去白边] 剥离calibre封面失败: {traceback.format_exc()}')
        _copy_zip(epub_path, out_path)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _find_item_id(opf_text, href):
    """从 manifest 里按 href 反查 item id（属性顺序不固定）。"""
    import re as _re
    for m in _re.finditer(r'<item\b[^>]*/>', opf_text, _re.I):
        tag = m.group(0)
        if ('href="%s"' % href) in tag or ("href='%s'" % href) in tag:
            mi = _re.search(r'\bid="([^"]+)"', tag)
            if mi:
                return mi.group(1)
    return None


def _copy_zip(src, dst):
    """拷贝 epub 文件（无改动时用）。"""
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    shutil.copyfile(src, dst)


def trim_epub_margins(epub_path, out_path, threshold=245, padding=0, zoom=100, dev_w=0, dev_h=0, progress_cb=None):
    """处理整个 epub：解压 -> 裁每张图白边 -> (可选)放大重采样 -> 注入不放大CSS -> 重打包。

    progress_cb(current, total, name) 用于上报进度。
    zoom 为放大百分比（>100 生效），dev_w/dev_h 为设备分辨率（用于夹在屏幕内）；
    默认 100/0/0 = 仅裁剪不放大，向后兼容。
    返回 (ok, msg)：ok=False 时 msg 为错误信息；ok=True 且检测到 FXL 时 msg='FXL'。
    """
    tmp_dir = tempfile.mkdtemp(prefix='trim_epub_')
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin:
            zin.extractall(tmp_dir)

        img_files = []
        for root, _, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith(IMG_EXTS):
                    img_files.append(os.path.join(root, f))
        total = len(img_files)

        for i, img_path in enumerate(img_files):
            try:
                _trim_one_image(img_path, threshold, padding, zoom, dev_w, dev_h)
            except Exception:
                logging.info(f'[去白边] 图片处理失败 {img_path}: {traceback.format_exc()}')
            if progress_cb:
                progress_cb(i + 1, total, os.path.basename(img_path))

        _inject_no_stretch_css(tmp_dir)
        _repack_epub(tmp_dir, out_path)

        is_fxl = _detect_fxl(tmp_dir)
        return True, ('FXL' if is_fxl else '')
    except Exception as e:
        logging.info(f'[去白边] epub处理失败: {traceback.format_exc()}')
        return False, str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_content_image_names(epub_path):
    """返回 epub 内所有内容图（跳过小图标/logo）的 zip 条目名列表，按 zip 顺序。

    仅读图片 header 判尺寸（不加载像素），用于预览翻页前先拿到全部图片名/总数。
    """
    names = []
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin:
            for name in zin.namelist():
                if not name.lower().endswith(IMG_EXTS):
                    continue
                try:
                    with zin.open(name) as f:
                        img = Image.open(f)
                        if img.width >= _MIN_CONTENT_SIZE and img.height >= _MIN_CONTENT_SIZE:
                            names.append(name)
                except Exception:
                    continue
    except Exception:
        logging.info(f'[去白边] 取图片名列表失败: {traceback.format_exc()}')
    return names


def get_image_by_name(epub_path, name):
    """从 epub 读取指定图片（加载像素，脱离 zip 流），返回 PIL Image 或 None。"""
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin:
            with zin.open(name) as f:
                img = Image.open(f)
                img.load()  # 读入内存，脱离 zip 流
                return img
    except Exception:
        logging.info(f'[去白边] 取图片失败 {name}: {traceback.format_exc()}')
    return None


def get_first_content_image(epub_path):
    """从 epub 取第一张内容图（跳过小图标/logo），用于预览。返回 PIL Image 或 None。"""
    names = get_content_image_names(epub_path)
    return get_image_by_name(epub_path, names[0]) if names else None
