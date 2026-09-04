"""最小 RAG 知识库。

实现：文档切块 -> TF-IDF 向量化 -> 余弦相似度检索 -> 拼入上下文。
为保持 MVP 零重依赖，不引入 embedding 模型 / 向量数据库，
用纯 Python 实现 TF-IDF（对中文做二元分词）。可无缝替换为真实 embedding + 向量库。
"""

from __future__ import annotations

import math
import re
from collections import Counter

# ---- 内置知识库文档（每块一段） ----
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


def _tokenize(text: str) -> list[str]:
    """中文按字符二元组 + 英文按词，统一小写。"""
    text = text.lower()
    tokens: list[str] = []
    # 英文/数字词
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)
    # 中文字符二元组
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    return tokens


class MiniRAG:
    """极简 TF-IDF 检索器。"""

    def __init__(self, docs: list[str] | None = None):
        self._docs = docs if docs is not None else list(KB_DOCS)
        self._tfidf: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._build()

    def _build(self) -> None:
        doc_tfs: list[Counter] = []
        df: Counter = Counter()  # 包含词项的文档数
        for doc in self._docs:
            tf = Counter(_tokenize(doc))
            doc_tfs.append(tf)
            for term in tf:
                df[term] += 1
        n = len(self._docs)
        self._idf = {term: math.log((1 + n) / (1 + freq)) + 1.0 for term, freq in df.items()}
        self._tfidf = []
        for tf in doc_tfs:
            vec: dict[str, float] = {}
            total = sum(tf.values())
            for term, cnt in tf.items():
                vec[term] = (cnt / total) * self._idf.get(term, 0.0)
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
        """返回 [{text, score}]，按相关度降序。"""
        qv = self._query_vec(query)
        scored = [(self._docs[i], self._cos(qv, vec), i) for i, vec in enumerate(self._tfidf)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [{"text": d, "score": round(s, 4), "index": i} for d, s, i in scored[:top_k]]


_default_rag = MiniRAG()


def search_kb(query: str, top_k: int = 3) -> list[dict]:
    """供 MCP 工具层调用的默认实例。"""
    return _default_rag.search(query, top_k)
