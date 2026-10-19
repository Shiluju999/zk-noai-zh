# 上游来源记录

本仓库是的本地分叉，用于按个人使用习惯持续修改，**不与上游自动同步**。

## 来源

| 项目 | 值 |
|---|---|
| 上游仓库 | https://github.com/op7418/Humanizer-zh |
| 上游 commit | `91f3d394db8419c20d67e22a96cf8fee0a404b` |
| 本地快照时间 | 2026-08-17 |
| 快照文件 | `SKILL.md`（19382 B，484 行）、`LICENSE`（1084 B） |

`SKILL.md` 快照 SHA256：

```
35ECA1B1A5D313B7EBCD2236670831C2E5F13920B8259208EEB3CFAD94685FA0
```

## 更上游的血统

| 层级 | 来源 |
|---|---|
| 英文原始版 | [blader/humanizer](https://github.com/blader/humanizer) |
| 实用工具部分 | [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) |
| 内容依据 | [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)，由 WikiProject AI Cleanup 维护 |

## 许可

MIT License，Copyright (c) 2026 歸藏。MIT 允许复制、修改、合并、发布、再许可和销售，唯一义务是**保留原始版权声明和许可声明**。

`LICENSE` 文件原样保留，未做修改。本仓库的衍生修改在 MIT 下同样宽松，不强制开源要求。

## 未采纳的文件

以下文件存在于原始技能目录，但**未复制**：

| 文件 | 原因 |
|---|---|
| `.skills-hub-cache.json` | 技能同步机制的缓存（含 `last_fetched_ms` 与 `head` 字段）。保留会导致本地修改被上游同步覆盖，与"本地分叉"定位冲突 |
| `README.md` | 原文是给 Claude Code 用户看的安装说明（含 `/humanizer-zh` 斜杠命令、`~/.claude/skills/` 路径等），与本仓库定位不符，已重写为 `README.md` |
| `.gitignore` | 内容为 `.DS_Store`、`*.swp`、`.vscode/` 等编辑器杂项，已并入新 `.gitignore` |

## 已知的上游问题与处理状态

以下问题在快照中**原样存在**，本仓库的处理情况如下：

| # | 问题 | 状态 |
|---|---|---|
| 1 | **规则自相矛盾**：第 13 条要求去除破折号，但 L76 的"改写后"示例 `真相可能在无聊的中间某处——但我一直在想那些通宵工作的智能体` 自身就使用了破折号，违反第 4 条与第 13 条 | ✅ 已修（改为句号） |
| 2 | **中文无效规则占位**：第 16 条（标题全词大写）、第 18 条（弯引号）在中文场景下无实际判定力 | ⚠️ 部分处理：第 18 条已移除（编号 18 保留为占位，内容替换为移除说明，不重排后续编号）；第 16 条保留（自带"中文中不太适用"注释，且编号用于外部引用） |
| 3 | **无阈值定义**：第 7 条标题为"过度使用的 AI 词汇"，但全文未定义"过度"的密度标准 | ⬜ 未处理（待做） |
| 4 | **缺少中文特征**：未收录"综上所述"、"随着……的不断发展"、"赋能"、"助力"等高频中文 AI 表达式 | ✅ 已修（新增第 7b 条"中文高频 AI 表达"，按功能分 5 组） |
| 5 | **音译继承**：判定标准源自英文语料归纳，直接套用中文会误判正常书面语 | ⚠️ 部分处理：第 7b 条内含"注意区分文体"说明；第 7 条本体未改 |

## 第二个上游：wsylvest/watermarks-remover

`scripts/` 下四个隐形字符脚本来自此处。

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/wsylvest/watermarks-remover（guillaumemeyer/watermarks-remover 的镜像） |
| 上游 commit | `258cf20cdc2906e24398b3d6f3bc3cbcfd578245`（2026-09-26） |
| 版本 | 0.7.0 |
| 许可 | MIT License, Copyright (c) 2026 Guillaume Meyer and contributors |

**原样收进、一字未改的四个脚本**（SHA256 已核）：

| 文件 | 字节 | SHA256 前 16 位 |
|---|---|---|
| `scripts/inspect_text.py` | 4688 | `2D89ECD6F4C60759` |
| `scripts/clean_text.py` | 3207 | `DA12C0A72C18503C` |
| `scripts/text_unicode.py` | 25840 | `97330BA39B82C6D0` |
| `scripts/common.py` | 21812 | `F4DD114EA676D7AB` |

**不要就地修改这四个文件**，上游同步会覆盖。要改行为请改 `deai.py` 或在外面包一层。

### 为什么没有原样搬 `score_stylometry.py`

它只认英文，对中文完全失效。同一段 446 字中文 AI 腔文本（含 赋能/助力/抓手/闭环/范式转变/综上所述/值得注意的是）跑出来是：

```
word_count=33（实际 413 个汉字）、sentence_count=1（实际 9 句）、
burstiness_cv=None、ai_ngram_density=0.0、matched_markers=[]、score=0.0077、tier=low
```

根因在源码：

- `service/scripts/score_stylometry.py:142`：`RE_WORDS = re.compile(r"\b[\w'-]+\b", re.UNICODE)` —— 中文无空格，整段成一个 token
- `score_stylometry.py:217`：`chunks = re.split(r"(?<=[.!?])\s+|\n+", raw_text)` —— 不认 。！？
- `AI_PHRASE_PATTERNS`（第 40-139 行）60 余条全英文：`delve into` / `a testament to` / `rich tapestry` / `plays a pivotal role` / `it is important to note`

所以 `scripts/score_stylometry.py` 是**本地重写**的，但为了不动 `inspect_text.py` 一行代码，**保留上游的类名、函数签名和 `to_dict()` 字段**：

- `MarkerMatch`、`StylometryReport` dataclass
- `score_text_stylometry(text, path) -> StylometryReport`
- `print_human_stylometry_report(report, explain=False)`
- `word_count` 字段名保留，中文语境下表示"字当量"（汉字数 + 西文串数）

### 也没有搬 `container_meta.py`

上游那份 4548 行，模块顶部 import 了 `av_meta`、`image_meta`、`inspect_png` 等一长串同目录模块，搬进来会拖出整个 service 依赖链；真正和 docx 相关的只有几十行。`scripts/meta_docx.py` 是重写的，只依赖 `zipfile` 和 `re`。

但保留了上游的设计与它踩过的坑：

| 规则 | 来源 | 原因 |
|---|---|---|
| 清 `dc:creator` 等 9 个字段 | 上游 `DOCX_SCRUB_FIELDS` | 作者/最后修改者/说明/关键词/主题/类别/应用程序/公司/经理 |
| **不清 `dc:title`** | 上游判断 | 是文档标题，不是生成痕迹 |
| **不清 `AppVersion`** | 上游 issue #283 | ECMA-376 Part 1 §15.2.12.1 要求匹配 `\d+\.\d{4}`，清空会让 Word 报"内容有问题" |
| 二进制部件字节保持 | 上游 issue #312 | 按 UTF-8 解码再编码会把字节变成 U+FFFD |
| **customXml 不无脑删** | 本仓库新增 | Word 参考文献库（`b:Sources`、"插入引文"）存在这里，删了丢用户引用数据。只删空壳，有内容的保留并报告 |
| 模板时间戳改当前时间 | 本仓库新增 | python-docx 固定写 `2013-12-23T23:15:00Z`，几十万份文件一模一样，是极显眼的批量生成指纹 |

## 本地修改记录

### 2026-08-17 第一批

- **第 13 条示例修正**：L76 "改写后"示例中的破折号改为句号，消除规则自相矛盾。
- **第 18 条移除**：弯引号在中文场景无判定力，整条替换为移除说明。**编号保留不重排**，避免破坏外部对"第 18 条"的引用；总条目数仍为 24。
- **新增第 7b 条"中文高频 AI 表达"**：按功能分为总结收束类、趋势铺陈类、抽象赋能类、判断强化类、递进套话类 5 组，含改写前后示例与 5 条改写要点。
- **第 13 条补中文变体**：原规则只提 `—`，补充 `——`、`—`、`--`、` - ` 四种需要检测的形式，并给出替换策略（按语义选逗号/分号/句号，不一律删成句号）。

**注意**：第 13 条、完整示例中的"改写前"段落**刻意保留破折号作为反例**，不是遗漏，不要改。

### 2026-10-19 第二批：融合 watermarks-remover

- **新增 `scripts/` 目录**：4 个上游脚本原样收录（SHA256 已核，见上文）；`score_stylometry.py` 中文重写；`meta_docx.py` 本地自写；`deai.py` 统一流水线入口。
- **SKILL.md 新增「脚本化流水线」章节**：六步命令、为什么元数据必须最后做、为什么回归校验不能靠自我复读、打分器怎么读、**先判断值不值得改**。
- **SKILL.md 新增「已知边界」**：pdf 只做元数据不改正文（字体子集死结）、Excel 不做句子级改写、短文本不打分。
- **README 更新**：文件结构表、脚本流水线、中文打分器的根因说明、修订记录。

**实测踩到并修掉的三个坑**（写在这里防止回退）：

1. `clean_text()` 返回 `tuple[str, dict]`，不是字符串。第一版用 `getattr(cleaned, "text", "")` 取到空串，把整篇正文删光（19 字符 → 0）。现在会解包元组，并加了「正文被删掉一半以上就拒绝写入」的防呆。
2. `compute_paragraph_cv` 把表格单元格当段落算。136 个单元格混进 58 个段落，段落 CV 从 0.803 虚高到 1.543，纯统计假信号。`deai.py` 现在打分只喂正文段落（`include_tables=False`）。
3. `[Content_Types].xml` 的 override 不能无条件摘——只有真正删掉部件时才能摘，否则造出「override 没了、部件还在」的 OPC 结构不一致。Word 能容忍，严格校验器和 LibreOffice 转换会报错。
