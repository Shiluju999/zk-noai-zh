#!/usr/bin/env python3
"""Zero-LLM stylometric AI-text scorer — **中文适配版**。

本文件是对 wsylvest/watermarks-remover ``service/scripts/score_stylometry.py``
的**接口兼容重写**。上游 ``inspect_text.py`` 通过
``from score_stylometry import print_human_stylometry_report, score_text_stylometry``
导入本模块，所以这里的类名、函数签名、``to_dict()`` 字段必须与上游保持一致。

与上游的差异（为什么必须重写）
--------------------------------
上游那套打分器为英文设计，直接跑中文会系统性失效，实测数据：

    输入 446 字中文 AI 腔文本（含 赋能/助力/抓手/闭环/范式转变/综上所述…）
    输出 word_count=33（实际 413 个汉字）
         sentence_count=1（实际 9 个句子）
         ai_ngram_density=0.0，matched_markers=[]（一个特征词都没认出）
         score=0.0077  →  density_tier="low"（判为人写）

根因在源码里：
    RE_WORDS = re.compile(r"\\b[\\w'-]+\\b", re.UNICODE)   # 中文无空格，整段成 1 个 token
    re.split(r"(?<=[.!?])\\s+|\\n+", raw_text)             # 不认 。！？，整篇成 1 句
    AI_PHRASE_PATTERNS = (delve into, a testament to, …)   # 60 余条全英文

本重写做了三件事：
1. **切句**改认中文句末标点 ``。！？；`` 与换行，同时保留英文规则（中英混排可用）
2. **计量单位**改为"CJK 汉字数"，一个汉字记 1，连续的西文/数字串也记 1，
   使 ``word_count`` 与 ``ngram_density`` 的量纲在中文下有意义
   注意：``word_count`` 字段名沿用上游以便报告兼容，中文语境下它表示「字当量」
3. **特征词表**换成中文 AI 腔词族，分七组，权重按"多强的 AI 指纹"标定

校准范围变了，读数解读也要跟着变：
    上游英文 CV 阈值 0.35 在中文并不成立。中文书面语即使人写，句长 CV 也常在
    0.5～0.8；AI 中文的典型特征是**段落长度过于接近**而非句长。所以本版把
    段落 CV 作为独立信号，并放宽句子 CV 的判定阈值。

定位：**这是量尺，不是判决。** 低分只说明"这项信号变弱了"，不证明是真人写的。

Exit codes:
  0  clean (score < threshold)
  1  suspicious / AI stylometric signals detected (score >= threshold)
  2  bad input (missing file, binary data, bad args)
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from common import (  # noqa: E402
    classify_finding_confidence,
    emit_json,
    read_text_input,
)

DEFAULT_THRESHOLD = 0.65
#: 中文有效样本下限：低于 120 字统计量不稳，不报分（对应上游的 MIN_SAMPLE_WORDS=30）
MIN_SAMPLE_CHARS = 120
#: 达到满权的字数
FULL_WEIGHT_CHARS = 400

CJK_RANGE = "\u4e00-\u9fff"
#: 中文句末 + 分号（分号在中文里常替代句号切分意群）
ZH_SENT_END = "。！？；…"
#: 句末标点之后可跟随的收尾引号/括号
ZH_TRAILING = "”』）)]】》\"'"

RE_ZH_CHAR = re.compile(rf"[{CJK_RANGE}]")
RE_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")


# ---------------------------------------------------------------------------
# 中文 AI 腔特征词表
# ---------------------------------------------------------------------------
# 权重标定原则：
#   1.5  几乎是 AI 专属，人写极少出现（「需要XX的是」句式、元话语开场）
#   1.0  高频、强 AI 指纹（赋能 / 助力 / 抓手 / 闭环 / 范式 / 综上所述）
#   0.6  中性词但被 AI 过度使用（随着 / 不断 / 进一步 / 有效 / 显著）
#   0.4  可接受但密度过高就不对的连接词（此外 / 与此同时 / 另一方面）
#
# 刻意**不收**的词：核心、关键、重要、问题、影响、实现、提升。
# 这些在真实专业文本里是实义词，收进来只会制造误报。

AI_PHRASE_PATTERNS: tuple[tuple[str, str, float], ...] = (
    # ── 组 1：总结收束（AI 最爱在结尾做的事）──
    (r"综上所述", "综上所述", 1.0),
    (r"总而言之", "总而言之", 1.0),
    (r"总的来说", "总的来说", 0.6),
    (r"通过以上(?:的)?(?:分析|讨论|论述|梳理)", "通过以上分析", 1.0),
    (r"由此可见", "由此可见", 1.0),
    (r"不难看出", "不难看出", 1.0),
    # ── 组 2：趋势铺陈（开头几乎必中）──
    (r"在当今[^，。]{0,12}?(?:背景下|时代|形势下)", "在当今……背景下", 1.4),
    (r"随着[^，。]{0,20}?(?:的)?(?:不断发展|深入推进|快速演进|持续升级)", "随着……的不断发展", 1.3),
    (r"在(?:当前|新的)[^，。]{0,10}?(?:背景下|形势下|格局下)", "在当前……背景下", 1.1),
    (r"近年来[，,]?\s*随着", "近年来随着", 1.0),
    (r"日新月异", "日新月异", 0.9),
    (r"前所未有(?:的)?(?:速度|程度|机遇|挑战|发展)", "前所未有的……", 0.9),
    # ── 组 3：抽象赋能（最强的中文 AI 指纹）──
    (r"赋能", "赋能", 1.4),
    (r"助力", "助力", 1.3),
    (r"抓手", "抓手", 1.4),
    (r"闭环", "闭环", 1.3),
    (r"范式(?:转变|转移|转换|革命|创新)", "范式转变", 1.2),
    (r"全链路|全链条贯通|端到端打通", "全链路/端到端", 1.1),
    (r"打通[^，。]{0,8}?(?:壁垒|堵点|断点|最后一公里)", "打通壁垒/堵点", 1.1),
    (r"(?:深度|高度|有机)(?:融合|耦合|协同|结合)", "深度融合/耦合", 0.9),
    (r"多维(?:度)?(?:赋能|协同|融合)", "多维度赋能", 1.0),
    (r"生态(?:体系|闭环|构建|伙伴)", "生态体系/生态闭环", 0.8),
    # ── 组 4：判断强化（"需要XX的是"句式家族 —— 单点最像 AI 的中文结构）──
    (r"需要(?:指出|说明|强调|注意|提醒|明确|承认|清醒认识|主动交代|特别说明|进一步说明)(?:的)?是", "需要XX的是", 1.5),
    (r"值得(?:注意|强调|关注|一提|深思)(?:的)?是", "值得XX的是", 1.4),
    (r"必须(?:指出|承认|强调)(?:的)?是", "必须指出的是", 1.3),
    (r"不容忽视(?:的)?是", "不容忽视的是", 1.2),
    (r"不可否认(?:的)?是", "不可否认的是", 1.2),
    (r"显而易见", "显而易见", 0.9),
    (r"众所周知", "众所周知", 1.3),
    # ── 组 5：递进套话与连接词堆砌 ──
    (r"不仅[^。！？]{0,40}?而且", "不仅……而且", 0.7),
    (r"不仅[^。！？]{0,40}?更是", "不仅……更是", 0.9),
    (r"既[^。！？]{0,30}?又[^。！？]{0,30}?", "既……又……", 0.5),
    (r"在[^，。]{0,12}?的同时", "在……的同时", 0.7),
    (r"进一步(?:提升|加强|深化|完善|优化|推动)", "进一步XX", 0.7),
    (r"与此同时", "与此同时", 0.6),
    (r"此外[，,]", "此外，", 0.4),
    (r"另一方面[，,]", "另一方面，", 0.4),
    (r"首先[，,][^。]{0,60}?其次[，,]", "首先……其次……", 0.8),
    (r"其一[，,][^。]{0,60}?其二[，,]", "其一……其二……", 0.6),
    # ── 组 6：模糊归因（无出处的"研究说"）──
    (r"(?:多项|大量|众多|诸多)(?:研究|文献|实践|案例)(?:表明|显示|证明|证实|发现)", "多项研究表明", 1.1),
    (r"(?:研究|数据|实践|事实)(?:表明|显示|证明)[，,]?", "研究表明", 0.7),
    (r"据(?:统计|了解|悉|报道)", "据统计/据了解", 0.8),
    (r"有(?:学者|专家|研究者|业内人士)(?:指出|认为|表示|强调)", "有学者指出", 1.0),
    (r"(?:在一定|某种)(?:程度|意义)上", "在一定程度上", 0.6),
    # ── 组 7：程度副词灌水 ──
    (r"(?:极大|显著|大幅)地?(?:提升|提高|改善|增强|促进|推动)", "极大地提升", 0.9),
    (r"有效(?:地)?(?:提升|促进|推动|解决|保障|赋能)", "有效提升", 0.8),
    (r"高度(?:重视|关注|契合|一致)", "高度重视", 0.6),
    (r"(?:至关|尤为)(?:重要|关键)", "至关重要", 0.7),
    (r"全面(?:提升|推进|深化|构建|落实)", "全面提升", 0.6),
    (r"持续(?:发力|深耕|赋能|演进|优化)", "持续发力/深耕", 1.0),
    # ── 组 8：翻译腔 / 书面腔（中文 AI 常见搭配）──
    (r"进行(?:了)?(?:一个|一次)[^，。]{0,6}?(?:的过程|的工作)", "进行了……的过程", 1.0),
    (r"对于[^，。]{0,10}?而言", "对于……而言", 0.6),
    (r"呈现出[^，。]{0,10}?的(?:特征|态势|趋势|状态)", "呈现出……的特征", 0.8),
    (r"具有(?:一定的|很强的|较高的)[^，。]{0,6}?性", "具有一定的XX性", 0.9),
    (r"起到了?[^，。]{0,10}?的(?:作用|效果)", "起到了……的作用", 0.7),
    (r"被认为是[^，。]{0,20}?的(?:重要|关键)", "被认为是……的重要", 0.5),
    # ── 组 9：元话语（讲「本文要做什么」而不是直接做）──
    (r"本文(?:将|拟|旨在|试图|通过|从[^，。]{0,8}?角度)", "本文将/本文旨在", 0.9),
    (r"下面(?:将|我们)?(?:从|就|对)[^，。]{0,12}?(?:展开|阐述|分析|介绍|讨论)", "下面将从……展开", 1.1),
    (r"(?:笔者|作者)认为", "笔者认为", 0.5),
)


@dataclass
class MarkerMatch:
    phrase: str
    count: int
    weight: float
    samples: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)  # start/end char offsets

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase": self.phrase,
            "count": self.count,
            "weight": self.weight,
            "samples": self.samples,
            "spans": [list(s) for s in self.spans],
        }


@dataclass
class StylometryReport:
    """与上游 ``StylometryReport`` 字段完全一致，额外增加中文专用字段。

    ``word_count`` 在中文语境下表示「字当量」（汉字数 + 西文串数），
    字段名保留是为了不破坏上游 ``inspect_text.py`` 与报告消费方。
    """

    path: str
    word_count: int
    sentence_count: int
    burstiness_cv: float | None
    lexical_diversity: float
    ai_ngram_density: float
    matched_markers: list[dict[str, Any]]
    score: float | None
    confidence_level: str | None  # CLEAN | LOW | MEDIUM | HIGH, or None when uncalibrated
    density_tier: str  # low | medium | high, or uncalibrated when not scored
    status: str  # ok | insufficient_length
    findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # ── 中文专用补充字段（上游没有，消费方可忽略）──
    cjk_char_count: int = 0
    paragraph_count: int = 0
    paragraph_cv: float | None = None
    markers_by_group: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
            "burstiness_cv": round(self.burstiness_cv, 4)
            if self.burstiness_cv is not None
            else None,
            "lexical_diversity": round(self.lexical_diversity, 4),
            "ai_ngram_density": round(self.ai_ngram_density, 4),
            "matched_markers": self.matched_markers,
            "score": round(self.score, 4) if self.score is not None else None,
            "confidence_level": self.confidence_level,
            "density_tier": self.density_tier,
            "status": self.status,
            "findings": self.findings,
            "findings_confidence": [classify_finding_confidence(f) for f in self.findings],
            "notes": self.notes,
            # 中文专用
            "cjk_char_count": self.cjk_char_count,
            "paragraph_count": self.paragraph_count,
            "paragraph_cv": round(self.paragraph_cv, 4)
            if self.paragraph_cv is not None
            else None,
            "markers_by_group": self.markers_by_group,
        }


# ---------------------------------------------------------------------------
# 分词与切句
# ---------------------------------------------------------------------------


def extract_sentences(text: str) -> list[str]:
    """切句：中文认 。！？；… 与换行，英文认 .!? —— 中英混排都能用。

    同时跳过 Markdown 代码块与空行（沿用上游行为）。
    """
    clean_lines: list[str] = []
    in_code_block = False
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not trimmed:
            continue
        clean_lines.append(trimmed)

    raw_text = "\n".join(clean_lines)
    if not raw_text.strip():
        return []

    # 在中文句末标点后切；英文句末标点后必须跟空白才切（避免切开 3.5 这种小数）
    marks = re.escape(ZH_SENT_END)
    trail = re.escape(ZH_TRAILING)
    pattern = rf"(?<=[{marks}])[{trail}]*|(?<=[.!?])\s+|\n+"
    chunks = re.split(pattern, raw_text)
    return [s.strip() for s in chunks if s and s.strip()]


def extract_words(text: str) -> list[str]:
    """「字当量」切分：每个汉字算 1，每段连续西文/数字算 1。

    这样中文文本的 word_count 才与字数量级相符，MATTR 与 ngram_density 也才有意义。
    用于 MATTR 时返回的是 token 列表（汉字逐个、西文串整体）。
    """
    tokens: list[str] = []
    buf: list[str] = []
    for ch in text:
        if RE_ZH_CHAR.match(ch):
            if buf:
                tokens.append("".join(buf).lower())
                buf = []
            tokens.append(ch)
        elif ch.isalnum() or ch in "'-":
            buf.append(ch)
        else:
            if buf:
                tokens.append("".join(buf).lower())
                buf = []
    if buf:
        tokens.append("".join(buf).lower())
    return tokens


def count_cjk_chars(text: str) -> int:
    """纯汉字数，用来判断样本够不够打分。"""
    return len(RE_ZH_CHAR.findall(text))


def compute_burstiness(sentences: list[str]) -> tuple[float, float, float | None]:
    """句子长度（字当量）的均值、标准差、变异系数。

    CV 为 None 表示无法测量（句子少于 2 条），不当作"极度均匀"处理。
    """
    if not sentences:
        return 0.0, 0.0, None

    lengths = [len(extract_words(s)) for s in sentences]
    lengths = [x for x in lengths if x > 0]
    if len(lengths) < 2:
        return (float(lengths[0]) if lengths else 0.0), 0.0, None

    mean_len = sum(lengths) / len(lengths)
    variance = sum((x - mean_len) ** 2 for x in lengths) / (len(lengths) - 1)
    std_dev = math.sqrt(variance)
    cv = (std_dev / mean_len) if mean_len > 0 else 0.0
    return mean_len, std_dev, cv


def compute_paragraph_cv(text: str) -> tuple[int, float | None]:
    """段落长度的变异系数。

    中文 AI 输出最稳定的特征不是句长均匀，而是**每段都三四行、长度高度接近**。
    人写的长文段落长短差得很大。
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    lengths = [len(extract_words(p)) for p in paras]
    lengths = [x for x in lengths if x >= 5]  # 标题、单字行不参与
    if len(lengths) < 4:
        return len(paras), None
    mean_len = sum(lengths) / len(lengths)
    variance = sum((x - mean_len) ** 2 for x in lengths) / (len(lengths) - 1)
    std = math.sqrt(variance)
    return len(paras), (std / mean_len if mean_len > 0 else 0.0)


