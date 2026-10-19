#!/usr/bin/env python3
"""zk-noai-zh 统一流水线入口。

把 watermarks-remover 的隐形字符工具、本仓库自写的中文文体打分器、以及
docx/xlsx/pptx 元数据清洗串成一条命令。

六个步骤
--------
===== ============ ==========================================================
步骤  子命令       做什么
===== ============ ==========================================================
0     ``freeze``   冻结原文：算 SHA256 存档，供最后 verify 比对
1     ``layer-a``  隐形字符（零宽、BOM、NBSP）检查与清理
2     ``score``    中文 AI 特征打分（自写规则，不套用英文语料）
3     （人工）     按 SKILL.md 的 7 轮流程改写正文，模型做，脚本不管
4     ``verify``   回归检查：字数、专名、数字、特征词是否达标
5     ``meta``     文档属性清洗，**必须最后做**
===== ============ ==========================================================

为什么第 5 步必须在最后
------------------------
python-docx / Word / LibreOffice 每次存盘都会重写 ``docProps/``。第 3 步一旦
用 python-docx 改了正文再 save，之前清掉的 ``dc:creator = python-docx`` 就会被
写回来。所以只能等所有内容改动都落盘之后，再清元数据。

为什么第 4 步不能省
--------------------
SKILL.md 里写明「最后由模型自我检查」不可靠：改写者和检查者是同一个模型、
同一套偏好，检出率接近零。回归检查必须是确定性脚本，而且专名/数字白名单
零丢失要当硬门槛——那是最容易在「让文字更像人写的」过程中被悄悄抹掉的东西。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

CJK = re.compile(r"[\u4e00-\u9fff]")
#: 「专名/数字」白名单候选：拉丁词、数字、带连字符或点的编号
PROTECTED_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]*|[0-9]+(?:\.[0-9]+)?")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_docx_parts(path: str | Path) -> tuple[list[str], list[str]]:
    """抽出 docx 的（段落列表, 表格单元格列表），两者分开返回。

    为什么要分开：表格单元格通常只有几个字，如果把 136 个单元格混进 58 个
    段落里一起算「段落长度」，段落 CV 会从 0.817 虚高到 1.543——一个纯技术
    原因造成的假信号，会让人误判「这篇节奏很乱」。节奏指标只该看真正的段落。
    """
    import docx  # 延迟导入：非 docx 场景不需要

    d = docx.Document(str(path))
    paras = [p.text for p in d.paragraphs if p.text.strip()]
    cells: list[str] = []
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                if cell.text.strip():
                    cells.append(cell.text)
    return paras, cells


def read_docx_text(path: str | Path, *, include_tables: bool = True) -> str:
    """抽出 docx 正文，按阅读顺序拼接。

    ``include_tables=True`` 用于字数统计、专名数字白名单比对——那些地方表格
    里的内容同样要保护。做段落节奏/句长打分时应传 False。
    """
    paras, cells = read_docx_parts(path)
    parts = list(paras)
    if include_tables:
        parts += cells
    return "\n".join(parts)


def read_text_any(path: str | Path, *, include_tables: bool = True) -> str:
    """读文件正文：docx 走 python-docx，其余按 UTF-8 文本读。"""
    p = Path(path)
    if p.suffix.lower() == ".docx":
        return read_docx_text(p, include_tables=include_tables)
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 第 0 步：冻结
# ---------------------------------------------------------------------------


def cmd_freeze(args: argparse.Namespace) -> int:
    p = Path(args.path)
    digest = sha256_file(p)
    text = read_text_any(p)
    record = {
        "path": str(p.resolve()),
        "sha256": digest,
        "bytes": p.stat().st_size,
        "chars": len(text),
        "cjk_chars": len(CJK.findall(text)),
        "frozen_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    out = Path(args.out) if args.out else p.with_suffix(p.suffix + ".freeze.json")
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已冻结：{p.name}")
    print(f"  SHA256 : {digest}")
    print(f"  字节数 : {record['bytes']}")
    print(f"  字符数 : {record['chars']}（其中汉字 {record['cjk_chars']}）")
    print(f"  存档   : {out}")
    return 0


# ---------------------------------------------------------------------------
# 第 1 步：隐形字符
# ---------------------------------------------------------------------------


def cmd_layer_a(args: argparse.Namespace) -> int:
    from text_unicode import clean_text, inspect_text

    p = Path(args.path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    rep = inspect_text(raw)
    total = getattr(rep, "suspicious_total", 0)

    print(f"隐形字符检查：{p.name}")
    print(f"  可疑字符总数：{total}")
    found = getattr(rep, "suspicious", None) or getattr(rep, "findings", None)
    if found:
        for item in found if isinstance(found, list) else [found]:
            print(f"    - {item}")
    if total == 0:
        print("  未发现零宽/BOM/异常空白字符。")
        return 0

    if args.clean:
        # 上游签名是 clean_text(text, ...) -> tuple[str, dict]，返回 (清洗后文本, 统计)。
        # 第一版误当成返回字符串，用 getattr(cleaned, "text", "") 取到空串，
        # 结果把整篇正文删光——这种静默数据损失必须靠解包元组来杜绝。
        result = clean_text(raw, normalize_spaces=not args.no_normalize_spaces)
        if isinstance(result, tuple):
            cleaned_s, stats = result[0], (result[1] if len(result) > 1 else {})
        else:
            cleaned_s, stats = result, {}
        out = Path(args.out) if args.out else p
        if out == p and not args.in_place:
            print(f"  检测到 {total} 个可疑字符。加 --in-place 才会覆盖原文件。")
            return 1
        # 防呆：正文被删掉一半以上时拒绝写入（几乎一定是接口用错了）
        if raw and len(cleaned_s) < len(raw) * 0.5:
            print(
                f"  ❌ 拒绝写入：{len(raw)} → {len(cleaned_s)} 字符，删减超过一半。"
                "清洗只该移除不可见字符，不该动正文。"
            )
            return 2
        out.write_text(cleaned_s, encoding="utf-8")
        print(f"  已清理 → {out}（{len(raw)} → {len(cleaned_s)} 字符）")
        if stats:
            print(f"  统计：{stats}")
        return 0
    print("  加 --clean 执行清理。")
    return 1


# ---------------------------------------------------------------------------
# 第 2 步：打分
# ---------------------------------------------------------------------------


def cmd_score(args: argparse.Namespace) -> int:
    from score_stylometry import print_human_stylometry_report, score_text_stylometry

    p = Path(args.path)
    text = read_text_any(p)
    # 打分只看正文段落，表格单元格混进来会污染段落节奏指标
    style_text = read_text_any(p, include_tables=False)
    rep = score_text_stylometry(style_text, str(p))
    print_human_stylometry_report(rep, explain=args.explain)
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 第 4 步：回归检查
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    ok: bool = True
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def cmd_verify(args: argparse.Namespace) -> int:
    from score_stylometry import score_text_stylometry

    orig_path, new_path = Path(args.original), Path(args.revised)
    # 全文（含表格）用于字数与专名白名单；只看段落用于文体打分
    orig_text, new_text = read_text_any(orig_path), read_text_any(new_path)
    orig_style = read_text_any(orig_path, include_tables=False)
    new_style = read_text_any(new_path, include_tables=False)
    res = VerifyResult()

    # 0) 冻结哈希校验：防止拿旧报告验新文件
    fp = Path(args.freeze) if args.freeze else orig_path.with_suffix(orig_path.suffix + ".freeze.json")
    if fp.exists():
        rec = json.loads(fp.read_text(encoding="utf-8"))
        now = sha256_file(orig_path)
        if rec.get("sha256") != now:
            res.hard_failures.append(
                f"原文哈希不符：冻结时 {rec.get('sha256')[:16]}… 现在 {now[:16]}…（原文被改过，或验错了文件）"
            )
        else:
            res.stats["freeze_ok"] = True
    else:
        res.warnings.append(f"没找到冻结存档 {fp.name}，跳过了原文哈希校验")

    # 1) AI 特征分：必须下降或持平，不允许上升
    so = score_text_stylometry(orig_style, str(orig_path))
    sn = score_text_stylometry(new_style, str(new_path))
    so_score = so.score if so.score is not None else 0.0
    sn_score = sn.score if sn.score is not None else 0.0
    res.stats["score_before"] = round(so_score, 4)
    res.stats["score_after"] = round(sn_score, 4)
    res.stats["tier_before"] = so.density_tier
    res.stats["tier_after"] = sn.density_tier
    if sn_score > so_score + 0.02:
        res.hard_failures.append(
            f"AI 特征分上升了：{so_score:.4f} → {sn_score:.4f}（改写引入了新的 AI 特征）"
        )

    # 2) 字数变化：删套话会变短，但不能删太多（删多了说明动了实质内容）
    co, cn = len(CJK.findall(orig_text)), len(CJK.findall(new_text))
    change = cn - co            # 正数=增加，负数=减少
    shrink = -change / co if co else 0.0   # 正数=删减比例
    res.stats["cjk_before"] = co
    res.stats["cjk_after"] = cn
    res.stats["cjk_change"] = change
    res.stats["cjk_change_ratio"] = round(change / co, 4) if co else 0.0
    if shrink > args.max_shrink:
        res.hard_failures.append(
            f"删得太多：汉字 {co} → {cn}（减少 {shrink:.1%}，上限 {args.max_shrink:.0%}）。"
            "删到这个程度，很可能连实质内容一起删了"
        )
    elif change > 0:
        res.warnings.append(f"字数增加了 {change} 个汉字，确认是否加了原文没有的内容")

    # 3) 专名 / 数字白名单：**硬门槛，零丢失**
    toks_o = set(PROTECTED_TOKEN.findall(orig_text))
    toks_n = set(PROTECTED_TOKEN.findall(new_text))
    lost = sorted(toks_o - toks_n)
    # 纯数字丢失往往是被写成中文，也算丢失
    res.stats["protected_tokens_before"] = len(toks_o)
    res.stats["protected_tokens_lost"] = lost
    if lost:
        res.hard_failures.append(
            f"专名/数字丢失 {len(lost)} 项：{', '.join(lost[:20])}"
            + ("…" if len(lost) > 20 else "")
        )

    # 4) 新增特征词检查已由第 1 项覆盖；这里单独查「不该出现的机械格式」
    md_residue = re.findall(r"\*\*[^*\n]+\*\*|^\s*[-*+]\s+|^\s*#{1,6}\s+", new_text, re.M)
    stripped_prev = re.findall(r"\*\*[^*\n]+\*\*|^\s*[-*+]\s+|^\s*#{1,6}\s+", orig_text, re.M)
    if len(md_residue) > len(stripped_prev):
        res.warnings.append(
            f"Markdown 残留增加了：{len(stripped_prev)} → {len(md_residue)} 处（若载体本身不是 .md，应清干净）"
        )
    res.stats["md_residue_before"] = len(stripped_prev)
    res.stats["md_residue_after"] = len(md_residue)

    res.ok = not res.hard_failures

    if args.json:
        print(json.dumps(
            {"ok": res.ok, "hard_failures": res.hard_failures,
             "warnings": res.warnings, "stats": res.stats},
            ensure_ascii=False, indent=2))
    else:
        print(f"=== 回归检查：{orig_path.name} → {new_path.name} ===")
        print(f"  AI 特征分 : {res.stats['score_before']:.4f} ({res.stats['tier_before']})"
              f" → {res.stats['score_after']:.4f} ({res.stats['tier_after']})")
        print(f"  汉字数    : {co} → {cn}（{change:+d}，{res.stats['cjk_change_ratio']:+.1%}）")
        print(f"  专名/数字 : {len(toks_o)} → {len(toks_n)}（丢失 {len(lost)}）")
        if res.hard_failures:
            print("\n  ❌ 硬性失败：")
            for f in res.hard_failures:
                print(f"     - {f}")
        if res.warnings:
            print("\n  ⚠️  提醒：")
            for w in res.warnings:
                print(f"     - {w}")
        if res.ok:
            print("\n  ✅ 通过：特征分未上升，专名数字零丢失，删减量在阈值内。")
        else:
            print("\n  ❌ 未通过：先修上面的硬性失败项。")

    return 0 if res.ok else 1


# ---------------------------------------------------------------------------
# 第 5 步：元数据
# ---------------------------------------------------------------------------


def cmd_meta(args: argparse.Namespace) -> int:
    import meta_docx

    argv = [args.path]
    if args.clean:
        argv.append("--clean")
    if args.out:
        argv += ["-o", args.out]
    if args.drop_customxml:
        argv.append("--drop-customxml")
    if args.json:
        argv.append("--json")
    return meta_docx.main(argv)


# ---------------------------------------------------------------------------
# 汇总：一次跑完只读检查
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    """跑完 0/1/2/5 四步只读检查，给一份总览。改写（第 3 步）不在自动范围内。"""
    from score_stylometry import score_text_stylometry
    import meta_docx

    p = Path(args.path)
    print(f"{'=' * 62}")
    print(f"去 AI 化体检：{p.name}")
    print(f"{'=' * 62}")

    text = read_text_any(p)
    # 打分只看正文段落：表格单元格（常见只有几个字）混进来会把段落 CV
    # 从 0.803 虚抬到 1.372，是纯统计假信号，会让人误判「这篇节奏很乱」。
    style_text = read_text_any(p, include_tables=False)
    print(f"\n[0] 原文指纹")
    print(f"    SHA256 : {sha256_file(p)}")
    print(f"    汉字数 : {len(CJK.findall(text))}（含表格）")

    print(f"\n[2] AI 特征打分（自写中文规则）")
    rep = score_text_stylometry(style_text, str(p))
    score_s = f"{rep.score:.4f}" if rep.score is not None else "n/a"
    print(f"    分数 {score_s}  档位 {rep.density_tier}  密度 {rep.ai_ngram_density:.3f}/100字")
    if rep.status != "ok":
        print(f"    状态 {rep.status}（样本太短，分数不具参考性）")
    matched = rep.matched_markers or []
    if matched:
        seen: list[str] = []
        for m in matched:
            pat = m.get("pattern") if isinstance(m, dict) else getattr(m, "pattern", None)
            if pat and pat not in seen:
                seen.append(pat)
        if seen:
            print(f"    命中特征词 {len(seen)} 类：{', '.join(seen[:12])}"
                  + ("…" if len(seen) > 12 else ""))
    if rep.burstiness_cv is not None:
        pcv = f"{rep.paragraph_cv:.3f}" if rep.paragraph_cv is not None else "n/a"
        print(f"    句长 CV {rep.burstiness_cv:.3f}   段落 CV {pcv}")

    print(f"\n[5] 元数据")
    mr = meta_docx.inspect_file(p)
    if mr.findings:
        for f in mr.findings:
            print(f"    - {f}")
    else:
        print("    干净。")

    print(f"\n{'=' * 62}")
    print("下一步：按 SKILL.md 的 7 轮流程改写正文，改完用 verify 做回归检查，")
    print("      最后用 meta --clean 清文档属性。")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deai",
        description="zk-noai-zh 去 AI 化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  deai report doc.docx                    体检（只读）
  deai freeze doc.docx                    冻结原文哈希
  deai score  doc.txt --explain           看中文 AI 特征明细
  deai verify --original a.docx --revised b.docx    回归检查
  deai meta   b.docx --clean -o b_clean.docx       清元数据（最后做）
""",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="体检总览（0/2/5 步只读）")
    r.add_argument("path")
    r.set_defaults(func=cmd_report)

    f = sub.add_parser("freeze", help="第 0 步：冻结原文哈希")
    f.add_argument("path")
    f.add_argument("--out", help="存档路径")
    f.set_defaults(func=cmd_freeze)

    a = sub.add_parser("layer-a", help="第 1 步：隐形字符检查/清理")
    a.add_argument("path")
    a.add_argument("--clean", action="store_true", help="执行清理")
    a.add_argument("--in-place", action="store_true", help="允许覆盖原文件")
    a.add_argument("-o", "--out", help="输出路径")
    a.add_argument("--no-normalize-spaces", action="store_true", help="不动空格")
    a.set_defaults(func=cmd_layer_a)

    s = sub.add_parser("score", help="第 2 步：中文 AI 特征打分")
    s.add_argument("path")
    s.add_argument("--explain", action="store_true", help="显示逐条命中")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_score)

    v = sub.add_parser("verify", help="第 4 步：回归检查")
    v.add_argument("--original", required=True, help="原文")
    v.add_argument("--revised", required=True, help="改后版本")
    v.add_argument("--freeze", help="冻结存档路径（默认找 <原文>.freeze.json）")
    v.add_argument("--max-shrink", type=float, default=0.25,
                   help="允许的最大汉字删减比例，默认 0.25")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    m = sub.add_parser("meta", help="第 5 步：文档属性清洗（最后做）")
    m.add_argument("path")
    m.add_argument("--clean", action="store_true", help="执行清洗（默认只检查）")
    m.add_argument("-o", "--out", help="输出到新文件（默认原地覆盖并留 .bak）")
    m.add_argument("--drop-customxml", action="store_true", help="连有数据的 customXml 也删")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_meta)

    return ap


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，中文会乱码
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
