#!/usr/bin/env python3
"""
稳定的 Markdown → PDF 转换脚本。
封装 md2pdf（weasyprint）调用，统一错误处理，固化转换逻辑。

Usage:
  python scripts/md_to_pdf.py \
    --input-md "/opt/data/tmp/.../report.md" \
    --output-pdf "/opt/data/tmp/.../报告.pdf" \
    --css "references/templates/pdf-style.css"

Exit codes:
  0 - 成功
  1 - 参数/文件错误
  2 - 转换异常

依赖：md2pdf, weasyprint（环境预装）
"""
import argparse
import os
import sys
import traceback
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description='Markdown → PDF 转换')
    parser.add_argument('--input-md', required=True,
                        help='输入的 Markdown 文件路径')
    parser.add_argument('--output-pdf', required=True,
                        help='输出的 PDF 文件路径')
    parser.add_argument('--css', default=None,
                        help='CSS 样式文件路径（可选，默认不使用样式）')
    parser.add_argument('--css-encoding', default='utf-8',
                        help='CSS 文件编码（默认 utf-8）')
    return parser.parse_args()


def validate_file(path, label):
    """校验文件存在且可读，返回规范化后的 Path"""
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] {label} 文件不存在: {p.resolve()}", file=sys.stderr)
        sys.exit(1)
    if not p.is_file():
        print(f"[ERROR] {label} 路径不是文件: {p.resolve()}", file=sys.stderr)
        sys.exit(1)
    return p


def ensure_output_dir(path):
    """确保输出目录存在"""
    parent = Path(path).parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] 已创建输出目录: {parent}")


def do_conversion(input_md: Path, output_pdf: Path, css_path=None):
    """
    核心转换逻辑。封装在一个独立函数中以隔离异常。
    返回 True 表示成功，False 表示失败。
    """
    try:
        from md2pdf.core import md2pdf
    except ImportError as e:
        print(f"[ERROR] 无法导入 md2pdf: {e}", file=sys.stderr)
        print("[HINT] 请确认环境已安装 md2pdf: pip install md2pdf", file=sys.stderr)
        return False

    try:
        # 读取 Markdown 内容
        md_content = input_md.read_text(encoding='utf-8')
        if not md_content.strip():
            print(f"[WARN] Markdown 文件内容为空: {input_md}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] 读取 Markdown 文件失败: {e}", file=sys.stderr)
        return False

    # 准备 CSS 参数
    kwargs = {}
    if css_path:
        if not css_path.exists():
            print(f"[WARN] CSS 文件不存在，将使用无样式渲染: {css_path}", file=sys.stderr)
        else:
            kwargs['css'] = str(css_path)

    # 执行转换
    try:
        print(f"[INFO] 开始转换: {input_md.name} → {output_pdf.name}")
        md2pdf(
            raw=md_content,
            pdf=str(output_pdf),
            **kwargs
        )
        if output_pdf.exists() and output_pdf.stat().st_size > 0:
            size_kb = output_pdf.stat().st_size / 1024
            print(f"[SUCCESS] PDF 生成成功: {output_pdf} ({size_kb:.1f} KB)")
            return True
        else:
            print(f"[ERROR] 转换完成但输出文件异常（为空）: {output_pdf}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERROR] md2pdf 转换失败: {e}", file=sys.stderr)
        print("[TRACE]", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return False


def main():
    args = parse_args()

    # 1. 校验输入文件
    input_md = validate_file(args.input_md, "输入 Markdown")

    # 2. 确保输出目录存在
    ensure_output_dir(args.output_pdf)

    # 3. 校验 CSS 文件（仅 warn，不阻断）
    css_path = None
    if args.css:
        css_path = Path(args.css)
        if not css_path.exists():
            print(f"[WARN] CSS 文件未找到，将使用无样式渲染: {args.css}", file=sys.stderr)

    # 4. 执行转换
    success = do_conversion(input_md, Path(args.output_pdf), css_path)

    if not success:
        print(f"[FAILED] PDF 生成失败，请检查上述错误信息", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
