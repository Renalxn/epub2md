# PROJECT_STATUS — epub2md

面向人类和 AI 都能读懂的连续性文档。中断后回到这个项目，先读这份。

## 当前版本

**v1.2.0**（2026-10-27）。版本号唯一真源是 `epub2md.py` 里的 `__version__`，`CHANGELOG.md` 记录变更。其他文档不写版本号，避免每次改动都要同步。

## 项目目标

把无 DRM 的 epub 转成 Markdown，供在 Obsidian 知识库里阅读和分析。两条硬性要求，都是用户 2026-10-27 提出的长期要求，不是某一次的临时需求：

1. **目录必须能点击跳转到对应章节**
2. **成书内容的位置要和原书一致** —— 原书自带的纯文字目录页（不能点、与生成的目录重复）默认剔除，生成的可点击目录顶替在那一页原来的位置上，不能一律插到文件最前面

## 已完成

- 仅标准库解析 epub（container.xml → OPF → spine 顺序 → XHTML）
- XHTML → Markdown，保留标题层级/列表/粗体斜体，剥离 style/script
- `--stats` 字数分布，`--toc-style obsidian|gh`，`--toc-depth`，`--no-toc`，`--keep-toc-page`，`--version`
- 写回文件逐条自检目录链接（`verify()`）
- 全角空格归一化、同名标题去重
- 剔除 epub 自带的纯文字目录页，并把可点击目录放回该页原位（三信号识别：首行是目录标题 + 与官方 ncx/nav 重合 ≥50% + 无 60 字以上长行；读不到官方目录则一律不删）
- 测试：`tests/test_epub2md.py`，17 个用例，用代码构造的迷你 epub，不依赖真实书籍
- 纳入 git，GitHub 公开仓库 `Renalxn/epub2md`

## 使用位置与调用方式

- 源码（开发位置）：`~/projects/epub2md/epub2md.py`
- 命令入口（安装位置）：`~/.local/bin/epub2md` → 软链接指向上面的源码
- 日常调用：`epub2md <epub目录>/书名.epub -o ~/books/书名.md`

## 技术决策记录

1. **不用 pandoc / calibre / ebooklib**：WSL 里没装，且系统 Python 没有可用的 pip。标准库方案零依赖，换机器就能跑。
2. **obsidian 作为默认目录样式**：用户实测 `[[#标题]]` 在 Obsidian 里能跳；gh 样式留着给 VS Code/GitHub/Typora。两种语法互不通用，脚本每次转换后提醒当前文件适用于哪类平台。
3. **同名标题改名只作用于 obsidian 样式**：GitHub 自己会按出现顺序给锚点加 `-1/-2`，改正文反而对不上。
4. **测试用自造迷你 epub**：真实书稿是有版权的第三方内容，不能进仓库，也不能作为测试依赖。
5. **不打 GitHub Release**：单文件纯脚本没有可下载产物可挂，与同类仓库 nlpm-qwen 一致；只打 `v1.0.0` tag。

## 已知问题

- `gh` 样式下同名标题不做序号去重（`build_toc` 逐个算 slug，`verify` 用包含判断，所以自检能过，但两条链接都只会跳到第一个标题）。obsidian 样式无此问题。属向下兼容修复，处理时应发 PATCH 版。
- 图片、脚注、表格不还原（表格摊成纯文本）。
- 插入目录会让全文行号整体平移，所以引用行号必须按标题名重算。
- 有 DRM 的 epub 读不了。
- 未选开源许可证（README 与仓库里都没有 LICENSE）。

## 下一步

- 需要时修 gh 样式的同名标题去重（PATCH + 补测试）
- 若要给别人复用，先补 LICENSE
- 知识库落位方案定了之后，把默认输出路径写进 README 示例

## 重要规则（红线）

推 GitHub 只能推脚本和文档。**绝不提交** `<epub目录>/` 里的 epub 原书，也**绝不提交**转换出的书稿全文（如 `~/books/*.md`）。`.gitignore` 已挡 `*.epub` 与 `/books/`，提交前仍要检查 `git status` 里有没有书稿。
