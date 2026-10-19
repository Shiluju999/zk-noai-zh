# zk-noai-zh

中文文本去 AI 化的 Agent Skill。**分两层处理**：去 AI 化管格式与符号，去 AI 感管内容与表达。按 7 轮流程逐步执行，并配一套脚本流水线做量化体检与回归校验。

流程主干来自个人实战总结，模式库继承自 [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) 的观察结论，经 `blader/humanizer` → `op7418/Humanizer-zh` 两代中文化，本仓库是第三处本地分叉。

隐形字符清理与元数据清洗的思路来自 [wsylvest/watermarks-remover](https://github.com/wsylvest/watermarks-remover)（MIT），其中四个脚本原样收进 `scripts/`；中文打分器与元数据清洗模块为本地自写。

来源、许可与修改记录见 [references/upstream.md](references/upstream.md)。

## 和原版 humanizer-zh 有什么不同

| 维度 | 原版 | 本仓库 |
|---|---|---|
| 组织方式 | 24 条规则平铺 | **7 轮执行流程**为主干，规则降级为参考 |
| 主战场 | 内容与表达 | **格式层 + 内容层**，格式先行 |
| 一致性检查 | 无 | **第 5 轮硬约束**：术语、数据、论点数量 |
| 操作指引 | 无 | **7 轮逐步过**，含自检清单 |
| 文体适配 | 无 | **文体豁免表**：公文/论文/汇报/随笔分别处理 |
| 收尾动作 | 无 | **第 7 轮全文默读** + 脚本回归校验 |
| 可量化 | 无 | **`scripts/deai.py`**：中文特征打分、隐形字符、元数据清洗、回归校验 |

核心判断：原版教"怎么写得不那么像 AI"，本仓库教"**按什么顺序动手，每步做完什么样算合格**"。

## 文件结构

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 执行手册，脚本流水线 + 7 轮流程 + 内容检查点 + 自检清单 |
| `references/patterns-zh.md` | 24 条 AI 写作模式详解，含改写前后对照 |
| `references/upstream.md` | 来源、许可、已知问题与修改记录 |
| `scripts/deai.py` | 统一流水线入口：`report` / `freeze` / `layer-a` / `score` / `verify` / `meta` |
| `scripts/score_stylometry.py` | 中文文体打分器（自写，替换上游只认英文的实现） |
| `scripts/meta_docx.py` | OOXML 元数据检查与清洗（自写，只依赖标准库） |
| `scripts/inspect_text.py` 等 4 个 | 来自 wsylvest/watermarks-remover，**原样保留，勿改** |
| `LICENSE` | MIT |

## 脚本流水线

```bash
python scripts/deai.py report 文档.docx                    # 体检：指纹 + 打分 + 元数据
python scripts/deai.py freeze 文档.docx                    # 冻结原文哈希
python scripts/deai.py layer-a 文本.txt --clean -o 净.txt   # 零宽字符等
python scripts/deai.py score 文本.txt --explain            # 中文 AI 特征明细
python scripts/deai.py verify --original 原.docx --revised 改后.docx
python scripts/deai.py meta 改后.docx --clean -o 净.docx    # 元数据，放最后
```

**顺序不能变。** 元数据必须在所有内容改动落盘之后清——`python-docx` 每次 `save()` 都会重写 `docProps/`，先清会被写回。

**回归校验不能省。** 改写者和检查者是同一个模型，自我检出率接近零。`verify` 做确定性比对，四项硬门槛：原文哈希、特征分不得上升、专名数字零丢失、汉字删减不超 25%。

## 中文打分器为什么要自己写

上游的 `score_stylometry.py` 规则全是为英文设计的，对中文基本失效。同一段 446 字的中文 AI 腔文本，上游给出：

```
word_count=33   实际 413 个汉字
sentence_count=1   实际 9 句
ai_ngram_density=0.0   matched_markers=[]
score=0.0077  tier=low
```

根因在源码里：`RE_WORDS = re.compile(r"\b[\w'-]+\b", re.UNICODE)` 对无空格的中文整段只切出一个 token；切句正则 `(?<=[.!?])\s+|\n+` 不认 `。！？`；`AI_PHRASE_PATTERNS` 60 余条全是 `delve into` / `a testament to` / `rich tapestry` 这类英文套话。

本仓库重写后同一段文本得 **0.9112 / high**。中文规则按"字当量"切词，按 `。！？；…` 切句，特征词分 9 组、权重 0.4–1.5，并新增段落长度 CV（中文 AI 最稳定的特征是**每段长度过于接近**，而不是句长）。刻意不收录"核心""关键""重要""问题""影响""实现""提升"——它们在真实专业文本里是实义词，收了只会误报。

## 7 轮流程

| 轮次 | 检查内容 | 目标 |
|---|---|---|
| 1 | Markdown 清理 | 删掉加粗、列表符、标题符、代码块、引用块 |
| 2 | 套话清理 | 删掉"综上所述""随着……不断发展"类开头结尾 |
| 3 | 段落节奏 | 长段拆短、短段合并、空行不规律 |
| 4 | 个人印记 | 加入"我觉得""这里有意思的是"，按文体控量 |
| 5 | **前后一致** | 术语、数据、论点数量全文自洽 |
| 6 | 可控的不完美 | 句式参差、口语插入语（错别字默认关闭） |
| 7 | 全文默读 | 找剩下卡壳的地方 |

**第 5 轮是硬约束。** 一致性不通过，无论其他几轮做得多好都不算完成。

## 两处刻意做的取舍

**1. 第 6 轮不鼓励写错别字。** 原始清单里有"加入少量不完美（错别字、轻微冗余）"。本仓库保留了这一轮，但把它改成"可控的不完美"：优先用句式参差、口语插入语制造呼吸感；错别字仅在非正式载体、用户明确要求、非关键概念三个条件同时满足时才启用，且正式公文、学术论文、商业文档一律禁用。

理由：AI 痕迹是"读起来像机器"，错别字是"看起来不专业"。用后者换前者通常不划算。

**2. 一致性优先于自然度。** 原版有些规则（模糊归因、虚假范围）靠弱化表述实现，会跟一致性检查打架。本仓库明确规定：宁可保留一句看起来不够自然的重复措辞，也不能让同一个概念有两种叫法。没有例外。

## 可脚本化程度

**已实现为确定性规则（`scripts/`）：**
- 中文 AI 特征词打分（9 组词表 + 密度 + 段落 CV + 句长 CV）
- 零宽字符 / BOM / word joiner / NBSP / 双向控制符的检测与清理
- OOXML（docx/xlsx/pptx）文档属性清洗：作者、最后修改者、说明、应用程序名、模板默认时间戳
- 回归校验：哈希、分数、汉字数、专名数字白名单

**外层的规则可直接写成确定性规则（词表/字符计数）：**
- Markdown 残留 `**` `` ` `` `>` `-` `1.` —— 纯正则
- 破折号变体 `——` `—` `--` ` - ` —— 正则

**需要语义理解，只能交给模型：**
内容层的全部条目。它们的本质是"内容空洞"或"刻意为之"，无法靠字面命中数判定。

**适合标记待人工确认：**
三段式并列、论点数量一致性。脚本能数"这里有几项"，但判断"是否强凑"要人来。

## 已知边界

- **pdf 只做元数据，不改正文。** 重排正文要吃中文字体子集，会留下字体回退、字距不匀、行尾溢出，视觉损伤大于 AI 味本身。要改文字请找回源文件重导出
- **pdf 元数据清理暂未实现**，本机 Python 环境没有 pikepdf / PyMuPDF
- **Excel 不做句子级改写**，只做元数据清洗 + 纯文本单元格删填充词
- 打分器对**少于 120 汉字**的样本返回 `uncalibrated`

## 安装

复制整个目录到 Agent 的 skills 目录即可。以 DSH 为例：

```
%APPDATA%\dsh-desktop\harness\skills\zk-noai-zh\
```

目录内需包含 `SKILL.md`、`references/`、`scripts/`。

Windows 下跑脚本前建议设 `$env:PYTHONIOENCODING = "utf-8"`，否则中文输出乱码。

## 修订记录

- **2.1** 融合 watermarks-remover：新增 `scripts/` 流水线（4 个上游脚本原样 + 自写的中文打分器与元数据清洗）；SKILL.md 新增脚本化流水线章节与"先判断值不值得改"
- **2.0** 重命名为 zk-noai-zh；重构为 7 轮流程；新增一致性硬约束、文体豁免、可控不完美
- **1.x** 继承 humanizer-zh，含第 7b 条中文 AI 表达、第 13 条中文破折号变体
