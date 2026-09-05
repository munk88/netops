"""最小 RAG 知识库 —— 阶段1：知识外置。

知识来源（按优先级）：
1. knowledge/ 目录下的 .md / .txt / .rst 文档（推荐，知识可增长、可溯源到文件名）
2. 目录为空 / 不存在时，回退到内置示例 KB_DOCS

实现：文档切块 -> TF-IDF 向量化 -> 余弦相似度检索 -> 拼入上下文。
为保持 MVP 零重依赖，不引入 embedding 模型 / 向量数据库，用纯 Python 实现 TF-IDF。
检索接口 search(query, top_k) 保持不变，后续可无缝替换为 embedding + 向量库。

用法：
    python -m netops_agent.rag --status          # 查看知识库状态
    python -m netops_agent.rag --rebuild         # 重建索引（放新文档后执行）
    python -m netops_agent.rag --query "接口 down" # 检索测试
"""

from __future__ import annotations

import math
import re
import sys
from collections import Counter
from pathlib import Path

# 知识目录：项目根 /knowledge（可放 .md/.txt/.rst，支持子目录）
KB_DIR = Path(__file__).resolve().parent.parent / "knowledge"
SUFFIXES = {".md", ".txt", ".rst"}
MIN_CHUNK = 12    # 少于该字符数的块丢弃
MAX_CHUNK = 600   # 块超长按句号边界截断

KB_SOURCE_BUILTIN = "内置示例（knowledge/ 目录为空）"

# ---- 内置兜底知识（目录为空时使用） ----
KB_DOCS: list[str] = [
    "接口 down 排障步骤：1) show interface 查看链路层与物理层状态；2) 检查光模块/收发功率与光衰；"
    "3) 检查物理连接与线缆；4) 查看端口安全 PortSecurity 是否触发 violation；"
    "5) shutdown 再 no shutdown 复位端口；6) 若为 PortSecurity violation，执行 errdisable recovery 或调整端口安全策略。",

    "端口安全 PortSecurity：当接口开启 port-security 且 MAC 地址数量超限时，接口进入 errdisable 状态，表现为 link down。"
    "排障：show port-security 查看违规 MAC；clear port-security 或 shutdown/no shutdown 恢复；"
    "必要时调整 maximum 数量或设置 violation protect（只丢弃不发告警）。",

    "OSPF 邻居建立排障：1) 确认两端口 area 一致且未 network 错配；2) 检查 hello/dead 定时器一致；"
    "3) 检查 MTU 不一致导致状态卡在 Exstart；4) 检查认证（MD5/明文）是否匹配；5) show ip ospf neighbor 查看状态。",

    "设备巡检常用命令：核心：show version / show cpu / show memory / show interface summary / "
    "show log；华为：display version / display cpu-usage / display memory-usage / display interface brief / display logbuffer。",

    "CPU 利用率过高排障：1) display cpu-usage 查看是否持续高；2) 定位高占用进程（路由进程/软转发）；"
    "3) 排查是否受到攻击（流量风暴、组播、BGP 路由抖动）；4) 抓包确认；5) 必要时限速、过滤或升级硬件。",

    "设备重启/固件升级注意事项：升级前先备份当前配置（display current-configuration 或 copy running-config startup-config）；"
    "确认设备型号与版本兼容性；升级过程中保持电源稳定，避免中断；升级失败时需可回滚到旧版本。",
]