def compute_mattr(words: list[str], window_size: int = 50) -> float:
    """滑动窗口型例比（MATTR），衡量词汇多样性。中文用字当量窗口。"""
    n = len(words)
    if n == 0:
        return 0.0
    if n <= window_size:
        return len(set(words)) / n

    total_ttr = 0.0
    num_windows = n - window_size + 1
    current_window = Counter(words[:window_size])
    total_ttr += len(current_window) / window_size

    for i in range(1, num_windows):
        leaving = words[i - 1]
        entering = words[i + window_size - 1]
        current_window[leaving] -= 1
        if current_window[leaving] == 0:
            del current_window[leaving]
        current_window[entering] += 1
        total_ttr += len(current_window) / window_size

    return total_ttr / num_windows


# ---------------------------------------------------------------------------
# 特征词扫描
# ---------------------------------------------------------------------------

_COMPILED_PATTERNS = tuple(
    (re.compile(pat), label, weight) for pat, label, weight in AI_PHRASE_PATTERNS
)


def scan_ai_phrases(text: str) -> list[MarkerMatch]:
    """扫描中文字面 AI 特征词，返回命中详情（含量、权重、位置）。"""
    results: list[MarkerMatch] = []
    for regex, label, weight in _COMPILED_PATTERNS:
        spans: list[tuple[int, int]] = []
        samples: list[str] = []
        for m in regex.finditer(text):
            spans.append((m.start(), m.end()))
            if len(samples) < 3:
                lo = max(0, m.start() - 12)
                hi = min(len(text), m.end() + 12)
                samples.append(text[lo:hi].replace("\n", " "))
        if spans:
            results.append(
                MarkerMatch(phrase=label, count=len(spans), weight=weight, samples=samples, spans=spans)
            )
    # 按「命中次数 × 权重」降序，最重要的排前面
    results.sort(key=lambda x: x.count * x.weight, reverse=True)
    return results


