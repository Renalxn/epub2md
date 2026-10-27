# epub2md

把 epub 电子书转成带**可点击目录**的 Markdown，只用 Python 标准库，不需要 pandoc、calibre、ebooklib。

epub 本质是一个 zip 包，里面装着 XHTML 网页。这个脚本按书的 spine（阅读顺序）取出各章，转成带 `#` 标题层级的纯文本，并在开头生成目录。

## 环境

Python 3，仅标准库。无 DRM 的 epub 才能直接解析。

## 安装

```bash
git clone https://github.com/Renalxn/epub2md.git
ln -s "$PWD/epub2md/epub2md.py" ~/.local/bin/epub2md   # 让 ~/.local/bin 在 PATH 里，装完直接敲 epub2md
```

不想装命令也可以直接 `python3 epub2md.py ...`。

## 用法

```bash
epub2md --stats book.epub                    # 先看各内容块字数，判断能否一次读完
epub2md book.epub -o ~/notes/书名.md          # 转换，默认 Obsidian 可点目录
epub2md book.epub -o out.md --toc-style gh    # 换成 VS Code / GitHub / Typora 能点的锚点
epub2md --version
```

## 两种目录链接语法互不通用

| 样式 | 正文链接写法 | 能点的平台 |
|---|---|---|
| `obsidian`（默认） | `[[#标题]]` | Obsidian、Logseq |
| `gh` | `[标题](#标题锚点)` | VS Code 预览、GitHub、Typora |

用错平台的症状就是“目录看着在，点了没反应”。脚本每次转换结束会提醒当前文件适用于哪类平台。

同名标题在 Obsidian 里只会跳到第一个，所以 obsidian 样式会给正文中第 2 个及以后的同名标题追加序号，目录同步用同一个名字；`gh` 样式不改正文，交给 GitHub 自己的 `-1/-2` 锚点规则。

## 自检

写完文件后脚本会重新读回，逐条核对目录链接是否命中正文标题，全部命中才报“自检通过”。这是硬性要求：目录点不动的书稿没有价值。

另两项人工检查应始终为 0：

```bash
grep -c "<[a-zA-Z/]" 书名.md      # 残留 HTML 标签
grep -c "&amp;\|&#" 书名.md       # 残留 HTML 实体
```

## 测试

测试用代码现场构造一个两章的迷你 epub，不依赖任何真实书籍文件：

```bash
python3 -m unittest discover -s tests -v
```

## 已知边界

- 图片、CSS、脚注链接不转换（正文文字保留，图与链接形式丢失）
- 表格按纯文本摊平，不生成 Markdown 表格
- 有 DRM 的 epub 读不了，需要先拿到无保护文件
- 版权书稿不要提交进仓库，`.gitignore` 已挡住 `*.epub` 与 `/books/`
