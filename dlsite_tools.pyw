# -*- coding: utf-8 -*-
"""
DLsite 小工具 - GUI 版 v2.4
三大功能：
  [封面图标] 抓封面→生成 ICO→设文件夹图标
  [重命名]    [RJ号][社团名]游戏名
  [一键处理]  改名 + 封面 一步到位

v2.4 审查修复：
  - Bug: _unique_path 自冲突导致重做模式追加 _1 后缀（ignore_path 豁免自身）
  - Bug: build_name_with_config 作品名(work)被全局括号误包，改为永不加括号
  - New: 图标背景模式（取色填充/白色/透明），合并到格式设置对话框
  - New: FormatConfig 新增 bg_mode 字段，PRESETS 同步更新
  - New: make_ico 新增 bg_mode 参数，icon/combined 两处调用点透传
  - Style: self._undo_btn 预初始化为 None

v2.0 重构要点：
  - TabState 统一管理各 tab 运行/暂停状态及按钮
  - _build_standard_tab 工厂方法消除 3 个 tab 构建重复
  - 提取 _truncate / _build_info_arr / _unique_path 工具函数消除重复代码块
  - 删除死代码 build_new_name / _run_processor / _rename_safe
  - 修复 safe 变量重复获取
  - 错误处理合并为 dict 查找映射，消除 if-elif 链

v2.1 审查修复：
  - Bug: combined tab 缺少格式标签，格式对话框无法更新其显示
  - Bug: combined tab 格式标签无「...」设置按钮
  - Bug: on_start 守卫逻辑错误（or→and 导致运行中会无声返回）
  - Clean: 删除未使用的 BRACKET_OPTIONS / SEP_OPTIONS / to_dict / from_dict / _restore_btn
  - Clean: icon_process_all 的 worker 函数移除冗余 total 参数

v2.2 审查修复：
  - Bug: icon_process_all 双重 progress/status（worker 内和循环体各调一次）
  - Bug: enter_running() 调用时机不一致（icon/combined 在 worker 线程调 tk 控件）
  - Bug: 版本号三处不一致
  - Clean: worker 函数移除多余的 nonlocal stats 和无用的 return True

v2.3 审查修复：
  - Bug: 版本号仍有两处停在 v2.1（主窗口/启动窗口），统一到 v2.3
  - Bug: icon_process_restore 的 enter_running 仍在 worker 线程调 tk（漏网之鱼）
  - Style: rename_on_undo 和 rename_process_all 之间补空行（PEP 8）
"""
import io, os, sys, math, time, re, struct, shutil, threading, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from PIL import Image
from pyquery import PyQuery as pq

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, filedialog, messagebox
except ImportError:
    tk = None

# ====== Config ======
SLEEP_INTERVAL = 3
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
PROXY = os.environ.get('DLISTE_PROXY', '').strip()
PROXIES = {'http': PROXY, 'https': PROXY} if PROXY else None
# ====================

# ======================== DLsite 通用工具函数 ========================

def get_domain(rjcode):
    return 'pro' if rjcode[:2].upper() in ('VJ',) else 'maniax'

def get_img_path(rjcode):
    return 'professional' if rjcode[:2].upper() in ('VJ',) else 'doujin'

def make_prefix(rjcode):
    prefix_type = rjcode[:2].upper()
    digits = rjcode[2:]
    digit_len = len(digits)
    prefix_num = math.ceil(int(digits) / 1000) * 1000
    return '{}{}'.format(prefix_type, str(prefix_num).zfill(digit_len))

def parse_workno(name):
    """从名称中提取 RJ/VJ/BJ 编号（有无方括号均可）"""
    m = re.search(r'\[(RJ|VJ|BJ)(\d{6,8})\]', name, re.IGNORECASE)
    if m:
        return (m.group(1) + m.group(2)).upper()
    m = re.search(
        r'(?:^|[\s_\-\.\(\)])((RJ|VJ|BJ)(\d{6,8}))(?:$|[\s_\-\.\(\)\[\]])',
        name, re.IGNORECASE)
    if m:
        return (m.group(2) + m.group(3)).upper()
    m = re.search(r'(RJ|VJ|BJ)(\d{6,8})', name, re.IGNORECASE)
    if m:
        return (m.group(1) + m.group(2)).upper()
    return None

# ---------- 封面抓取 ----------

def construct_cover_url(rjcode, ext='.jpg'):
    pre = make_prefix(rjcode)
    return 'https://img.dlsite.jp/modpub/images2/work/{}/{}/{}_img_main{}'.format(
        get_img_path(rjcode), pre, rjcode, ext)

def fetch_og_image(rjcode):
    url = 'https://www.dlsite.com/{}/work/=/product_id/{}.html'.format(
        get_domain(rjcode), rjcode)
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, proxies=PROXIES)
        if r.status_code == 200:
            text = r.text
            if '您所在的国家・区域无法购买此作品' in text or \
               'あなたのお住まいの国・地域ではこの作品を購入できません' in text:
                return None, 'region_blocked'
            if 'お探しの作品は見つかりませんでした' in text or \
               '作品が見つかりません' in text:
                return None, 'not_found'
            doc = pq(text)
            for el in doc('meta').items():
                prop = el.attr('property')
                if prop and 'og:image' in prop:
                    og_url = el.attr('content')
                    if og_url:
                        return og_url, None
        elif r.status_code == 404:
            return None, 'not_found'
    except Exception:
        pass
    return None, None

def fetch_api_image(rjcode):
    api_url = 'https://www.dlsite.com/{}/api/=/product.json?workno={}'.format(
        get_domain(rjcode), rjcode)
    try:
        r = requests.get(api_url, timeout=15, headers=HEADERS, proxies=PROXIES)
        if r.status_code == 200:
            data = r.json()
            if data and 'image_main' in data[0] and data[0]['image_main']:
                return 'https:' + data[0]['image_main']['url']
    except Exception:
        pass
    return None

def fetch_parts_url(rjcode):
    url = 'https://www.dlsite.com/{}/work/=/product_id/{}.html'.format(
        get_domain(rjcode), rjcode)
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, proxies=PROXIES)
        if r.status_code != 200:
            return None
        doc = pq(r.text)
        for img in doc('a[href*="parts"] img, img[src*="parts"]').items():
            src = img.attr('src')
            if src:
                return src if src.startswith('http') else 'https:' + src
    except Exception:
        pass
    return None

def get_best_image_url(rjcode):
    url = fetch_api_image(rjcode)
    if url:
        return url, 'API'
    for ext in ['.webp', '.jpg']:
        guessed = construct_cover_url(rjcode, ext)
        try:
            r = requests.head(guessed, timeout=10, headers=HEADERS, proxies=PROXIES)
            if r.status_code == 200:
                return guessed, '主封面'
        except Exception:
            pass
    og_url, error = fetch_og_image(rjcode)
    if error:
        return None, error
    if og_url:
        return og_url, '网页'
    parts_url = fetch_parts_url(rjcode)
    if parts_url:
        return parts_url, '大图'
    return None, None

def download_image(url):
    r = requests.get(url, timeout=30, headers=HEADERS, proxies=PROXIES)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))

# ---------- ICO 生成 ----------

