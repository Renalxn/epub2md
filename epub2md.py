#!/usr/bin/env python3
"""epub -> markdown, stdlib only.

    epub2md <book.epub> [-o out.md] [--stats]
"""
import argparse
import html
import os
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

__version__ = '1.2.0'


def localname(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


class Textify(HTMLParser):
    BLOCK_END = {'p', 'div', 'section', 'article', 'blockquote', 'h1', 'h2',
                 'h3', 'h4', 'h5', 'h6', 'tr', 'table', 'dl', 'figure'}
    HEADINGS = {'h1': '#', 'h2': '##', 'h3': '###', 'h4': '####',
                'h5': '#####', 'h6': '######'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = localname(tag)
        if tag in ('style', 'script', 'head'):
            self.skip += 1
        if tag in self.HEADINGS:
            self.out.append('\n\n' + self.HEADINGS[tag] + ' ')
        elif tag == 'li':
            self.out.append('\n- ')
        elif tag == 'br':
            self.out.append('\n')
        elif tag in ('em', 'i'):
            self.out.append('*')
        elif tag in ('strong', 'b'):
            self.out.append('**')
        elif tag in self.BLOCK_END:
            self.out.append('\n\n')

    def handle_endtag(self, tag):
        tag = localname(tag)
        if tag in ('style', 'script', 'head'):
            self.skip = max(0, self.skip - 1)
        if tag in self.HEADINGS:
            self.out.append('\n\n')
        elif tag == 'li':
            self.out.append('\n')
        elif tag in ('em', 'i'):
            self.out.append('*')
        elif tag in ('strong', 'b'):
            self.out.append('**')
        elif tag in ('ul', 'ol'):
            self.out.append('\n')
        elif tag in self.BLOCK_END:
            self.out.append('\n\n')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def text(self):
        raw = html.unescape(''.join(self.out))
        raw = raw.replace('\u00ad', '')
        raw = re.sub(r'[ \t\u3000]+\n', '\n', raw)
        raw = re.sub(r'\n[ \t\u3000]+', '\n', raw)
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        return raw.strip()


def opf_path(zf):
    root = ET.fromstring(zf.read('META-INF/container.xml').decode('utf-8', 'ignore'))
    for el in root.iter():
        if localname(el.tag) == 'rootfile':
            return el.get('full-path')
    raise SystemExit('OPF not found')


def spine_and_meta(zf, opf):
    root = ET.fromstring(zf.read(opf).decode('utf-8', 'ignore'))
    base = posixpath.dirname(opf)
    manifest, spine, titles = {}, [], []
    for el in root.iter():
        t = localname(el.tag)
        if t == 'item' and el.get('href'):
            href = el.get('href').split('#')[0]
            manifest[el.get('id')] = posixpath.normpath(posixpath.join(base, href)) if base else href
        elif t == 'itemref':
            spine.append(el.get('idref'))
        elif t == 'title':
            titles.append(' '.join((el.text or '').split()))
    return manifest, [s for s in spine if s in manifest], (titles[0] if titles else '')


def _norm(s):
    """标题比对用的归一化：抹掉空格（含全角）、标点、数字符号，只留中英文和数字。
    NCX 条目和目录页文字必须用同一个函数处理，否则空格差异会导致比对失败。"""
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', s.lower())


def ncx_titles(zf, opf):
    """读取 epub 官方目录（toc.ncx / EPUB3 nav 文档）里的标题集合。"""
    raws = []
    root = ET.fromstring(zf.read(opf).decode('utf-8', 'ignore'))
    base_dir = posixpath.dirname(opf)
    targets = []
    for el in root.iter():
        if localname(el.tag) == 'item':
            mt = (el.get('media-type') or '').lower()
            href = (el.get('href') or '').split('#')[0]
            if mt.endswith('ncx+xml') or href.lower().endswith('.ncx'):
                targets.append(href)
            if 'nav' in (el.get('properties') or ''):
                targets.append(href)
    for cand in targets:
        path = posixpath.normpath(posixpath.join(base_dir, cand)) if base_dir else cand
        try:
            raws.append(zf.read(path).decode('utf-8', 'ignore'))
        except KeyError:
            continue
    titles = set()
    for raw in raws:
        for m in re.finditer(r'<text>([^<]*)</text>', raw):
            t = m.group(1).strip()
            if t:
                titles.add(_norm(t))
        for m in re.finditer(r'<a[^>]*>([^<]*)</a>', raw):
            t = m.group(1).strip()
            if t:
                titles.add(_norm(t))
    return {t for t in titles if t}


TOC_WORDS = {'目录', '目次', 'contents', 'tableofcontents', 'toc'}


def looks_like_repeat_toc(text, ref_titles):
    """判断某块是否为"纯文字目录页"：首行是目录标题 + 与官方目录高度重合 + 无长段落。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) < 8:
        return False, ''
    if _norm(lines[0]) not in TOC_WORDS:
        return False, ''
    entries = [_norm(l) for l in lines[1:]]
    entries = [e for e in entries if e]
    if not entries:
        return False, ''
    hits = sum(1 for e in entries if e in ref_titles)
    overlap = hits / len(entries)
    long_lines = sum(1 for l in lines if len(l) > 60)
    why = '与官方目录重合 %d/%d（%.0f%%），%d 行' % (hits, len(entries), overlap * 100, len(lines))
    return (overlap >= 0.5 and long_lines == 0), why


def load_chunks(epub, drop_repeat_toc=True):
    """返回 (书名, [(文件名, 正文)], [被剔除的重复目录页说明], 该目录页在原书里的位置)。"""
    chunks, dropped, toc_pos = [], [], None
    with zipfile.ZipFile(epub) as zf:
        opf = opf_path(zf)
        manifest, order, title = spine_and_meta(zf, opf)
        ref_titles = ncx_titles(zf, opf)
        for idref in order:
            name = manifest[idref]
            if not name.lower().endswith(('.xhtml', '.html', '.htm')):
                continue
            try:
                body = Textify()
                body.feed(zf.read(name).decode('utf-8', 'ignore'))
                text = body.text()
            except KeyError:
                continue
            if not text:
                continue
            if drop_repeat_toc:
                is_toc, why = looks_like_repeat_toc(text, ref_titles)
                if is_toc:
                    dropped.append('%s（%s）' % (posixpath.basename(name), why))
                    if toc_pos is None:
                        toc_pos = len(chunks)
                    continue
            chunks.append((posixpath.basename(name), text))
    return title, chunks, dropped, toc_pos


HEADING_RE = re.compile(r'^(#{1,6}) (.+)$')


def normalize_headings(text):
    """把标题行里的全角空格换成普通空格，使两种锚点写法都可预测。"""
    lines = []
    for line in text.split('\n'):
        m = HEADING_RE.match(line)
        if m:
            line = '%s %s' % (m.group(1), ' '.join(m.group(2).replace('\u3000', ' ').split()))
        lines.append(line)
    return '\n'.join(lines)


def gh_slug(title):
    """模拟 GitHub/VS Code 的标题锚点规则。"""
    s = title.strip().lower()
    s = ''.join(c for c in s if c.isalnum() or c in ' _-' or ord(c) > 0x2FFF)
    s = re.sub(r'\s+', '-', s.strip())
    return s or 'section'


def gh_anchors(titles):
    """按 GitHub 规则把标题列表换成锚点，同名标题在全文顺序上追加 -1/-2。"""
    counts, out = {}, []
    for t in titles:
        s = gh_slug(t)
        n = counts.get(s, 0)
        counts[s] = n + 1
        out.append(s if n == 0 else '%s-%d' % (s, n))
    return out


def all_headings(text):
    out = []
    for line in text.split('\n'):
        m = HEADING_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def build_toc(body, style='obsidian', depth=3):
    """扫描正文标题生成可点击目录。重复标题已由 main() 在正文里改名。"""
    heads = all_headings(body)
    anchors = ([gh_slug(t) for _, t in heads] if style == 'gh'
               else [t for _, t in heads])
    rows = []
    for (level, title), anchor in zip(heads, anchors):
        if level > depth:
            continue
        if style == 'gh':
            label = title.replace('[', '\\[').replace(']', '\\]')
            rows.append('%s- [%s](#%s)' % ('  ' * (level - 1), label, anchor))
        else:
            rows.append('%s- [[#%s]]' % ('  ' * (level - 1), anchor))
    toc = '## 目录\n\n' + '\n'.join(rows) + '\n\n---\n\n'
    return toc, len(rows)


def verify(path):
    """从磁盘读回文件，检查目录里每条链接都能命中正文标题。"""
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    head, sep, rest = text.partition('## 目录\n')
    if not sep:
        return None, ['文件里没有目录']
    toc_part, sep2, body_part = rest.partition('\n---\n')
    if not sep2:
        return None, ['目录块后找不到分隔线']
    # 目录插在正文中间（原书目录页所在位置），所以目录之前的书名页、版权页
    # 也算正文标题。head 里第一个标题是脚本自己加的书名，不参与目录，需排除。
    before = all_headings(head)[1:]
    titles = [t for _, t in before + all_headings(body_part)]
    anchors = gh_anchors(titles)
    bad, total = [], 0
    for line in toc_part.split('\n'):
        s = line.strip()
        if s.startswith('- [[#') and s.endswith(']]'):
            total += 1
            if s[5:-2] not in titles:
                bad.append(s)
        elif s.startswith('- [') and '](#' in s:
            total += 1
            if s.split('](#')[1].rstrip(')') not in anchors:
                bad.append(s)
    return total, bad


def number_duplicate_headings(parts, depth):
    """Obsidian 里同名标题只会跳到第一个，所以给正文第 2 个及以后的同名标题加序号。

    parts 是"每个内容块一段文本"，按块处理而不是拼成一整篇再切，
    这样目录插入位置（也靠块下标定位）不会和分隔符混淆。
    gh 样式不走这里：GitHub/VS Code 自己按出现顺序给锚点追加 -1/-2。
    """
    counter = {}
    for level, t in all_headings('\n\n'.join(parts)):
        if level <= depth:
            counter[t] = counter.get(t, 0) + 1
    dupes = {t for t, c in counter.items() if c > 1}
    if not dupes:
        return parts
    seen, out = {}, []
    for part in parts:
        lines = part.split('\n')
        for i, line in enumerate(lines):
            m = HEADING_RE.match(line)
            if m and len(m.group(1)) <= depth and m.group(2) in dupes:
                t = m.group(2)
                seen[t] = seen.get(t, 0) + 1
                if seen[t] > 1:
                    lines[i] = '%s %s %d' % (m.group(1), t, seen[t])
        out.append('\n'.join(lines))
    return out


def main():
    ap = argparse.ArgumentParser(prog='epub2md', description=__doc__.strip())
    ap.add_argument('epub')
    ap.add_argument('-o', '--out')
    ap.add_argument('--version', action='version', version='epub2md ' + __version__)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--toc-style', choices=['obsidian', 'gh'], default='obsidian',
                    help='obsidian=[[#标题]]；gh=[标题](#标题锚点)，适用 VS Code/GitHub/Typora')
    ap.add_argument('--toc-depth', type=int, default=3, help='目录收录到第几级标题')
    ap.add_argument('--no-toc', action='store_true', help='不生成目录')
    ap.add_argument('--keep-toc-page', action='store_true',
                    help='保留 epub 自带的纯文字目录页（默认剔除，避免和可点击目录重复）')
    a = ap.parse_args()

    title, chunks, dropped, toc_pos = load_chunks(a.epub, drop_repeat_toc=not a.keep_toc_page)

    if a.stats:
        for i, (name, text) in enumerate(chunks, 1):
            head = next((l for l in text.split('\n') if l.startswith('#')), name)
            print('%3d  %7d  %s' % (i, len(text), head[:60]))
        print('\n%d blocks, %d chars' % (len(chunks), sum(len(t) for _, t in chunks)))
        return

    parts = [normalize_headings(t) for _, t in chunks if t]
    n_entries = 0

    if not a.no_toc:
        if a.toc_style == 'obsidian':
            parts = number_duplicate_headings(parts, a.toc_depth)
        body = '\n\n---\n\n'.join(parts)
        toc, n_entries = build_toc(body, a.toc_style, a.toc_depth)
        # 目录放回原书目录页所在的位置，保持书的前后顺序和原书一致；
        # 原书没有目录页时（toc_pos 为 None）仍然放在最前面。
        pos = min(toc_pos, len(parts)) if toc_pos is not None else 0
        head_block = '\n\n---\n\n'.join(parts[:pos])
        md = '# %s\n\n' % title
        if head_block:
            md += head_block + '\n\n---\n\n'
        md += toc + '\n\n---\n\n'.join(parts[pos:]) + '\n'
    else:
        body = '\n\n---\n\n'.join(parts)
        md = '# %s\n\n' % title + body + '\n'

    out = os.path.abspath(a.out or posixpath.splitext(posixpath.basename(a.epub))[0] + '.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(md)

    print('已写出 %s' % out)
    print('目录 %d 条（样式 %s，深度 %d），正文 %d 字符'
          % (n_entries, a.toc_style, a.toc_depth, len(body)))
    for d in dropped:
        print('已剔除 epub 自带的重复目录页：%s' % d)
    if a.no_toc:
        print('未生成目录')
    else:
        total, bad = verify(out)
        if bad:
            print('!! %d/%d 条目录链接无法命中正文标题，例如：' % (len(bad), total))
            for b in bad[:5]:
                print('   %s' % b[:100])
        else:
            print('自检通过（读回文件逐条核对）：%d 条目录链接全部命中正文标题' % total)
    if a.toc_style == 'gh':
        print('提醒：本文件用标准锚点，Obsidian 里点不动，需改用 --toc-style obsidian')
    else:
        print('提醒：本文件用 Obsidian 内链，VS Code/GitHub 里点不动，需改用 --toc-style gh')


if __name__ == '__main__':
    main()