def classify_density(score: float | None) -> str:
    """把总分映射成「要不要动手改」的档位。

    high  → 达到可疑阈值，应当进入改写轮次
    medium→ 信号中等，先核对再决定
    low   → 信号弱，验证即可，不要硬改
    """
    if score is None:
        return "uncalibrated"
    if score >= DEFAULT_THRESHOLD:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# 主评分
# ---------------------------------------------------------------------------


def score_text_stylometry(text: str, path: str = "<text>") -> StylometryReport:
    """跑完整的多维打分，返回结构化报告。"""
    tokens = extract_words(text)
    token_count = len(tokens)
    cjk_count = count_cjk_chars(text)
    sentences = extract_sentences(text)
    sentence_count = len(sentences)
    para_count, para_cv = compute_paragraph_cv(text)

    findings: list[str] = []
    notes: list[str] = []

    marker_matches = scan_ai_phrases(text)
    by_group: dict[str, int] = {}
    for m in marker_matches:
        by_group[m.phrase] = m.count

    # ── 长度门槛 ──
    # 中文按汉字数判定，不按西文 token 数
    if cjk_count < MIN_SAMPLE_CHARS:
        for m in marker_matches:
            findings.append(f"中文 AI 特征词「{m.phrase}」命中 {m.count} 次")
        notes.append(
            f"样本仅 {cjk_count} 个汉字，低于 {MIN_SAMPLE_CHARS} 字的统计下限，"
            f"不给总分；特征词扫描结果仍然有效"
        )
        return StylometryReport(
            path=path,
            word_count=token_count,
            sentence_count=sentence_count,
            burstiness_cv=None,
            lexical_diversity=compute_mattr(tokens),
            ai_ngram_density=0.0,
            matched_markers=[m.to_dict() for m in marker_matches],
            score=None,
            confidence_level=None,
            density_tier="uncalibrated",
            status="insufficient_length",
            findings=findings,
            notes=notes,
            cjk_char_count=cjk_count,
            paragraph_count=para_count,
            paragraph_cv=para_cv,
            markers_by_group=by_group,
        )

    _, _, cv = compute_burstiness(sentences)
    mattr = compute_mattr(tokens)

    # 特征词密度：每 100 汉字的加权命中数
    total_weight = sum(m.count * m.weight for m in marker_matches)
    density = (total_weight / (token_count / 100.0)) if token_count > 0 else 0.0

    # ── 分量 1：句子节奏 ──
    # 中文阈值比英文宽：人写中文书面语 CV 常在 0.5～0.8，AI 常在 0.3～0.5
    # 所以 0.35 不能直接照搬，这里用 0.30/0.40/0.50/0.60 分档
    if cv is None:
        burst_score: float | None = None
    elif cv < 0.30:
        burst_score = 0.95
    elif cv < 0.40:
        burst_score = 0.75
    elif cv < 0.50:
        burst_score = 0.45
    elif cv < 0.60:
        burst_score = 0.20
    else:
        burst_score = 0.05

    # ── 分量 2：特征词密度 ──
    # 中文 AI 腔密度普遍高于英文（「众所周知」「综上所述」这类是成句出现的）
    if density >= 2.0:
        ngram_score = 1.0
    elif density >= 1.2:
        ngram_score = 0.80
    elif density >= 0.6:
        ngram_score = 0.55
    elif density > 0:
        ngram_score = 0.25
    else:
        ngram_score = 0.0

    # ── 分量 3：段落均匀度（中文的强信号）──
    # AI 爱写等长段落；人写长文段落长度参差
    para_score: float | None = None
    if para_cv is not None:
        # 中文阈值比英文宽：AI 中文段落 CV 常在 0.30～0.50，
        # 人写长文档则在 0.60 以上。照搬英文的 0.35 会把正常文档打成 AI。
        if para_cv < 0.28:
            para_score = 0.85
        elif para_cv < 0.42:
            para_score = 0.60
        elif para_cv < 0.58:
            para_score = 0.30
        else:
            para_score = 0.05

    # ── 分量 4：词汇多样性 ──
    # 中文 MATTR 的解释与英文不同（汉字重复率高是常态），权重压到 0.10
    diversity_score = 0.35 if 0.55 <= mattr <= 0.72 else 0.10

    # ── 合成 ──
    parts: list[tuple[float, float]] = []  # (分值, 权重)
    if burst_score is not None:
        parts.append((burst_score, 0.35))
    else:
        notes.append("句子节奏不可测（解析出的句子不足 2 条），该项从合成中剔除并重新归一化")
    parts.append((ngram_score, 0.40))
    if para_score is not None:
        parts.append((para_score, 0.15))
    else:
        notes.append("段落长度不可测（有效段落不足 4 段），段落项不参与合成")
    parts.append((diversity_score, 0.10))

    weight_sum = sum(w for _, w in parts)
    raw = sum(v * w for v, w in parts) / weight_sum if weight_sum > 0 else 0.0

    # ── 特征词地板 ──
    # 为什么需要这条：节奏类信号（句长 CV、段长 CV）可以被人为打散，
    # 而字面特征词不会因为句式参差就消失。实测一篇 3765 字的真文档，
    # 即使 4 处「需要XX的是」+「闭环」全部命中，句长 CV=0.68、段长 CV=0.80
    # 仍把它压到 0.135（CLEAN），说明节奏分量的权重足以掩盖字面证据。
    # 所以：特征词密度一旦越过档位线，给总分设下限，不让节奏项把它拉回来。
    # 这不是加分，是防止其他分量稀释已经确证的字面证据。
    floor_by_density = 0.0
    if density >= 2.0:
        floor_by_density = 0.70
    elif density >= 1.2:
        floor_by_density = 0.58
    # 0.6 档故意不设地板。实测一篇 3765 字的正常文档，4 处「需要XX的是」
    # 却只有 0.25/100 字的密度——中文里单条特征词就是很稀疏，密度低不一定
    # 是好事，也可能是长度稀释。0.6 这一档留给节奏分量自己说话。
    floor_applied = raw < floor_by_density
    raw = max(raw, floor_by_density)

    # 稠密度惩罚：特征词出现得太密（≥3.0/100 字）时，节奏分量若还很均匀，
    # 那就是"打散了句长但套话没删"的典型改写痕迹，直接加重。
    if density >= 3.0 and burst_score is not None and burst_score >= 0.45:
        raw = min(1.0, raw + 0.12)
        notes.append(
            "特征词密度极高且句子节奏仍偏均匀，符合「只改句式未清套话」的特征，总分加重 0.12"
        )

    # ── 样本长度阻尼：120 字起 0.4 倍，400 字满权 ──
    if cjk_count < FULL_WEIGHT_CHARS:
        dampener = 0.4 + 0.6 * (
            (cjk_count - MIN_SAMPLE_CHARS) / (FULL_WEIGHT_CHARS - MIN_SAMPLE_CHARS)
        )
        dampener = max(0.4, min(1.0, dampener))
        notes.append(
            f"样本 {cjk_count} 字处于校准区间（{MIN_SAMPLE_CHARS}～{FULL_WEIGHT_CHARS}），"
            f"总分按 {dampener:.2f} 阻尼"
        )
    else:
        dampener = 1.0

    final_score = min(1.0, max(0.0, raw * dampener))

    # ── 结论清单 ──
    if marker_matches:
        for m in marker_matches[:12]:
            findings.append(f"中文 AI 特征词「{m.phrase}」命中 {m.count} 次（权重 {m.weight}）")

    if cv is not None and cv < 0.40 and sentence_count >= 5:
        findings.append(f"句子节奏过于均匀（CV={cv:.2f} < 0.40）")
    if para_cv is not None and para_cv < 0.40 and para_count >= 6:
        findings.append(f"段落长度过于接近（CV={para_cv:.2f} < 0.40），这是中文 AI 输出的典型特征")
    if density >= 1.2:
        findings.append(f"AI 套话密度偏高（每百字 {density:.2f} 加权命中）")
    if floor_applied:
        notes.append(
            f"特征词密度 {density:.2f}/100 字越过档位线，总分设下限 {floor_by_density:.2f}"
            f"——节奏类信号（句长/段长参差）不足以为此抵消"
        )

    if final_score >= 0.75:
        confidence = "HIGH"
    elif final_score >= 0.50:
        confidence = "MEDIUM"
    elif final_score >= 0.25:
        confidence = "LOW"
    else:
        confidence = "CLEAN"

    return StylometryReport(
        path=path,
        word_count=token_count,
        sentence_count=sentence_count,
        burstiness_cv=cv,
        lexical_diversity=mattr,
        ai_ngram_density=density,
        matched_markers=[m.to_dict() for m in marker_matches],
        score=final_score,
        confidence_level=confidence,
        density_tier=classify_density(final_score),
        status="ok",
        findings=findings,
        notes=notes,
        cjk_char_count=cjk_count,
        paragraph_count=para_count,
        paragraph_cv=para_cv,
        markers_by_group=by_group,
    )


