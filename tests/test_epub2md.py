"""用代码现造的迷你 epub 验证转换结果，不依赖任何真实书籍文件。"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'epub2md.py')
sys.path.insert(0, ROOT)
import epub2md  # noqa: E402

CONTAINER = ('<?xml version="1.0"?>'
             '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
             '<rootfiles><rootfile full-path="OEBPS/content.opf" '
             'media-type="application/oebps-package+xml"/></rootfiles></container>')

XHTML = ('<?xml version="1.0" encoding="utf-8"?>'
         '<html xmlns="http://www.w3.org/1999/xhtml">'
         '<head><title>ch</title><style>p{}</style></head>'
         '<body>%s</body></html>')

OPF = ('<?xml version="1.0"?>'
       '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
       '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
       '<dc:title>%s</dc:title><dc:creator>%s</dc:creator></metadata>'
       '<manifest>%s<style id="s" href="style.css" media-type="text/css"/>'
       '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
       '<spine toc="ncx">%s</spine></package>')

NCX = ('<?xml version="1.0"?>'
       '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
       '<navMap>%s</navMap></ncx>')

NAVPOINT = ('<navPoint id="n%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
            '<src>%s</src></navPoint>')

# 书自带的"纯文字目录页"：条目与 NCX 完全一致，且没有长段落
TOC_PAGE = ('<h1>目录</h1><p>第一章 开篇</p><p>重复出现的标题</p>'
            '<p>第二章</p><p>重复出现的标题</p><p>要点一</p><p>要点二</p>'
            '<p>附录</p><p>致谢</p>')


def make_epub(path, chapters, title='测试书', with_toc_page=False, author='[某] 测试·作者'):
    """chapters: [(文件名, XHTML 正文)]；with_toc_page=True 时把书自带的纯文字目录页
    插在第 1 章之后（模拟真实书的"版权页 → 目录页 → 正文"顺序）。"""
    items, refs, files = [], [], []
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip')
        zf.writestr('META-INF/container.xml', CONTAINER)
        for i, (fname, body) in enumerate(chapters, 1):
            files.append(('OEBPS/' + fname, XHTML % body))
            items.append('<item id="i%d" href="%s" media-type="application/xhtml+xml"/>' % (i, fname))
            refs.append('<itemref idref="i%d"/>' % i)
            if with_toc_page and i == 1:
                files.append(('OEBPS/toc-page.xhtml', XHTML % TOC_PAGE))
                items.append('<item id="itoc" href="toc-page.xhtml" '
                             'media-type="application/xhtml+xml"/>')
                refs.append('<itemref idref="itoc"/>')
        zf.writestr('OEBPS/style.css', 'p { color: black }')
        points = ''.join(NAVPOINT % (n, n, t, 'c1.xhtml') for n, t in enumerate(
            ['第一章 开篇', '重复出现的标题', '第二章', '重复出现的标题',
             '要点一', '要点二', '附录', '致谢'], 1))
        zf.writestr('OEBPS/toc.ncx', NCX % points)
        for name, content in files:
            zf.writestr(name, content)
        zf.writestr('OEBPS/content.opf', OPF % (title, author, ''.join(items), ''.join(refs)))

CHAPTER_ONE = ('<h1>第一章\u3000开篇</h1><p>第一段正文，含 <em>强调</em> 与 &amp; 符号。</p>'
               '<h2>重复出现的标题</h2><p>甲。</p>')
CHAPTER_TWO = ('<h1>第二章</h1><p>第二段\u3000正文。</p>'
               '<h2>重复出现的标题</h2><p>乙。</p>'
               '<ul><li>要点一</li><li>要点二</li></ul>')
CHAPTERS = [('c1.xhtml', CHAPTER_ONE), ('c2.xhtml', CHAPTER_TWO)]


def epub2md_text(body):
    """把一段 XHTML 正文片段转成脚本实际得到的文本，供判据单测使用。"""
    t = epub2md.Textify()
    t.feed(XHTML % body)
    return t.text()


class Epub2mdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.epub = os.path.join(self.tmp.name, 'mini.epub')
        make_epub(self.epub, CHAPTERS)
        self.out = os.path.join(self.tmp.name, 'mini.md')

    def epub_with_toc_page(self):
        p = os.path.join(self.tmp.name, 'mini-toc.epub')
        make_epub(p, CHAPTERS, with_toc_page=True)
        return p

    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, SCRIPT] + list(args),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def read(self):
        with open(self.out, encoding='utf-8') as fh:
            return fh.read()

    def test_version_flag_reports_semver(self):
        self.assertIn('epub2md %s' % epub2md.__version__,
                      self.run_cli('--version'))

    def test_spine_order_and_meta_title(self):
        title, chunks, dropped, toc_pos, creators = epub2md.load_chunks(self.epub)
        self.assertEqual(title, '测试书')
        self.assertEqual([name for name, _ in chunks], ['c1.xhtml', 'c2.xhtml'])
        self.assertEqual(dropped, [])
        self.assertIsNone(toc_pos)
        self.assertEqual(creators, ['[某] 测试·作者'])

    def test_obsidian_output_has_clickable_resolved_toc(self):
        self.run_cli(self.epub, '-o', self.out)
        text = self.read()
        self.assertIn('## 目录', text)
        self.assertIn('- [[#第一章 开篇]]', text)
        total, bad = epub2md.verify(self.out)
        self.assertEqual(bad, [], '目录链接未能命中正文标题：%s' % bad)
        self.assertGreater(total, 0)

    def test_fullwidth_space_normalized_in_headings(self):
        self.run_cli(self.epub, '-o', self.out)
        for line in self.read().split('\n'):
            if epub2md.HEADING_RE.match(line):
                self.assertNotIn('\u3000', line)

    def test_duplicate_headings_numbered_for_obsidian(self):
        self.run_cli(self.epub, '-o', self.out)
        text = self.read()
        self.assertIn('## 重复出现的标题 2', text)
        self.assertEqual(text.count('- [[#重复出现的标题]]'), 1)

    def test_gh_style_uses_standard_anchors(self):
        self.run_cli(self.epub, '-o', self.out, '--toc-style', 'gh')
        text = self.read()
        self.assertIn('- [第一章 开篇](#第一章-开篇)', text)
        total, bad = epub2md.verify(self.out)
        self.assertEqual(bad, [], '%s' % bad)

    def test_no_toc_option(self):
        self.run_cli(self.epub, '-o', self.out, '--no-toc')
        self.assertNotIn('## 目录', self.read())

    def test_output_is_free_of_html_and_css_leakage(self):
        self.run_cli(self.epub, '-o', self.out)
        text = self.read()
        self.assertIsNone(re.search(r'<[a-zA-Z/]', text), '残留 HTML 标签')
        self.assertNotIn('&amp;', text)
        self.assertNotIn('color: black', text, '样式表内容混进了正文')

    def test_markdown_lists_and_emphasis_preserved(self):
        self.run_cli(self.epub, '-o', self.out)
        text = self.read()
        self.assertIn('- 要点一', text)
        self.assertIn('*强调*', text)

    def test_stats_reports_block_count(self):
        out = self.run_cli(self.epub, '--stats')
        self.assertIn('2 blocks', out)

    def test_repeat_toc_page_detected(self):
        """与 epub 官方目录高度重合、且全是短标题的"目录页"应被识别。"""
        ref = {'第一章开篇', '重复出现的标题', '第二章', '要点一', '要点二', '附录', '致谢'}
        self.assertTrue(epub2md.looks_like_repeat_toc(epub2md_text(TOC_PAGE), ref)[0])

    def test_real_chapter_is_never_treated_as_toc_page(self):
        """真正文（长段落 + 首行不是"目录"）绝不能被误判剔除。"""
        ref = {'第一章开篇', '重复出现的标题', '第二章', '要点一', '要点二', '附录', '致谢'}
        for body in (CHAPTER_ONE, CHAPTER_TWO):
            self.assertFalse(epub2md.looks_like_repeat_toc(epub2md_text(body), ref)[0])

    def test_toc_page_without_ncx_reference_is_kept(self):
        """没有官方目录可比对时，宁可不删，避免误删正文。"""
        p = os.path.join(self.tmp.name, 'noncx.epub')
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('META-INF/container.xml', CONTAINER)
            zf.writestr('OEBPS/toc-page.xhtml', XHTML % TOC_PAGE)
            zf.writestr('OEBPS/content.opf',
                        OPF % ('无目录书', '测试作者', '<item id="i1" href="toc-page.xhtml" '
                               'media-type="application/xhtml+xml"/>', '<itemref idref="i1"/>'))
        _, chunks, dropped, toc_pos, _ = epub2md.load_chunks(p)
        self.assertEqual([n for n, _ in chunks], ['toc-page.xhtml'])
        self.assertEqual(dropped, [])
        self.assertIsNone(toc_pos)

    def test_book_own_toc_page_dropped_by_default(self):
        """默认剔除书自带的纯文字目录页，输出里只剩一份可点击目录。"""
        self.run_cli(self.epub_with_toc_page(), '-o', self.out)
        text = self.read()
        self.assertEqual(text.count('## 目录'), 1, '正文里不该再留一份纯文字目录')
        self.assertNotIn('目录\n\n引', text)
        total, bad = epub2md.verify(self.out)
        self.assertEqual(bad, [], '%s' % bad)

    def test_generated_toc_sits_where_book_toc_page_was(self):
        """目录页夹在第 1 章与第 2 章之间时，生成的可点击目录也放在同一位置，
        保证成书顺序（第 1 章 → 目录 → 第 2 章）与原书一致。"""
        self.run_cli(self.epub_with_toc_page(), '-o', self.out)
        text = self.read()
        self.assertLess(text.index('# 第一章 开篇'), text.index('## 目录'),
                        '第 1 章应排在目录之前（原书顺序）')
        self.assertLess(text.index('## 目录'), text.index('# 第二章'),
                        '第 2 章应排在目录之后（原书顺序）')
        total, bad = epub2md.verify(self.out)
        self.assertEqual(bad, [], '%s' % bad)
        self.assertEqual(total, 4, '目录要同时命中目录页之前和之后的标题')

    def test_order_preserved_when_book_has_no_toc_page(self):
        """原书没有目录页时，章节顺序不变，目录仍放最前。"""
        self.run_cli(self.epub, '-o', self.out)
        text = self.read()
        self.assertLess(text.index('## 目录'), text.index('# 第一章 开篇'))
        self.assertLess(text.index('# 第一章 开篇'), text.index('# 第二章'))

    def test_keep_toc_page_option_restores_it(self):
        self.run_cli(self.epub_with_toc_page(), '-o', self.out, '--keep-toc-page')
        self.assertIn('# 目录', self.read())

    def test_default_output_has_no_frontmatter(self):
        """不传 --tags 时一个字都不能多，保证旧产物的 md5 仍然可比对。"""
        self.run_cli(self.epub, '-o', self.out)
        self.assertTrue(self.read().startswith('# 测试书\n'), '开头不该有 frontmatter')

    def test_tags_write_frontmatter_at_the_very_top(self):
        """Obsidian 标签面板只认文件最开头的 YAML 块；作者标签自动附在后面。"""
        self.run_cli(self.epub, '-o', self.out, '--tags', '心理,成长')
        self.assertTrue(self.read().startswith(
            '---\ntags:\n  - "心理"\n  - "成长"\n  - "作者/测试-作者"\n---\n\n# 测试书\n'))

    def test_tags_are_split_deduped_and_ordered(self):
        """中英文逗号、顿号都当分隔符；重复标签只留一份；顺序按用户输入。"""
        self.assertEqual(epub2md.parse_tags('心理，成长, 心理 、 心理 '), ['心理', '成长'])
        self.assertEqual(epub2md.parse_tags('  , ， '), [])

    def test_frontmatter_quotes_yaml_special_characters(self):
        """标签里带 : " \\ 时不能把 YAML 结构写坏。"""
        block = epub2md.frontmatter(['带: 冒号', '带"引号'])
        self.assertIn('  - "带: 冒号"', block)
        self.assertIn(r'  - "带\"引号"', block)

    def test_toc_self_check_still_passes_with_frontmatter(self):
        """frontmatter 占掉文件开头后，目录自检仍要逐条命中正文标题。"""
        self.run_cli(self.epub_with_toc_page(), '-o', self.out, '--tags', '心理')
        total, bad = epub2md.verify(self.out)
        self.assertEqual(bad, [], '%s' % bad)
        self.assertEqual(total, 4)

    def test_tags_with_only_separators_writes_no_frontmatter(self):
        out = self.run_cli(self.epub, '-o', self.out, '--tags', '，,,')
        self.assertIn('未写入 frontmatter', out)
        self.assertTrue(self.read().startswith('# 测试书\n'))

    def test_author_tags_clean_real_world_metadata(self):
        """dc:creator 常带噪声（以下示例已化名），清洗后必须是 Obsidian 合法标签。"""
        cases = [
            ('[某] 甲·乙', ['作者/甲-乙']),
            ('【某】丙·丁', ['作者/丙-丁']),
            ('[某]庚', ['作者/庚']),
            ('戊，己 等', ['作者/戊', '作者/己']),
            ('辛·壬', ['作者/辛-壬']),
            ('癸', ['作者/癸']),
        ]
        for raw, expect in cases:
            self.assertEqual(epub2md.author_tags([raw]), expect, '原文 %r 清洗结果不对' % raw)

    def test_author_tags_reject_number_only_and_junk(self):
        """纯数字标签 Obsidian 不认；只有"等"这种残片也不该变成标签。"""
        self.assertEqual(epub2md.author_tags(['1984']), [])
        self.assertEqual(epub2md.author_tags(['等']), [])

    def test_nested_tags_pass_through_verbatim(self):
        """斜杠是 Obsidian 的层级分隔符，脚本一个字都不能动。"""
        self.run_cli(self.epub, '-o', self.out, '--tags', '电子书/心理学/思维模式')
        self.assertIn('  - "电子书/心理学/思维模式"', self.read())

    def test_no_author_tag_option(self):
        self.run_cli(self.epub, '-o', self.out, '--tags', '心理', '--no-author-tag')
        self.assertNotIn('作者/', self.read())

    def test_no_tags_means_no_author_hint(self):
        """不传 --tags 时仍不写 frontmatter（保住逐字节兼容），但要提示作者标签没写。"""
        out = self.run_cli(self.epub, '-o', self.out)
        self.assertIn('提示：未传 --tags', out)

    def test_space_in_user_tag_is_warned(self):
        """Obsidian 1.4 起带空格的标签会被劈成两条，必须提醒而不是闷头写进去。"""
        out = self.run_cli(self.epub, '-o', self.out, '--tags', '心 理')
        self.assertIn('不认的字符', out)


if __name__ == '__main__':
    unittest.main()
