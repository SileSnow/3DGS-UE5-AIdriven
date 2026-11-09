
# -*- coding: utf-8 -*-
"""合并 report/sections/*.md 生成最终报告（自动目录 + 占位检查）。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SEC = os.path.join(HERE, "sections")
OUT = os.path.join(HERE, "DJI_Mini_UE5_3DGS_可行性验证报告.md")

ORDER = [
    "00_结论速览.md", "01_执行摘要.md", "02_背景与问题定义.md", "03_验证方法与判据.md",
    "04_DJI_Mini_SDK与采集链路.md", "05_3DGS重建链路.md", "06_UE5集成与渲染.md",
    "07_端到端与工程化.md", "08_风险矩阵.md", "09_结论与路线图.md", "10_附录.md",
]

def read(name):
    p = os.path.join(SEC, name)
    if not os.path.exists(p):
        print("WARN missing section:", name)
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read().strip()

sections = []
for name in ORDER:
    sections.append((name, read(name)))

toc = ["## 目录", ""]
for name, text in sections:
    if not text:
        continue
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        n = 0
        while n < len(s) and s[n] == "#":
            n += 1
        title = s[n:].strip()
        if n == 1:
            continue
        indent = "  " * (n - 2)
        toc.append(indent + "- " + title)
toc.append("")

header = [
    "# 以大疆 Mini 系列为基础的 UE5 3DGS 技术可行性验证报告",
    "",
    "> 文档版本：v1.0（2026-11-08）",
    "> 验证环境：Windows 11 / RTX 5060 Laptop 8GB / UE 5.8.4 / PyTorch 2.13.0+cu130",
    "> 项目根目录：dji_ue5_3dgs/（代码、日志、数据、截图均可在项目内找到）",
    "> 证据规则：正文所有定量结论均回链到项目内文件；官方资料附 URL。",
    "",
]

body = ""
for name, text in sections:
    if text:
        body += text + chr(10) + chr(10)

full = chr(10).join(header) + chr(10).join(toc) + chr(10) + "---" + chr(10) + chr(10) + body

with open(OUT, "w", encoding="utf-8") as f:
    f.write(full)

placeholders = []
for i in range(len(full)):
    pass
import re
placeholders = re.findall(r"【[^】]*】", full)
print("WROTE", OUT, len(full), "chars")
print("PLACEHOLDERS:", len(placeholders))
seen = []
for p in placeholders:
    if p not in seen:
        seen.append(p)
for p in seen[:40]:
    print("  -", p[:100])
