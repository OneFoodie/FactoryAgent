# -*- coding: utf-8 -*-
"""知识库（RAG）检索层：基于 SQLite FTS5 三元组分词的中文全文检索。

- 语料：sop_docs（SOP 作业指导书 / 保养标准）
- 检索：FTS5 trigram + bm25 排序，支持短词回退到 LIKE 模糊匹配
"""
import re

from db import query

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_STOP = {
    "怎么", "如何", "什么", "哪些", "为什么", "请", "帮我", "一下", "的", "了",
    "和", "与", "是", "有", "在", "查询", "查找", "检索", "处置", "处理",
}


def _keywords(text: str) -> list[str]:
    """从自然语言问题里抽取检索关键词（中文按 2~4 字滑窗 + 保留英文/编号）。"""
    text = (text or "").strip()
    keys: list[str] = []
    # 英文编号 / 术语，如 SOP-INJ-07、DEV-A3-02
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}", text):
        keys.append(tok)
    # 中文连续片段
    for seg in _CJK.findall(text):
        if seg in _STOP:
            continue
        if len(seg) <= 4:
            keys.append(seg)
        else:
            for n in (4, 3, 2):
                for i in range(len(seg) - n + 1):
                    frag = seg[i:i + n]
                    if frag not in _STOP:
                        keys.append(frag)
    # 去重保序
    seen, out = set(), []
    for k in keys:
        if len(k) >= 2 and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _fts_search(terms: list[str], limit: int) -> list[dict]:
    expr = " OR ".join(f'"{t}"' for t in terms)
    sql = (
        "SELECT d.code, d.title, d.category, d.device_code, d.content, d.source, "
        "       bm25(sop_fts, 4.0, 6.0, 1.0) AS score "
        "FROM sop_fts JOIN sop_docs d ON d.id = sop_fts.rowid "
        "WHERE sop_fts MATCH ? ORDER BY score LIMIT ?"
    )
    try:
        return query(sql, (expr, limit))
    except Exception:
        return []


def _like_search(term: str, limit: int) -> list[dict]:
    like = f"%{term}%"
    return query(
        "SELECT code, title, category, device_code, content, source, 0 AS score "
        "FROM sop_docs WHERE title LIKE ? OR content LIKE ? OR code LIKE ? "
        "ORDER BY id LIMIT ?",
        (like, like, like, limit),
    )


def search(query_text: str, top_k: int = 3) -> list[dict]:
    """检索知识库，返回按相关度排序的 SOP 片段。

    - 用 bm25 加权（title/编号权重高于正文）对多关键词做联合排序。
    - FTS5 trigram 对 <3 字词无法匹配，因此对结果不足的情况回退 LIKE 模糊匹配。
    """
    keywords = _keywords(query_text)
    if not keywords:
        return []
    rows = _fts_search(keywords, top_k * 3)
    if len(rows) < top_k:
        merged = {r["code"]: r for r in rows}
        for kw in keywords[:4]:
            for row in _like_search(kw, top_k):
                merged.setdefault(row["code"], row)
        rows = list(merged.values())
        rows.sort(key=lambda r: r.get("score", 0))
    return rows[:top_k]


def list_docs() -> list[dict]:
    return query(
        "SELECT code, title, category, device_code, source FROM sop_docs ORDER BY id"
    )


def get_doc(code: str) -> dict | None:
    rows = query("SELECT * FROM sop_docs WHERE code = ?", (code,))
    return rows[0] if rows else None


def build_context(query_text: str, top_k: int = 3, max_chars: int = 1600) -> tuple[str, list[str]]:
    """把检索结果拼成可注入 LLM 的上下文文本，返回 (context, sources)。"""
    hits = search(query_text, top_k=top_k)
    if not hits:
        return "", []
    parts, sources = [], []
    used = 0
    for h in hits:
        snippet = (h.get("content") or "").strip()
        block = f"【{h['code']}】{h['title']}（来源：{h.get('source') or '知识库'}）\n{snippet}"
        if used + len(block) > max_chars:
            block = block[:max_chars - used] + "…"
        parts.append(block)
        sources.append(f"{h['code']} {h['title']}")
        used += len(block)
        if used >= max_chars:
            break
    return "\n\n".join(parts), sources