def make_ico(image, icon_path, bg_mode='auto'):
    # 删除旧文件，避免被 Explorer 锁定导致 Permission denied
    if os.path.exists(icon_path):
        try:
            subprocess.run('attrib -h -s -r "{}"'.format(icon_path),
                           shell=True, capture_output=True)
            os.remove(icon_path)
        except Exception:
            pass
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    x, y = image.size
    sizes = [16, 24, 32, 48, 64, 96, 128, 256]
    if bg_mode == 'auto':
        img_rgb = image.convert('RGB')
        edge_pixels = []
        for px in range(0, x, 5):
            edge_pixels.append(img_rgb.getpixel((px, 0)))
            edge_pixels.append(img_rgb.getpixel((px, y - 1)))
        for py in range(0, y, 5):
            edge_pixels.append(img_rgb.getpixel((0, py)))
            edge_pixels.append(img_rgb.getpixel((x - 1, py)))
        avg_color = tuple(sum(c) // len(c) for c in zip(*edge_pixels))
        bg_rgba = avg_color + (255,)
    elif bg_mode == 'white':
        bg_rgba = (255, 255, 255, 255)
    else:  # transparent
        bg_rgba = (0, 0, 0, 0)
    base = Image.new('RGBA', (256, 256), bg_rgba)
    ratio = min(256 / x, 256 / y)
    new_size = (int(x * ratio), int(y * ratio))
    resized = image.resize(new_size, Image.LANCZOS)
    base.paste(resized, ((256 - new_size[0]) // 2, (256 - new_size[1]) // 2), resized)
    png_data_list = []
    for s in sizes:
        img = base.resize((s, s), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        png_data_list.append(buf.getvalue())
    count = len(png_data_list)
    with open(icon_path, 'wb') as f:
        f.write(struct.pack('<HHH', 0, 1, count))
        data_start = 6 + 16 * count
        current_offset = data_start
        for i, png_data in enumerate(png_data_list):
            s = sizes[i]
            w_byte = 0 if s >= 256 else s
            h_byte = 0 if s >= 256 else s
            f.write(struct.pack('<BBBBHHII',
                w_byte, h_byte, 0, 0, 1, 32, len(png_data), current_offset))
            current_offset += len(png_data)
        for png_data in png_data_list:
            f.write(png_data)

def set_folder_icon(folder_path, icon_name):
    ini_path = os.path.join(folder_path, "desktop.ini")
    # 清理旧 desktop.ini（.ico 由 make_ico 负责清理）
    if os.path.exists(ini_path):
        try:
            subprocess.run('attrib -h -s -r "{}"'.format(ini_path),
                           shell=True, capture_output=True)
            os.remove(ini_path)
        except Exception:
            pass
    ini_content = (
        "[.ShellClassInfo]\r\n"
        'IconResource="{}",0\r\n'.format(icon_name) +
        "[ViewState]\r\n"
        "Mode=\r\n"
        "Vid=\r\n"
        "FolderType=StorageProviderGeneric\r\n"
    )
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write(ini_content)
    subprocess.run('attrib +h +s "{}"'.format(ini_path), shell=True, capture_output=True)
    subprocess.run('attrib +h "{}"'.format(os.path.join(folder_path, icon_name)),
                   shell=True, capture_output=True)
    subprocess.run('attrib +s "{}"'.format(folder_path), shell=True, capture_output=True)

def restore_folder_icon(folder_path):
    result = {'ico': 0, 'ini': False, 'attr': False}
    for fname in os.listdir(folder_path):
        if fname.startswith('@folder-icon-') and fname.endswith('.ico'):
            try:
                os.remove(os.path.join(folder_path, fname))
                result['ico'] += 1
            except Exception:
                pass
    ini_path = os.path.join(folder_path, 'desktop.ini')
    if os.path.exists(ini_path):
        try:
            subprocess.run('attrib -h -s -r "{}"'.format(ini_path),
                           shell=True, capture_output=True)
            with open(ini_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            new_content = re.sub(r'(?m)^\s*IconResource\s*=.*\n?', '', content)
            new_content = re.sub(r'(?m)^\s*IconFile\s*=.*\n?', '', new_content)
            new_content = re.sub(r'(?m)^\s*IconIndex\s*=.*\n?', '', new_content)
            new_content = re.sub(r'(?m)^\s*(Mode|Vid|FolderType)\s*=.*\n?', '', new_content)
            new_content = new_content.strip()
            if not new_content or new_content in (
                    '[.ShellClassInfo]', '[ViewState]',
                    '[.ShellClassInfo][ViewState]'):
                os.remove(ini_path)
            else:
                with open(ini_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            result['ini'] = True
        except Exception:
            pass
    try:
        subprocess.run('attrib -s "{}"'.format(folder_path), shell=True, capture_output=True)
        result['attr'] = True
    except Exception:
        pass
    return result

def refresh_icon_cache():
    subprocess.run('taskkill /f /im explorer.exe >nul 2>nul', shell=True)
    time.sleep(1)
    subprocess.run('start explorer.exe', shell=True)

# ---------- 作品信息抓取（重命名用） ----------

def fetch_product_info_api(rjcode):
    api_url = 'https://www.dlsite.com/{}/api/=/product.json?workno={}'.format(
        get_domain(rjcode), rjcode)
    try:
        r = requests.get(api_url, timeout=15, headers=HEADERS, proxies=PROXIES)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                work_name = item.get('work_name', '') or ''
                maker_name = item.get('maker_name', '') or ''
                if not work_name:
                    return None
                return {
                    'work_name': work_name.strip(),
                    'maker_name': maker_name.strip(),
                    'regist_date': (item.get('regist_date', '') or '').strip()[:10],
                    'age_category': (item.get('age_category_string', '') or '').strip(),
                    'work_type': (item.get('work_type_string', '') or '').strip(),
                }
    except Exception:
        pass
    return None

def fetch_product_info_page(rjcode):
    """页面解析，降级方案"""
    url = 'https://www.dlsite.com/{}/work/=/product_id/{}.html'.format(
        get_domain(rjcode), rjcode)
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, proxies=PROXIES)
        if r.status_code == 200:
            text = r.text
            if '您所在的国家・区域无法购买此作品' in text or \
               'あなたのお住まいの国・地域ではこの作品を購入できません' in text:
                return None, None, 'region_blocked'
            if 'お探しの作品は見つかりませんでした' in text or \
               '作品が見つかりません' in text:
                return None, None, 'not_found'
            if 'ただいまメンテナンス中です' in text:
                return None, None, 'maintenance'
            doc = pq(text)
            work_name = ''
            h1 = doc('h1#work_name')
            if h1:
                work_name = h1.text().strip()
            if not work_name:
                span = doc('span#work_name')
                if span:
                    work_name = span.text().strip()
            if not work_name:
                for el in doc('meta').items():
                    prop = el.attr('property')
                    if prop and 'og:title' in prop:
                        wt = el.attr('content')
                        if wt:
                            work_name = wt.strip()
                            break
            maker_name = ''
            maker_link = doc('a[href*="maker_name"]')
            if maker_link:
                maker_name = maker_link.text().strip()
            if not maker_name:
                for th in doc('th').items():
                    if 'サークル' in th.text() or 'ブランド' in th.text() or \
                       'サークル名' in th.text() or 'circle' in th.text().lower():
                        td = th.next('td')
                        if td:
                            maker_name = td.text().strip()
                            break
            if not maker_name:
                maker_el = doc('.maker_name')
                if maker_el:
                    maker_name = maker_el.text().strip()
            if not maker_name:
                for tr in doc('tr').items():
                    th_text = tr.find('th').text() if tr.find('th') else ''
                    if 'サークル' in th_text:
                        td = tr.find('td')
                        if td:
                            maker_name = td.text().strip()
                            break
            if work_name:
                return work_name.strip(), maker_name.strip(), None
            else:
                return None, None, 'parse_failed'
        elif r.status_code == 404:
            return None, None, 'not_found'
    except Exception:
        pass
    return None, None, None

def fetch_product_info(rjcode):
    """返回 (info_dict, error)。info_dict 包含 work_name/maker_name/…/source"""
    api_data = fetch_product_info_api(rjcode)
    if api_data:
        api_data['source'] = 'API'
        return api_data, None
    w, m, error = fetch_product_info_page(rjcode)
    if error:
        return None, error
    if w:
        return {'work_name': w, 'maker_name': m, 'regist_date': '',
                'age_category': '', 'work_type': '', 'source': 'page'}, None
    return None, None

# ---------- 重命名工具函数 ----------

def sanitize_filename(name):
    replacements = {
        '\\': '＼', '/': '／', ':': '：', '*': '＊',
        '?': '？', '"': '＂', '<': '＜', '>': '＞',
        '|': '｜'
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    name = name.strip('. ')
    reserved = {'CON', 'PRN', 'AUX', 'NUL',
                 'COM1', 'COM2', 'COM3', 'COM4',
                 'LPT1', 'LPT2', 'LPT3', 'LPT4'}
    base = os.path.splitext(name)[0].upper()
    if base in reserved:
        name = '_' + name
    return name

def _truncate(name, length=40):
    """截断长名称用于日志显示"""
    return name if len(name) <= length else name[:length] + '...'

# ====== 格式配置 ======

class FormatConfig:
    FIELD_LABELS = {'rj': 'RJ号', 'maker': '社团名', 'work': '作品名',
                    'date': '发售日期', 'age': '年龄限制', 'type': '作品形式'}
    FIELD_ORDER = ['rj', 'maker', 'work', 'date', 'age', 'type']
    BRACKET_DISPLAY = {'[]': '[]  方括号', '()': '()  圆括号',
                       '【】': '【】  书名号', '': '(无括号)'}
    SEP_DISPLAY = {'': '(无分隔)', ' ': '空格',
                   '_': '_  下划线', '-': '-  横线'}
    BRACKET_REVERSE = {v: k for k, v in BRACKET_DISPLAY.items()}
    SEP_REVERSE = {v: k for k, v in SEP_DISPLAY.items()}
    BG_MODE_DISPLAY = {'auto': '取色填充', 'white': '白色', 'transparent': '透明'}
    BG_MODE_REVERSE = {v: k for k, v in BG_MODE_DISPLAY.items()}
    PRESETS = {
        '默认': {'fields': ['rj', 'maker', 'work'], 'bracket': '[]', 'sep': '',
                 'bg_mode': 'auto'},
        '带日期': {'fields': ['rj', 'maker', 'work', 'date'], 'bracket': '[]', 'sep': '',
                  'bg_mode': 'auto'},
    }

    def __init__(self):
        self.fields = ['rj', 'maker', 'work']
        self.bracket = '[]'
        self.sep = ''
        self.bg_mode = 'auto'

    # to_dict / from_dict（预留：需要持久化时添加）

    def preview(self):
        vals = {'rj': 'RJ012345', 'maker': '社团名', 'work': '作品名',
                'date': '2026-06-01', 'age': 'R18', 'type': 'RPG'}
        return build_name_with_config('RJ012345', vals, self)

def build_name_with_config(rjcode, info, config):
    parts = []
    for f in config.fields:
        val = info.get(f, '')
        if not val:
            continue
        # 作品名（work）永远不加括号，其他字段按配置处理
        if config.bracket and f != 'work':
            b = config.bracket
            if len(b) == 2:
                parts.append(b[0] + val + b[1])
            else:
                parts.append(val)
        else:
            parts.append(val)
    return sanitize_filename(config.sep.join(parts))

def is_already_renamed(folder_name, rjcode):
    patterns = [
        r'^\[' + re.escape(rjcode) + r'\]',
        r'^\(' + re.escape(rjcode) + r'\)',
        r'^【' + re.escape(rjcode) + r'】',
        r'^' + re.escape(rjcode) + r'[\s_]',
        r'^' + re.escape(rjcode) + r'$',
    ]
    return any(re.match(p, folder_name) for p in patterns)

# ---------- 重构：抽取的公用工具 ----------

def _build_info_arr(rjcode, info_dict):
    """把 info_dict 标准化为 build_name_with_config 需要的格式"""
    return {
        'rj': rjcode,
        'maker': info_dict.get('maker_name', ''),
        'work': info_dict.get('work_name', ''),
        'date': (info_dict.get('regist_date', '') or '')[:10],
        'age': info_dict.get('age_category', ''),
        'type': info_dict.get('work_type', ''),
    }

def _unique_path(base_dir, desired_name, ignore_path=None):
    """如果 desired_name 已存在，加后缀避免覆盖；ignore_path 指定的路径不算冲突"""
    new_name = desired_name
    new_path = os.path.join(base_dir, new_name)
    ignore = os.path.normcase(os.path.abspath(ignore_path)) if ignore_path else None
    suffix = 1
    while os.path.exists(new_path) and \
            os.path.normcase(os.path.abspath(new_path)) != ignore:
        new_name = '{}_{}'.format(desired_name, suffix)
        new_path = os.path.join(base_dir, new_name)
        suffix += 1
    return new_name, new_path



# ======================== 启动信息窗口 ========================

def show_startup_window(parent):
    """打开启动信息窗口，固定布局确保所有内容可见。"""
    import webbrowser

    def _open_url(url):
        webbrowser.open(url)

    win = tk.Toplevel(parent)
    win.title("DLsite 小工具")
    win.geometry("560x580")
    win.minsize(500, 420)
    win.resizable(True, True)
    win.transient(parent)
    win.grab_set()

    outer = ttk.Frame(win)
    outer.pack(fill=tk.BOTH, expand=True)
    inner = ttk.Frame(outer, padding=(12, 10))
    inner.pack(fill=tk.BOTH, expand=True)

    ttk.Label(inner, text="DLsite 小工具 v2.4",
              font=('Microsoft YaHei UI', 14, 'bold')).pack(pady=(0, 8))

    # ---- 免责声明 ----
    f1 = tk.LabelFrame(inner, text="⚠️ 免责声明", padx=8, pady=6, font=('Microsoft YaHei UI', 9, 'bold'))
    f1.pack(fill=tk.X, pady=3)
    tk.Label(f1, text="本工具由 AI 辅助生成，仅供个人学习参考。使用者应自行评估并承担全部风险。",
             fg="#cc0000", font=('Microsoft YaHei UI', 9, 'bold'),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f1, text="使用前请充分测试，确保理解其工作原理及潜在影响。",
             fg="#cc0000", font=('Microsoft YaHei UI', 9, 'bold'),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f1, text="作者不对任何直接或间接损失承担责任，使用即代表接受。",
             fg="#cc0000", font=('Microsoft YaHei UI', 9, 'bold'),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f1, text="本工具完全免费，任何收费行为均为诈骗。",
             fg="#ff6600", font=('Microsoft YaHei UI', 10, 'bold'),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)

    # ---- 特别致谢 ----
    f2 = tk.LabelFrame(inner, text="🙏 特别致谢", padx=8, pady=6, font=('Microsoft YaHei UI', 9, 'bold'))
    f2.pack(fill=tk.X, pady=3)
    tk.Label(f2, text="封面抓取逻辑参考了以下开源项目：",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    lbl_link = tk.Label(f2, text="yodhcn/dlsite-doujin-renamer",
                        font=('Microsoft YaHei UI', 9, 'underline'),
                        fg="#0066cc", cursor="hand2",
                        wraplength=520, anchor=tk.W, justify=tk.LEFT)
    lbl_link.pack(anchor=tk.W, pady=2)
    lbl_link.bind('<Button-1>', lambda e: _open_url("https://github.com/yodhcn/dlsite-doujin-renamer"))
    lbl_link.bind('<Enter>', lambda e: lbl_link.config(fg='#004499'))
    lbl_link.bind('<Leave>', lambda e: lbl_link.config(fg='#0066cc'))
    tk.Label(f2, text="（功能更全、社区活跃，推荐了解）。",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f2, text="", font=('Microsoft YaHei UI', 9)).pack(anchor=tk.W, pady=0)
    tk.Label(f2, text="本工具为独立开发，与原项目无任何关系。不要打扰原项目。",
             fg="#666666", font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)

    # ---- 使用提示 ----
    f3 = tk.LabelFrame(inner, text="💡 使用提示", padx=8, pady=6, font=('Microsoft YaHei UI', 9, 'bold'))
    f3.pack(fill=tk.X, pady=3)
    tk.Label(f3, text="• 代理：DLISTE_PROXY=http://127.0.0.1:7890  |  间隔 3 秒防限流",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f3, text="• 识别 RJ/VJ/BJ 编号，有无方括号均可",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f3, text="【★ 一键处理】两步到位  【封面图标】单独处理  【重命名】单独改名",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
    tk.Label(f3, text="• 包裹模式：为原文件夹包一层格式化父文件夹，原文件夹内容不动（同盘零开销）",
             font=('Microsoft YaHei UI', 9),
             wraplength=520, anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W, pady=2)

    # ---- 按钮 ----
    btn_frame = ttk.Frame(inner)
    btn_frame.pack(fill=tk.X, pady=(10, 4))
    ttk.Button(btn_frame, text="  我知道了，开始使用  ",
               command=win.destroy).pack(pady=4)

    win.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_y() + (parent.winfo_height() - win.winfo_height()) // 2
    win.geometry('+{}+{}'.format(x, y))

# ======================== TabState：统一管理各 tab 运行状态 ========================

class TabState:
    """替代原先 6 个独立布尔变量 + 手动按钮管理"""
    __slots__ = ('running', 'paused', 'start_btn', 'pause_btn',
                 'progress', 'listbox', 'mode_var')

    def __init__(self, start_btn, pause_btn, progress, listbox, mode_var):
        self.running = False
        self.paused = False
        self.start_btn = start_btn
        self.pause_btn = pause_btn
        self.progress = progress
        self.listbox = listbox
        self.mode_var = mode_var

    def enter_running(self):
        self.running = True
        self.paused = False
        self.start_btn.config(text='⏳ 处理中...', state=tk.DISABLED)
        self.pause_btn.config(text='⏸ 暂停', state=tk.NORMAL)

    def exit_running(self, start_text='▶ 开始'):
        self.running = False
        self.paused = False
        self.start_btn.config(text=start_text, state=tk.NORMAL)
        self.pause_btn.config(text='⏸ 暂停', state=tk.DISABLED)

    def toggle_pause(self, log_func):
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.config(text='▶ 继续')
            log_func('⏸ 已暂停', 'orange')
        else:
            self.pause_btn.config(text='⏸ 暂停')
            log_func('▶ 继续处理...', 'lime')

    def is_rebuild(self):
        return self.mode_var.get() == 'rebuild'


# ======================== 主 GUI ========================

class DlsiteToolsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DLsite 小工具 v2.4")
        self.root.geometry("960x720")
        self.root.minsize(680, 560)

        style = ttk.Style()
        style.theme_use('vista' if 'vista' in style.theme_names() else 'winnative')

        # ------ 全局状态 ------
        self.target_dir = os.path.abspath(os.path.dirname(__file__))
        self.folders = []           # [(rjcode, folder_path, folder_name), ...]
        self.rename_history = []    # [(old_path, new_path, rjcode, folder_name), ...]
        self.safe_mode_var = tk.BooleanVar(value=True)
        self.format_config = FormatConfig()
        self._rename_fmt_label = None
        self._combined_fmt_label = None
        self._undo_btn = None
        # TabState 实例在 build_tab 后赋值
        self.icon_state = None
        self.rename_state = None
        self.combined_state = None

        # ------ 顶部：目录选择（共享）------
        frame_top = ttk.Frame(root, padding=8)
        frame_top.pack(fill=tk.X)

        ttk.Label(frame_top, text="目标目录：").pack(side=tk.LEFT)
        self.dir_var = tk.StringVar(value=self.target_dir)
        entry_dir = ttk.Entry(frame_top, textvariable=self.dir_var, width=60)
        entry_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        ttk.Button(frame_top, text="选择目录",
                   command=self.on_browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(frame_top, text="重新扫描",
                   command=self.on_scan).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(frame_top, text="包裹模式",
            variable=self.safe_mode_var).pack(side=tk.LEFT, padx=(15, 2))

        # ------ 状态栏（共享）------
        self.status_bar = ttk.Label(root, text="就绪", relief=tk.SUNKEN,
                                    anchor=tk.W, padding=(5, 2))

        # ------ Notebook ------
        self.notebook = ttk.Notebook(root, padding=(4, 0))
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 三个 Tab 用统一工厂方法构建
        self.tab_combined = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.tab_combined, text="  ★ 一键处理  ")
        self.combined_state = self._build_standard_tab(
            self.tab_combined, 'combined',
            extra_widgets=self._combined_extra,
            start_text='▶ 开始 !',
            skip_hint="↳ 普通模式跳过条件：已重命名 + 已有图标，两者均已完成才跳过")

        self.tab_icon = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.tab_icon, text="  封面图标  ")
        self.icon_state = self._build_standard_tab(
            self.tab_icon, 'icon',
            extra_buttons=[('恢复默认图标', 'restore'), ('刷新图标缓存', 'refresh')])

        self.tab_rename = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.tab_rename, text="  重命名  ")
        self.rename_state = self._build_standard_tab(
            self.tab_rename, 'rename',
            extra_buttons=[('↩ 撤销选中', 'undo')],
            show_fmt=True)

        # ------ 日志（共享）------
        log_frame = ttk.Frame(root, padding=(8, 0, 8, 8))
        log_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(log_frame, text="运行日志：").pack(anchor=tk.W)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=8, font=('Consolas', 9), wrap=tk.WORD,
            bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.status_bar.pack(fill=tk.X)

        self.root.after(500, self.show_startup)
        self.root.after(300, self.on_scan)

    # ==================== UI 工厂方法 ====================

    def _build_standard_tab(self, tab, name, extra_widgets=None,
                            extra_buttons=None, show_fmt=False,
                            skip_hint=None, start_text='▶ 开始处理'):
        """
        统一构建 tab 布局，消除三个 tab 的重复 UI 代码。
        返回 TabState 实例。
        """
        mode_var = tk.StringVar(value="normal")
        frame_mode = ttk.Frame(tab)
        frame_mode.pack(fill=tk.X)

        ttk.Radiobutton(frame_mode, text="普通模式（跳过已完成）",
            variable=mode_var, value="normal").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(frame_mode, text="重做模式（忽略已有，全部重做）",
            variable=mode_var, value="rebuild").pack(side=tk.LEFT)

        # 格式/额外部件区域（由各 tab 定制）
        fmt_label = None
        if show_fmt:
            ttk.Label(frame_mode, text="   格式：").pack(side=tk.LEFT, padx=(12, 2))
            fmt_label = ttk.Label(frame_mode, text="[RJ号][社团名]作品名",
                foreground='#0066cc', font=('Microsoft YaHei UI', 9, 'bold'))
            fmt_label.pack(side=tk.LEFT)
            ttk.Button(frame_mode, text="...", width=3,
                       command=self.show_format_dialog).pack(side=tk.LEFT, padx=3)
        elif extra_widgets:
            _extra_fmt = extra_widgets(frame_mode)
            if _extra_fmt:
                fmt_label = _extra_fmt

        if skip_hint:
            hint = ttk.Label(tab, text=skip_hint,
                foreground='#666666', font=('Microsoft YaHei UI', 8))
            hint.pack(anchor=tk.W, pady=(0, 2))

        # 列表
        list_frame = ttk.Frame(tab)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        listbox = tk.Listbox(list_frame, font=('Microsoft YaHei UI', 9),
                             selectmode=tk.EXTENDED)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                  command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 进度条
        progress = ttk.Progressbar(tab, mode='determinate')
        progress.pack(fill=tk.X)

        # 按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=(4, 0))

        start_btn = ttk.Button(btn_frame, text=start_text)
        pause_btn = ttk.Button(btn_frame, text="⏸ 暂停", state=tk.DISABLED)

        start_btn.pack(side=tk.LEFT, padx=2)
        pause_btn.pack(side=tk.LEFT, padx=2)

        # 额外按钮
        if extra_buttons:
            for text, action in extra_buttons:
                btn = ttk.Button(btn_frame, text=text)
                btn.pack(side=tk.LEFT, padx=2)
                if action == 'restore':
                    btn.configure(command=self.icon_on_restore)
                elif action == 'refresh':
                    btn.configure(command=self.icon_on_refresh)
                elif action == 'undo':
                    btn.configure(command=self.rename_on_undo)
                    self._undo_btn = btn

        state = TabState(start_btn, pause_btn, progress, listbox, mode_var)

        # 绑定开始按钮
        actions = {
            'icon': self.icon_on_start,
            'rename': self.rename_on_start,
            'combined': self.combined_on_start,
        }
        start_btn.configure(command=actions[name])

        # 绑定暂停按钮
        pausers = {
            'icon': self.icon_on_pause,
            'rename': self.rename_on_pause,
            'combined': self.combined_on_pause,
        }
        pause_btn.configure(command=pausers[name])

        # 保存 fmt_label 引用用于更新
        if name == 'rename' and fmt_label:
            self._rename_fmt_label = fmt_label
        if name == 'combined' and fmt_label:
            self._combined_fmt_label = fmt_label

        return state

    def _combined_extra(self, frame):
        """一键处理独有的额外部件：流程标签 + 格式标签 + 设置按钮，返回 fmt_label"""
        ttk.Label(frame, text="  流程：").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Label(frame, text="改名+封面→一步到位",
            foreground='#cc0066', font=('Microsoft YaHei UI', 9, 'bold')).pack(
                side=tk.LEFT)
        ttk.Label(frame, text="   格式：").pack(side=tk.LEFT, padx=(12, 2))
        fmt_label = ttk.Label(frame,
            text=self.format_config.preview(),
            foreground='#0066cc', font=('Microsoft YaHei UI', 9, 'bold'))
        fmt_label.pack(side=tk.LEFT)
        ttk.Button(frame, text="...", width=3,
                   command=self.show_format_dialog).pack(side=tk.LEFT, padx=3)
        return fmt_label

    # ==================== 工具方法 ====================

    def log(self, msg, color=None):
        self.log_text.insert(tk.END, msg + '\n')
        if color:
            start = self.log_text.index('end-1l linestart')
            end = self.log_text.index('end-1l lineend')
            self.log_text.tag_add(color, start, end)
            self.log_text.tag_config(color, foreground=color)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def status(self, msg):
        self.status_bar.config(text=msg)
        self.root.update_idletasks()

    def progress_set(self, progress_bar, value, max_val):
        if max_val > 0:
            progress_bar['maximum'] = max_val
        progress_bar['value'] = value
        self.root.update_idletasks()

    def update_format_labels(self):
        preview = self.format_config.preview()
        try:
            self._rename_fmt_label.config(text=preview)
        except Exception:
            pass
        try:
            self._combined_fmt_label.config(text=preview)
        except Exception:
            pass

    # ==================== 聚焦对话框 ====================

    def show_format_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("重命名格式设置")
        win.geometry("520x430")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # 预设
        pf = ttk.Frame(frm)
        pf.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(pf, text="预设：").pack(side=tk.LEFT)
        preset_var = tk.StringVar(value="")
        ttk.Combobox(pf, textvariable=preset_var,
            values=[""] + list(FormatConfig.PRESETS.keys()),
            width=12, state="readonly").pack(side=tk.LEFT, padx=5)

        # 字段
        ff = ttk.LabelFrame(frm,
            text="字段（☑ 勾选的会按从左到右顺序拼成文件名）", padding=5)
        ff.pack(fill=tk.X, pady=2)
        field_vars = {}
        rows = [ttk.Frame(ff), ttk.Frame(ff)]
        for r in rows:
            r.pack(fill=tk.X, pady=2)
        for idx, fk in enumerate(FormatConfig.FIELD_ORDER):
            v = tk.BooleanVar(value=fk in self.format_config.fields)
            field_vars[fk] = v
            ttk.Checkbutton(rows[0 if idx < 3 else 1],
                text=FormatConfig.FIELD_LABELS[fk], variable=v).pack(
                    side=tk.LEFT, padx=6)

        # 括号 + 分隔
        bsf = ttk.Frame(frm)
        bsf.pack(fill=tk.X, pady=(8, 2))
        ttk.Label(bsf, text="括号：").pack(side=tk.LEFT)
        bracket_var = tk.StringVar(
            value=FormatConfig.BRACKET_DISPLAY.get(self.format_config.bracket, '[]'))
        ttk.Combobox(bsf, textvariable=bracket_var,
            values=list(FormatConfig.BRACKET_DISPLAY.values()),
            width=14, state="readonly").pack(side=tk.LEFT, padx=5)
        ttk.Label(bsf, text="  分隔：").pack(side=tk.LEFT, padx=(20, 0))
        sep_var = tk.StringVar(
            value=FormatConfig.SEP_DISPLAY.get(self.format_config.sep, ''))
        ttk.Combobox(bsf, textvariable=sep_var,
            values=list(FormatConfig.SEP_DISPLAY.values()),
            width=14, state="readonly").pack(side=tk.LEFT, padx=5)

        # 图标背景模式
        bgf = ttk.Frame(frm)
        bgf.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(bgf, text="图标背景：").pack(side=tk.LEFT)
        bg_mode_var = tk.StringVar(
            value=FormatConfig.BG_MODE_DISPLAY.get(
                self.format_config.bg_mode, '取色填充'))
        ttk.Combobox(bgf, textvariable=bg_mode_var,
            values=list(FormatConfig.BG_MODE_DISPLAY.values()),
            width=14, state="readonly").pack(side=tk.LEFT, padx=5)
        ttk.Label(bgf, text="（ICO 图标空白区域填充色）",
            foreground='#888888',
            font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT, padx=(8, 0))

        # 预览
        prev_f = ttk.LabelFrame(frm, text="预览", padding=5)
        prev_f.pack(fill=tk.X, pady=(8, 8))
        preview_label = ttk.Label(prev_f, text=self.format_config.preview(),
            foreground='#cc0066', font=('Microsoft YaHei UI', 11, 'bold'))
        preview_label.pack()

        def refresh_preview(*args):
            fields = [fk for fk in FormatConfig.FIELD_ORDER
                      if field_vars[fk].get()]
            if not fields:
                preview_label.config(text="(至少选一个字段)")
                return
            tmp = FormatConfig()
            tmp.fields = fields
            tmp.bracket = FormatConfig.BRACKET_REVERSE.get(bracket_var.get(), '')
            tmp.sep = FormatConfig.SEP_REVERSE.get(sep_var.get(), '')
            preview_label.config(text=tmp.preview())

        for v in field_vars.values():
            v.trace_add('write', refresh_preview)
        bracket_var.trace_add('write', refresh_preview)
        sep_var.trace_add('write', refresh_preview)

        def apply_preset(*args):
            name = preset_var.get()
            if name in FormatConfig.PRESETS:
                p = FormatConfig.PRESETS[name]
                bracket_var.set(
                    FormatConfig.BRACKET_DISPLAY.get(p['bracket'], ''))
                sep_var.set(FormatConfig.SEP_DISPLAY.get(p['sep'], ''))
                bg_val = FormatConfig.BG_MODE_DISPLAY.get(
                    p.get('bg_mode', 'auto'), '取色填充')
                bg_mode_var.set(bg_val)
                for fk in FormatConfig.FIELD_ORDER:
                    field_vars[fk].set(fk in p['fields'])
                preset_var.set('')
        preset_var.trace_add('write', apply_preset)

        def on_ok():
            self.format_config.fields = [
                fk for fk in FormatConfig.FIELD_ORDER if field_vars[fk].get()]
            if not self.format_config.fields:
                self.format_config.fields = ['rj']
            self.format_config.bracket = \
                FormatConfig.BRACKET_REVERSE.get(bracket_var.get(), '')
            self.format_config.sep = \
                FormatConfig.SEP_REVERSE.get(sep_var.get(), '')
            self.format_config.bg_mode = \
                FormatConfig.BG_MODE_REVERSE.get(bg_mode_var.get(), 'auto')
            self.update_format_labels()
            self.log("格式已更新：" + self.format_config.preview(), 'cyan')
            win.destroy()

        btn_frm = ttk.Frame(frm)
        btn_frm.pack()
        ttk.Button(btn_frm, text="确定", command=on_ok).pack(
            side=tk.LEFT, padx=10)
        ttk.Button(btn_frm, text="取消", command=win.destroy).pack(
            side=tk.LEFT, padx=10)

        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry('+{}+{}'.format(x, y))

    def show_startup(self):
        show_startup_window(self.root)

    # ==================== 扫描与浏览 ====================

    def on_browse(self):
        d = filedialog.askdirectory(title="选择游戏目录")
        if d:
            self.dir_var.set(d)
            self.on_scan()

    def on_scan(self):
        target = self.dir_var.get()
        if not os.path.isdir(target):
            self.log("错误：目录不存在", 'red')
            return
        self.target_dir = target

        for state in (self.icon_state, self.rename_state, self.combined_state):
            if state:
                state.listbox.delete(0, tk.END)

        self.folders = []
        count = 0
        for item in sorted(os.listdir(target)):
            item_path = os.path.join(target, item)
            if not os.path.isdir(item_path):
                continue
            rjcode = parse_workno(item)
            if not rjcode:
                continue
            self.folders.append((rjcode, item_path, item))
            short = _truncate(item, 55)

            # 封面图标状态
            has_ico = os.path.exists(os.path.join(
                item_path, '@folder-icon-{}.ico'.format(rjcode)))
            has_ini = os.path.exists(os.path.join(item_path, 'desktop.ini'))
            icon_st = '🔄' if (has_ico and has_ini) else '  '
            self.icon_state.listbox.insert(tk.END,
                '{} [{}] {}'.format(icon_st, rjcode, short))

            # 重命名状态
            rn_st = '🔄' if is_already_renamed(item, rjcode) else '  '
            self.rename_state.listbox.insert(tk.END,
                '{} [{}] {}'.format(rn_st, rjcode, short))

            # 一键处理状态（合并）
            both = (has_ico and has_ini) and is_already_renamed(item, rjcode)
            cmb_st = '🔄' if both else '  '
            self.combined_state.listbox.insert(tk.END,
                '{} [{}] {}'.format(cmb_st, rjcode, short))
            count += 1

        for state in (self.icon_state, self.rename_state, self.combined_state):
            self.progress_set(state.progress, 0, count)
        self.status('扫描完成，发现 {} 个游戏文件夹'.format(count))
        self.log('扫描 [{}]：找到 {} 个游戏文件夹'.format(target, count), 'cyan')

    # ====================== 封面图标逻辑 ======================

    def icon_on_start(self):
        if self.icon_state.running:
            return self.log('任务正在进行中，请等待完成', 'orange')
        if not self.folders:
            return self.log('请先扫描目录', 'orange')
        self.icon_state.enter_running()
        threading.Thread(target=self.icon_process_all, daemon=True).start()

    def icon_on_pause(self):
        self.icon_state.toggle_pause(self.log)

    def icon_on_restore(self):
        if self.icon_state.running:
            return self.log('当前有任务进行中，请等待完成', 'orange')
        if not self.folders:
            return self.log('请先扫描目录', 'orange')
        sel = self.icon_state.listbox.curselection()
        target_list = [self.folders[i] for i in sel] if sel else self.folders
        self.log('确认恢复默认图标（{} 个）'.format(len(target_list)), 'yellow')
        self.icon_state.enter_running()
        threading.Thread(target=self.icon_process_restore,
                         args=(target_list,), daemon=True).start()

    def icon_on_refresh(self):
        self.log('正在刷新图标缓存...', 'cyan')
        refresh_icon_cache()
        self.log('图标缓存已刷新', 'lime')

    def icon_process_all(self):
        rebuild = self.icon_state.is_rebuild()
        total = len(self.folders)
        stats = {'success': 0, 'skip': 0, 'fail': 0, 'fail_detail': []}

        self.log('=' * 60)
        self.log('  [封面图标] 开始处理')
        self.log('  模式：{}  目录：{}'.format(
            '重做模式' if rebuild else '普通模式', self.target_dir))
        self.log('=' * 60)
        self.status('图标处理中... 0/{}'.format(total))
        self.progress_set(self.icon_state.progress, 0, total)

        def worker(i, item):
            rjcode, folder_path, folder_name = item
            icon_name = '@folder-icon-{}.ico'.format(rjcode)
            icon_path = os.path.join(folder_path, icon_name)
            has_icon = os.path.exists(icon_path)
            has_ini = os.path.exists(os.path.join(folder_path, 'desktop.ini'))

            if not rebuild and has_icon and has_ini:
                self.icon_state.listbox.itemconfig(i - 1, fg='gray')
                self.log('[{}/{}] [{}] {} → 跳过（已有图标）'.format(
                    i, total, rjcode, _truncate(folder_name)), 'gray')
                stats['skip'] += 1
                return

            self.log('[{}/{}] [{}] {}'.format(
                i, total, rjcode, _truncate(folder_name)))
            try:
                self.log('  >> 获取封面...', 'cyan')
                img_url, source = get_best_image_url(rjcode)
                if not img_url:
                    err_map = {'region_blocked': ('区域限制', 'orange'),
                               'not_found': ('已下架或不存在', 'red')}
                    msg, clr = err_map.get(source, ('找不到封面', 'red'))
                    self.log('  ❌ ' + msg, clr)
                    stats['fail_detail'].append(
                        '{}: {}'.format(rjcode, msg))
                    stats['fail'] += 1
                    self.icon_state.listbox.itemconfig(i - 1, fg='red')
                    return

                self.log('  >> 来源：{}'.format(source))
                self.log('  >> 下载中...', 'cyan')
                image = download_image(img_url)
                self.log('  >> 尺寸：{}×{}'.format(image.width, image.height))
                self.log('  >> 生成多尺寸图标...', 'cyan')
                make_ico(image, icon_path, self.format_config.bg_mode)
                kb = os.path.getsize(icon_path) // 1024
                self.log('  >> ICO：{}KB'.format(kb))
                self.log('  >> 设置文件夹图标...', 'cyan')
                set_folder_icon(folder_path, icon_name)
                stats['success'] += 1
                self.log('  ✅ 完成！', 'lime')
                self.icon_state.listbox.itemconfig(i - 1, fg='green')
            except requests.exceptions.Timeout:
                self.log('  ❌ 超时', 'red')
                stats['fail'] += 1
                stats['fail_detail'].append('{}: 超时'.format(rjcode))
                self.icon_state.listbox.itemconfig(i - 1, fg='red')
            except Exception as e:
                err_msg = str(e)[:100]
                self.log('  ❌ {}'.format(err_msg), 'red')
                stats['fail'] += 1
                stats['fail_detail'].append('{}: {}'.format(rjcode, err_msg))
                self.icon_state.listbox.itemconfig(i - 1, fg='red')

        for i, item in enumerate(self.folders, 1):
            while self.icon_state.paused:
                time.sleep(0.5)
            worker(i, item)
            self.progress_set(self.icon_state.progress, i, len(self.folders))
            self.status('图标处理中... {}/{}'.format(i, len(self.folders)))
            if i < len(self.folders):
                time.sleep(SLEEP_INTERVAL)
        self.icon_state.exit_running()

        self.log('=' * 60)
        self.log('📊 [封面图标] 完成！新增：{} 跳过：{} 失败：{} 共{}'.format(
            stats['success'], stats['skip'], stats['fail'], total))
        if stats['fail_detail']:
            self.log('  ❌ 失败详情：')
            for d in stats['fail_detail']:
                self.log('    [X] {}'.format(d))
        self.status('图标完成：{}成功/{}跳过/{}失败 共{}'.format(
            stats['success'], stats['skip'], stats['fail'], total))
        self.progress_set(self.icon_state.progress, 0, total)

    def icon_process_restore(self, target_list):
        total = len(target_list)
        stats = {'ico_del': 0, 'ini_clean': 0, 'attr_reset': 0, 'fail': 0}
        self.log('=' * 60)
        self.log('  恢复默认图标 - 处理 {} 个文件夹'.format(total))
        self.log('=' * 60)
        self.status('恢复中... 0/{}'.format(total))
        self.progress_set(self.icon_state.progress, 0, total)

        for i, (rjcode, folder_path, folder_name) in enumerate(target_list, 1):
            while self.icon_state.paused:
                time.sleep(0.5)
            self.log('[{}/{}] [{}] {}'.format(
                i, total, rjcode, _truncate(folder_name)))
            try:
                result = restore_folder_icon(folder_path)
                parts = []
                if result['ico'] > 0:
                    parts.append('删除图标×{}'.format(result['ico']))
                    stats['ico_del'] += result['ico']
                if result['ini']:
                    parts.append('清理desktop.ini')
                    stats['ini_clean'] += 1
                if result['attr']:
                    parts.append('移除System属性')
                    stats['attr_reset'] += 1
                if parts:
                    self.log('  ✅ ' + '、'.join(parts), 'lime')
                else:
                    self.log('  ℹ️ 已无自定义图标', 'gray')
            except Exception as e:
                self.log('  ❌ {}'.format(str(e)[:80]), 'red')
                stats['fail'] += 1
            self.progress_set(self.icon_state.progress, i, total)
            self.status('恢复中... {}/{}'.format(i, total))
        self.icon_state.exit_running()

        self.log('📊 恢复完成！删除ICO:{} 清理ini:{} 重置属性:{} 失败:{}'.format(
            stats['ico_del'], stats['ini_clean'],
            stats['attr_reset'], stats['fail']))
        self.status('恢复完成：{}个文件夹'.format(total))
        self.progress_set(self.icon_state.progress, 0, total)

    # ====================== 重命名逻辑 ======================

    def rename_on_start(self):
        if self.rename_state.running:
            return self.log('任务正在进行中，请等待完成', 'orange')
        if not self.folders:
            return self.log('请先扫描目录', 'orange')
        self.rename_state.enter_running()
        self._undo_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.rename_process_all, daemon=True).start()

    def rename_on_pause(self):
        self.rename_state.toggle_pause(self.log)

    def rename_on_undo(self):
        if self.rename_state.running:
            return self.log('当前有任务进行中，请等待完成', 'orange')
        if not self.rename_history:
            return self.log('没有可撤销的记录', 'orange')
        sel = self.rename_state.listbox.curselection()
        if not sel:
            return self.log('请先在列表中选中要撤销的文件夹（可多选）', 'orange')

        selected_rj = set()
        for i in sel:
            text = self.rename_state.listbox.get(i)
            m = re.match(r'.*?\[(RJ|VJ|BJ)(\d{6,8})\]', text)
            if m:
                selected_rj.add((m.group(1) + m.group(2)).upper())

        to_undo = [(o, n, r, f) for o, n, r, f in self.rename_history
                    if r in selected_rj and os.path.exists(n)]
        if not to_undo:
            return self.log('选中的项目没有可撤销的记录', 'orange')

        self.log('开始撤销重命名（共 {} 个）'.format(len(to_undo)))
        success = 0
        for old_path, new_path, rjcode, folder_name in to_undo:
            try:
                os.rename(new_path, old_path)
                self.log('  ✅ [{}] 已撤销 → {}'.format(rjcode, folder_name), 'lime')
                self.rename_history = [h for h in self.rename_history
                    if h[0] != old_path or h[1] != new_path]
                success += 1
            except Exception as e:
                self.log('  ❌ [{}] 撤销失败：{}'.format(
                    rjcode, str(e)[:60]), 'red')
        self.log('撤销完成：成功 {} / 失败 {}'.format(success, len(to_undo) - success))
        self.on_scan()

    def rename_process_all(self):
        rebuild = self.rename_state.is_rebuild()
        total = len(self.folders)
        stats = {'success': 0, 'skip': 0, 'fail': 0,
                 'fail_detail': [], 'success_detail': []}
        safe = self.safe_mode_var.get()

        self.log('=' * 60)
        self.log('  [重命名] 开始处理' + (' [包裹模式]' if safe else ''))
        self.log('  模式：{}  目录：{}'.format(
            '重做模式' if rebuild else '普通模式', self.target_dir))
        self.log('=' * 60)
        self.status('重命名处理中... 0/{}'.format(total))
        self.progress_set(self.rename_state.progress, 0, total)

        for i, (rjcode, folder_path, folder_name) in enumerate(self.folders, 1):
            while self.rename_state.paused:
                time.sleep(0.5)

            if not rebuild and is_already_renamed(folder_name, rjcode):
                self.rename_state.listbox.itemconfig(i - 1, fg='gray')
                self.log('[{}/{}] [{}] {} → 跳过（已重命名）'.format(
                    i, total, rjcode, _truncate(folder_name)), 'gray')
                stats['skip'] += 1
                self.progress_set(self.rename_state.progress, i, total)
                self.status('重命名处理中... {}/{}'.format(i, total))
                continue

            self.log('[{}/{}] [{}] {}'.format(
                i, total, rjcode, _truncate(folder_name)))

            try:
                self.log('  >> 查询作品信息...', 'cyan')
                info_dict, error = fetch_product_info(rjcode)

                if error:
                    err_msg = {'region_blocked': '区域限制',
                               'not_found': '已下架或不存在',
                               'maintenance': 'DLsite 维护中'}.get(
                                   error, '获取失败')
                    clr = 'orange' if error == 'region_blocked' else 'red'
                    self.log('  ❌ ' + err_msg, clr)
                    stats['fail_detail'].append('{}: {}'.format(rjcode, error))
                    stats['fail'] += 1
                    self.rename_state.listbox.itemconfig(i - 1, fg='red')
                    self.progress_set(self.rename_state.progress, i, total)
                    self.status('重命名处理中... {}/{}'.format(i, total))
                    if i < total:
                        time.sleep(SLEEP_INTERVAL)
                    continue

                source = info_dict.get('source', '')
                source_label = 'API' if source == 'API' else '页面'
                wn = info_dict.get('work_name', '')
                self.log('  >> 来源：{} | 社团：{} | 作品：{}'.format(
                    source_label,
                    info_dict.get('maker_name', '') or '（无社团名）',
                    _truncate(wn, 50)))

                info_arr = _build_info_arr(rjcode, info_dict)
                new_name = build_name_with_config(
                    rjcode, info_arr, self.format_config)
                base_dir = os.path.dirname(folder_path)
                new_name, new_path = _unique_path(base_dir, new_name, ignore_path=folder_path)

                if new_path == folder_path:
                    self.log('  ℹ️ 名称未变化', 'gray')
                    stats['skip'] += 1
                else:
                    if safe:
                        os.makedirs(new_path, exist_ok=True)
                        shutil.move(folder_path, os.path.join(new_path, folder_name))
                        self.log('  📦 包裹完成！', 'lime')
                        self.log('    {} → {}\\{}'.format(
                            folder_name, new_name, folder_name))
                        self.rename_history.append(
                            (folder_path, new_path, rjcode, folder_name))
                        inner_path = os.path.join(new_path, folder_name)
                        self.folders[i - 1] = (rjcode, inner_path, folder_name)
                    else:
                        os.rename(folder_path, new_path)
                        self.rename_history.append(
                            (folder_path, new_path, rjcode, folder_name))
                        self.log('  ✅ 重命名完成！', 'lime')
                        self.log('    {} → {}'.format(folder_name, new_name))
                        self.folders[i - 1] = (rjcode, new_path, new_name)
                    stats['success'] += 1
                    stats['success_detail'].append(
                        '{}: {} → {}'.format(rjcode, folder_name, new_name))

                self.rename_state.listbox.itemconfig(i - 1, fg='green')

            except Exception as e:
                self.log('  ❌ {}'.format(str(e)[:80]), 'red')
                stats['fail'] += 1
                stats['fail_detail'].append('{}: {}'.format(rjcode, str(e)[:40]))
                self.rename_state.listbox.itemconfig(i - 1, fg='red')

            self.progress_set(self.rename_state.progress, i, total)
            self.status('重命名处理中... {}/{}'.format(i, total))
            if i < total:
                time.sleep(SLEEP_INTERVAL)

        self.rename_state.exit_running()
        self._undo_btn.config(state=tk.NORMAL)
        self._log_rename_summary(stats, total)

    def _log_rename_summary(self, stats, total):
        self.log('=' * 60)
        self.log('📊 [重命名] 完成！成功：{} 跳过：{} 失败：{} 共{}'.format(
            stats['success'], stats['skip'], stats['fail'], total))
        if stats['success_detail']:
            self.log('  ✅ 成功详情：')
            for d in stats['success_detail']:
                self.log('    {}'.format(d))
        if stats['fail_detail']:
            self.log('  ❌ 失败详情：')
            for d in stats['fail_detail']:
                self.log('    [X] {}'.format(d))
        self.status('重命名完成：{}成功/{}跳过/{}失败 共{}'.format(
            stats['success'], stats['skip'], stats['fail'], total))
        self.progress_set(self.rename_state.progress, 0, total)

    # ====================== 一键处理逻辑 ======================

    def combined_on_start(self):
        if self.combined_state.running:
            return self.log('任务正在进行中，请等待完成', 'orange')
        if not self.folders:
            return self.log('请先扫描目录', 'orange')
        self.combined_state.enter_running()
        threading.Thread(target=self.combined_process_all, daemon=True).start()

    def combined_on_pause(self):
        self.combined_state.toggle_pause(self.log)

    def combined_is_done(self, rjcode, folder_path, folder_name):
        has_ico = os.path.exists(os.path.join(
            folder_path, '@folder-icon-{}.ico'.format(rjcode)))
        has_ini = os.path.exists(os.path.join(folder_path, 'desktop.ini'))
        return is_already_renamed(folder_name, rjcode) and has_ico and has_ini

    def combined_process_all(self):
        rebuild = self.combined_state.is_rebuild()
        total = len(self.folders)
        stats = {'success': 0, 'skip': 0, 'fail_info': 0, 'fail_icon': 0,
                 'fail_detail': [], 'success_detail': []}
        safe = self.safe_mode_var.get()

        self.log('=' * 60)
        self.log('  ★ [一键处理] 改名 + 封面一步到位' +
                 (' [包裹模式]' if safe else ''))
        self.log('  模式：{}  目录：{}'.format(
            '重做模式' if rebuild else '普通模式', self.target_dir))
        self.log('=' * 60)
        self.status('一键处理中... 0/{}'.format(total))
        self.progress_set(self.combined_state.progress, 0, total)

        for i, (rjcode, folder_path, folder_name) in enumerate(self.folders, 1):
            while self.combined_state.paused:
                time.sleep(0.5)

            if not rebuild and self.combined_is_done(
                    rjcode, folder_path, folder_name):
                self.combined_state.listbox.itemconfig(i - 1, fg='gray')
                self.log('[{}/{}] [{}] {} → 跳过（已完）'.format(
                    i, total, rjcode, _truncate(folder_name)), 'gray')
                stats['skip'] += 1
                self.progress_set(self.combined_state.progress, i, total)
                self.status('一键处理中... {}/{}'.format(i, total))
                continue

            self.log('[{}/{}] [{}] {}'.format(
                i, total, rjcode, _truncate(folder_name)))

            # ------ 步骤1：获取作品信息 + 重命名 ------
            try:
                self.log('  ── ① 查询作品信息...', 'cyan')
                info_dict, error = fetch_product_info(rjcode)

                if error or not info_dict:
                    err_msg = {'region_blocked': '区域限制，跳过',
                               'not_found': '已下架或不存在，跳过',
                               'maintenance': 'DLsite 维护中，跳过'}.get(
                                   error, '获取作品信息失败')
                    clr = 'orange' if error == 'region_blocked' else 'red'
                    self.log('  ❌ ' + err_msg, clr)
                    stats['fail_info'] += 1
                    stats['fail_detail'].append(
                        '{}: 获取信息失败({})'.format(rjcode, error or '无'))
                    self.combined_state.listbox.itemconfig(i - 1, fg='red')
                    self.progress_set(self.combined_state.progress, i, total)
                    self.status('一键处理中... {}/{}'.format(i, total))
                    if i < total:
                        time.sleep(SLEEP_INTERVAL)
                    continue

                source = info_dict.get('source', '')
                source_label = 'API' if source == 'API' else '页面'
                wn = info_dict.get('work_name', '')
                self.log('  >> 来源：{} | 社团：{} | 作品：{}'.format(
                    source_label,
                    info_dict.get('maker_name', '') or '（无社团名）',
                    _truncate(wn, 50)))

                info_arr = _build_info_arr(rjcode, info_dict)
                new_name = build_name_with_config(
                    rjcode, info_arr, self.format_config)
                base_dir = os.path.dirname(folder_path)
                current_path = folder_path
                current_name = folder_name
                # 处理重名
                new_name, new_path = _unique_path(base_dir, new_name, ignore_path=current_path)

                if new_path != current_path:
                    if safe:
                        os.makedirs(new_path, exist_ok=True)
                        shutil.move(current_path,
                                    os.path.join(new_path, current_name))
                        self.log('  📦 包裹：{} → {}\\{}'.format(
                            current_name, new_name, current_name), 'lime')
                        self.rename_history.append(
                            (current_path, new_path, rjcode, current_name))
                        current_path = os.path.join(new_path, current_name)
                        self.folders[i - 1] = (
                            rjcode, current_path, current_name)
                    else:
                        os.rename(current_path, new_path)
                        self.rename_history.append(
                            (current_path, new_path, rjcode, current_name))
                        self.log('  ✅ 改名：{} → {}'.format(
                            current_name, new_name), 'lime')
                        current_path = new_path
                        current_name = new_name
                        self.folders[i - 1] = (
                            rjcode, new_path, new_name)
                else:
                    self.log('  ℹ️ 名称未变化，跳过改名', 'gray')

            except Exception as e:
                self.log('  ❌ 改名失败：{}'.format(str(e)[:80]), 'red')
                stats['fail_info'] += 1
                stats['fail_detail'].append('{}: 改名异常'.format(rjcode))
                self.combined_state.listbox.itemconfig(i - 1, fg='red')
                self.progress_set(self.combined_state.progress, i, total)
                self.status('一键处理中... {}/{}'.format(i, total))
                if i < total:
                    time.sleep(SLEEP_INTERVAL)
                continue

            # ------ 步骤2：获取封面 + 生成 ICO ------
            try:
                # 包裹模式：封面加在外层父文件夹
                icon_folder = (new_path if safe else current_path)
                self.log('  ── ② 获取封面...', 'cyan')
                icon_name = '@folder-icon-{}.ico'.format(rjcode)
                icon_path = os.path.join(icon_folder, icon_name)

                img_url, img_source = get_best_image_url(rjcode)
                if not img_url:
                    err_map = {'region_blocked': '封面区域限制（改名已完成）',
                               'not_found': '封面已下架（改名已完成）'}
                    msg = err_map.get(img_source, '找不到封面（改名已完成）')
                    self.log('  ⚠️ ' + msg, 'orange')
                    stats['fail_icon'] += 1
                    stats['fail_detail'].append('{}: 无封面'.format(rjcode))
                    self.combined_state.listbox.itemconfig(
                        i - 1, fg='#cc8800')
                    self.progress_set(self.combined_state.progress, i, total)
                    self.status('一键处理中... {}/{}'.format(i, total))
                    if i < total:
                        time.sleep(SLEEP_INTERVAL)
                    continue

                self.log('  >> 来源：{}'.format(img_source))
                self.log('  >> 下载中...', 'cyan')
                image = download_image(img_url)
                self.log('  >> 尺寸：{}×{}'.format(image.width, image.height))
                self.log('  >> 生成多尺寸图标...', 'cyan')
                make_ico(image, icon_path, self.format_config.bg_mode)
                kb = os.path.getsize(icon_path) // 1024
                self.log('  >> ICO：{}KB'.format(kb))
                self.log('  >> 设置文件夹图标...', 'cyan')
                set_folder_icon(icon_folder, icon_name)

                stats['success'] += 1
                stats['success_detail'].append(
                    '{}: {} + 图标'.format(rjcode, new_name))
                self.log('  ✅ ★ 全部完成！', 'lime')
                self.combined_state.listbox.itemconfig(i - 1, fg='green')

            except Exception as e:
                self.log('  ⚠️ 封面处理失败（改名已完成）：{}'.format(
                    str(e)[:80]), 'orange')
                stats['fail_icon'] += 1
                stats['fail_detail'].append('{}: 封面异常'.format(rjcode))
                self.combined_state.listbox.itemconfig(i - 1, fg='#cc8800')

            self.progress_set(self.combined_state.progress, i, total)
            self.status('一键处理中... {}/{}'.format(i, total))
            if i < total:
                time.sleep(SLEEP_INTERVAL)

        self.combined_state.exit_running()
        self._log_combined_summary(stats, total)

    def _log_combined_summary(self, stats, total):
        self.log('=' * 60)
        self.log('📊 ★ [一键处理] 完成！')
        self.log('  全部完成（改名+图标）：{}'.format(stats['success']))
        self.log('  跳过（已存在）：{}'.format(stats['skip']))
        self.log('  改名失败：{}'.format(stats['fail_info']))
        self.log('  仅改名成功（图标失败）：{}'.format(stats['fail_icon']))
        self.log('  总计：{}'.format(total))
        if stats['success_detail']:
            self.log('  ✅ 成功详情：')
            for d in stats['success_detail']:
                self.log('    {}'.format(d))
        if stats['fail_detail']:
            self.log('  ⚠️ 失败/警告详情：')
            for d in stats['fail_detail']:
                self.log('    [X] {}'.format(d))
        self.status('一键完成：全部完成{} 跳过{} 改名失败{} 图标失败{} 共{}'.format(
            stats['success'], stats['skip'],
            stats['fail_info'], stats['fail_icon'], total))
        self.progress_set(self.combined_state.progress, 0, total)


def main():
    if tk is None:
        print("错误：Python 未安装 tkinter 模块（GUI 需要）")
        return
    root = tk.Tk()
    app = DlsiteToolsApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
