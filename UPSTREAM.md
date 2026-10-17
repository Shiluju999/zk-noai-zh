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

## 已知的上游问题（供本地修改参考）

这些问题在快照中**原样存在**，未在本次复制时修改：

1. **规则自相矛盾**：第 13 条要求去除破折号，但 L76 的"改写后"示例 `真相可能在无聊的中间某处——但我一直在想那些通宵工作的智能体` 自身就使用了破折号，违反第 4 条与第 13 条。
2. **中文无效规则占位**：第 16 条（标题全词大写）标注"中文中不太适用"，第 18 条（弯引号）标注"中文通常使用「」"，两条在中文场景下无实际判定力，但占用编号。
3. **无阈值定义**：第 7 条标题为"过度使用的 AI 词汇"，但全文未定义"过度"的密度标准；检查清单 L414 用"考虑删除"而非确定性规则。
4. **缺少中文特征**：未收录"综上所述"、"随着……的不断发展"、"赋能"、"助力"等高频中文 AI 表达式。
5. **音译继承**：判定标准源自英文语料归纳，直接套用中文会误判正常书面语（如"此外"在中文公文里是常规连接词，并非 AI 特征）。
