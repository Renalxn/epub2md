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
       '<dc:title>%s</dc:title></metadata>'
       '<manifest>%s<style id="s" href="style.css" media-type="text/css"/></manifest>'
       '<spine>%s</spine></package>')


def make_epub(path, chapters, title='测试书'):
    items, refs = [], []
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip')
        zf.writestr('META-INF/container.xml', CONTAINER)
        for i, body in enumerate(chapters, 1):
            zf.writestr('OEBPS/c%d.xhtml' % i, XHTML % body)
            items.append('<item id="i%d" href="c%d.xhtml" media-type="application/xhtml+xml"/>' % (i, i))
            refs.append('<itemref idref="i%d"/>' % i)
        zf.writestr('OEBPS/style.css', 'p { color: black }')
        zf.writestr('OEBPS/content.opf', OPF % (title, ''.join(items), ''.join(refs)))


CHAPTER_ONE = ('<h1>第一章\u3000开篇</h1><p>第一段正文，含 <em>强调</em> 与 &amp; 符号。</p>'
               '<h2>重复出现的标题</h2><p>甲。</p>')
CHAPTER_TWO = ('<h1>第二章</h1><p>第二段\u3000正文。</p>'
               '<h2>重复出现的标题</h2><p>乙。</p>'
               '<ul><li>要点一</li><li>要点二</li></ul>')


class Epub2mdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.epub = os.path.join(self.tmp.name, 'mini.epub')
        make_epub(self.epub, [CHAPTER_ONE, CHAPTER_TWO])
        self.out = os.path.join(self.tmp.name, 'mini.md')

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
        title, chunks = epub2md.load_chunks(self.epub)
        self.assertEqual(title, '测试书')
        self.assertEqual([name for name, _ in chunks], ['c1.xhtml', 'c2.xhtml'])

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


if __name__ == '__main__':
    unittest.main()