def print_human_stylometry_report(report: StylometryReport, explain: bool = False) -> None:
    """人读报告（中文）。"""
    print(f"=== 中式风格计量报告：{report.path} ===")
    print("这是量尺，不是判决：只反映可测的字面信号，不判定作者身份。")
    print(f"状态:               {report.status}")
    print(f"信号强度:           {report.confidence_level or 'n/a'}")
    if report.score is not None:
        print(f"综合分:             {report.score * 100:.1f}%（{report.score:.3f}）")
    else:
        print("综合分:             n/a（样本太短，不打分）")
    print(f"处理档位:           {report.density_tier}")
    print(f"汉字数:             {report.cjk_char_count}")
    print(f"字当量 token:       {report.word_count}")
    print(f"句子数:             {report.sentence_count}")
    cv_disp = f"{report.burstiness_cv:.3f}" if report.burstiness_cv is not None else "n/a（不足 2 句）"
    print(f"句长 CV:            {cv_disp}")
    pcv_disp = f"{report.paragraph_cv:.3f}" if report.paragraph_cv is not None else "n/a（不足 4 段）"
    print(f"段长 CV:            {pcv_disp}（{report.paragraph_count} 段）")
    print(f"字面多样性 MATTR:   {report.lexical_diversity:.3f}")
    print(f"AI 特征词密度:      {report.ai_ngram_density:.3f} / 100 字当量")

    if report.findings:
        print("\n检出项:")
        for f in report.findings:
            print(f"  - {f}")

    if explain and report.matched_markers:
        print("\n命中明细:")
        for m in report.matched_markers:
            print(f"  * {m['phrase']}（{m['count']} 次，权重 {m['weight']}）")
            for s in m.get("samples", [])[:2]:
                print(f'    例：…{s}…')

    if report.notes:
        print("\n说明:")
        for n in report.notes:
            print(f"  * {n}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="中文风格计量打分（零模型、零网络）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("path", nargs="?", default="-", help="待打分的文本文件，- 表示 stdin")
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"触发 exit 1 的分数阈值（默认 {DEFAULT_THRESHOLD}）",
    )
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--explain", action="store_true", help="附命中明细")

    args = p.parse_args()
    text = read_text_input(args.path)

    input_label = "<stdin>" if args.path == "-" else args.path
    report = score_text_stylometry(text, path=input_label)

    if args.json:
        emit_json(report.to_dict())
    else:
        print_human_stylometry_report(report, explain=args.explain)

    if report.status == "ok" and report.score is not None and report.score >= args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