# ---------------- 文档读取与切块 ----------------
def _read_text_files() -> list[tuple[str, str]]:
    """扫描知识目录，返回 [(source, 全文)]，source 为相对路径如 '01-接口down排障.md'。

    跳过说明性元文档：以 README 开头或以下划线开头的文件。
    """
    if not KB_DIR.exists():
        return []
    out: list[tuple[str, str]] = []
    for p in sorted(KB_DIR.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in SUFFIXES):
            continue
        name = p.name
        if name.startswith("README") or name.startswith("_"):
            continue
        try:
            out.append((p.relative_to(KB_DIR).as_posix(), p.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


def _chunk(text: str) -> list[str]:
    """按空行分段，过滤过短块与纯标题块，超长按句号边界截断。"""
    chunks: list[str] = []
    for part in re.split(r"\n\s*\n", text):
        part = part.strip()
        if len(part) < MIN_CHUNK:
            continue
        # 纯标题块（如 "# 接口 Down 排障"）无正文信息量，跳过；
        # 正文段落自会包含标题语义，避免检索只命中标题。
        if part.startswith("#") and len(part) < 24:
            continue
        while len(part) > MAX_CHUNK:
            cut = part.rfind("。", 0, MAX_CHUNK)
            cut = cut if cut != -1 else MAX_CHUNK
            chunks.append(part[: cut + 1])
            part = part[cut + 1:].strip()
        if part:
            chunks.append(part)
    return chunks


def load_docs() -> list[dict]:
    """返回 [{text, source}]。目录有文档则用目录，否则用内置兜底。"""
    items: list[dict] = []
    for source, text in _read_text_files():
        for chunk in _chunk(text):
            items.append({"text": chunk, "source": source})
    if not items:
        items = [{"text": d, "source": KB_SOURCE_BUILTIN} for d in KB_DOCS]
    return items


# ---------------- 检索器 ----------------
def _tokenize(text: str) -> list[str]:
    """中文按字符二元组 + 英文按词，统一小写。"""
    text = text.lower()
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    return tokens


class MiniRAG:
    """极简 TF-IDF 检索器，支持溯源（每块带 source）。"""

    def __init__(self, docs: list[dict] | list[str] | None = None):
        self._texts: list[str] = []
        self._sources: list[str] = []
        if docs is None:
            docs = load_docs()
        for d in docs:
            if isinstance(d, dict):
                self._texts.append(d["text"])
                self._sources.append(d.get("source", "未知"))
            else:
                self._texts.append(d)
                self._sources.append("未知")
        self._tfidf: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._build()

    def _build(self) -> None:
        doc_tfs: list[Counter] = []
        df: Counter = Counter()
        for doc in self._texts:
            tf = Counter(_tokenize(doc))
            doc_tfs.append(tf)
            for term in tf:
                df[term] += 1
        n = len(self._texts)
        self._idf = {term: math.log((1 + n) / (1 + freq)) + 1.0 for term, freq in df.items()}
        self._tfidf = []
        for tf in doc_tfs:
            total = sum(tf.values())
            vec = {term: (cnt / total) * self._idf.get(term, 0.0) for term, cnt in tf.items()}
            self._tfidf.append(vec)

    def _query_vec(self, query: str) -> dict[str, float]:
        tf = Counter(_tokenize(query))
        total = sum(tf.values()) or 1
        return {t: (c / total) * self._idf.get(t, 0.0) for t, c in tf.items()}

    @staticmethod
    def _cos(a: dict[str, float], b: dict[str, float]) -> float:
        inter = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in inter)
        na = math.sqrt(sum(v * v for v in a.values())) or 1.0
        nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
        return dot / (na * nb)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """返回 [{text, score, index, source}]，按相关度降序。"""
        qv = self._query_vec(query)
        scored = [
            (self._texts[i], self._cos(qv, vec), i)
            for i, vec in enumerate(self._tfidf)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {"text": d, "score": round(s, 4), "index": i, "source": self._sources[i]}
            for d, s, i in scored[:top_k]
        ]

    def stats(self) -> dict:
        """索引统计（块数 / 来源文件 / 模式）。"""
        return {
            "chunks": len(self._texts),
            "sources": sorted(set(self._sources)),
            "mode": "knowledge" if (self._sources and self._sources[0] != KB_SOURCE_BUILTIN) else "builtin",
            "kb_dir": str(KB_DIR),
        }


# ---------------- 全局实例（懒加载 + 自动检测目录变化） ----------------
_default_rag: MiniRAG | None = None
_kb_sig: object = None


def _current_sig():
    """知识目录的指纹：目录不存在返回 None；否则返回 (文件名, mtime) 元组。"""
    if not KB_DIR.exists():
        return None
    try:
        return tuple(
            (p.relative_to(KB_DIR).as_posix(), p.stat().st_mtime_ns)
            for p in sorted(KB_DIR.rglob("*"))
            if p.is_file() and p.suffix.lower() in SUFFIXES
        )
    except OSError:
        return None


def _ensure_loaded() -> None:
    global _default_rag, _kb_sig
    sig = _current_sig()
    if _default_rag is None or sig != _kb_sig:
        _default_rag = MiniRAG()
        _kb_sig = sig


def search_kb(query: str, top_k: int = 3) -> list[dict]:
    """供 MCP 工具层调用的默认实例（自动检测目录变化并重建）。"""
    _ensure_loaded()
    return _default_rag.search(query, top_k)


def rebuild() -> dict:
    """重建知识库索引，返回统计信息。"""
    _ensure_loaded()
    return _default_rag.stats()


def show_status() -> None:
    info = rebuild()
    print("知识库状态：")
    print(f"  模式：{info['mode']}（{'knowledge/ 目录' if info['mode'] == 'knowledge' else '内置示例'}）")
    print(f"  知识块数：{info['chunks']}")
    print(f"  来源文件：{len(info['sources'])} 个")
    for s in info["sources"]:
        print(f"    - {s}")


# ---------------- CLI ----------------
def _cli(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="netops-mvp 知识库管理（阶段1：知识外置）")
    ap.add_argument("--status", action="store_true", help="显示知识库状态")
    ap.add_argument("--rebuild", action="store_true", help="重建索引（放新文档后执行）")
    ap.add_argument("--query", metavar="问题", help="检索测试，返回 top3 命中")
    ap.add_argument("--top-k", type=int, default=3, help="检索返回条数（默认 3）")
    args = ap.parse_args(argv)

    if args.rebuild:
        info = rebuild()
        print(f"已重建索引：{info['chunks']} 块知识，来源 {len(info['sources'])} 个文件（模式：{info['mode']}）")
    elif args.query:
        _ensure_loaded()
        hits = _default_rag.search(args.query, args.top_k)
        print(f"查询：{args.query}\n命中 {len(hits)} 条：")
        for h in hits:
            print(f"\n[{h['score']:.3f}] 来源：{h['source']}\n    {h['text']}")
    else:
        show_status()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
