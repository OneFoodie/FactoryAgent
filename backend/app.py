# -*- coding: utf-8 -*-
"""FACTORY AGENT 后端：FastAPI + LangChain（DeepSeek / OpenAI 兼容接口）

架构：
    前端 index.html（静态页面，数据全部通过 REST 接口拉取）
        │
        ├── GET  /api/overview | lines | devices | alerts | tickets | reports | sop | metrics
        │        └─ repository.py / kb.py ──> SQLite 真实数据库 factory.db
        │
        └── POST /api/chat
                 └─ LangChain ChatOpenAI.bind_tools(工具集) ──> 按需查库 / 检索知识库
                    工具：query_lines / query_devices / get_device / query_alerts /
                          query_work_orders / factory_overview / search_knowledge_base

用法:
    py -m uvicorn app:app --host 127.0.0.1 --port 8700           （在 backend 目录下）
    首次运行会自动建库；灌入测试数据源：py seed.py

环境变量（可用 backend/.env 覆盖，见 .env.example）:
    DEEPSEEK_API_KEY / OPENAI_API_KEY   必填（仅 /api/chat 需要）
    LLM_BASE_URL                        默认 https://api.deepseek.com/v1
    LLM_MODEL                           默认 deepseek-chat
    LLM_TEMPERATURE                     默认 0.3
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

import kb
import repository as repo

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """你是「FACTORY AGENT · 产线智能体」，服务于工厂产线的值班工程师。

职责：
- 回答产线运行、设备状态、告警处置、工单调度、质量与 OEE 等生产问题。
- 涉及执行类操作（派工、停机、下发参数）时必须提示需人工确认。

数据使用规则（重要）：
- 所有实时数据都来自后台数据库，必须通过工具按需查询，禁止凭记忆编造数值。
- 可用工具：
  · factory_overview      — 全局概览（产线/设备在线、待确认告警、未关闭工单）
  · query_lines           — 产线台账（节拍、产出、OEE、FPY）
  · query_devices         — 设备列表，可按状态/产线过滤
  · get_device            — 单台设备详情（按编号或名称模糊匹配）
  · query_alerts          — 告警列表，可按状态/级别过滤
  · query_work_orders     — 工单列表，可按状态/设备过滤
  · search_knowledge_base — 在 SOP 知识库中检索作业指导（处置步骤、保养标准）
- 问设备编号（如 DEV-A3-02）、产线（如三号线）时，先用工具查库再作答。
- 问「怎么处置 / 作业指导 / SOP」时，先调用 search_knowledge_base 检索，再结合命中条目作答。

回答要求：
- 中文；聚焦结论与动作建议。
- 使用 Markdown 排版以提升可读性：
  · 结论与关键数值用 **加粗**；分点用 - 或 1. 列表；
  · 多对象/多字段对比用 Markdown 表格（含表头分隔行）；
  · 展示流程、链路或判定逻辑时，用 ```mermaid 代码块输出流程图（如 flowchart TD 或 sequenceDiagram）；
  · 参数、编号用行内 `code`（如 `SOP-INJ-07`）。
- 篇幅控制在 2~8 行左右，避免冗长堆砌。
- 若工具未返回数据，请明确说明「暂无相关数据」，不要编造。"""

app = FastAPI(title="Factory Agent Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_llm = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            temperature=TEMPERATURE,
            timeout=60,
            max_retries=2,
        )
    return _llm


# ---------------------------------------------------------------------------
# LangChain 工具：让 LLM 按需查库 / 检索知识库
# ---------------------------------------------------------------------------
@tool
def factory_overview() -> dict:
    """查询工厂全局概览：产线在线数、设备在线数与在线率、待确认告警数、未关闭工单数。"""
    return repo.overview()


@tool
def query_lines() -> list[dict]:
    """查询全部产线台账：编号、名称、运行状态、设备在线数、班次产出、节拍、OEE 与 FPY。"""
    return repo.list_lines()


@tool
def query_devices(state: str = "", line_code: str = "") -> list[dict]:
    """查询设备列表。

    Args:
        state: 可选，按状态过滤，取值 run / warn / stop / idle；留空返回全部。
        line_code: 可选，按产线编号过滤，如 LINE-01 / LINE-02 / LINE-03 / 公用。
    """
    return repo.list_devices(state or None, line_code or None)


@tool
def get_device(code: str) -> dict:
    """查询单台设备详情。

    Args:
        code: 设备编号或名称，如 DEV-A3-02、A3 注塑机。
    """
    return repo.get_device(code) or {}


@tool
def query_alerts(status: str = "open", level: str = "") -> list[dict]:
    """查询告警列表。

    Args:
        status: 告警状态，open（待确认）或 closed；默认 open。
        level: 可选，级别过滤，取值 err / warn / info。
    """
    return repo.list_alerts(status or None, level or None)


@tool
def query_work_orders(status: str = "", device_code: str = "") -> list[dict]:
    """查询维修工单列表。

    Args:
        status: 可选，工单状态：pending（待派工）/ doing（处理中）/ accepting（待验收）/ done（已完成）。
        device_code: 可选，按设备编号过滤，如 DEV-A3-02。
    """
    return repo.list_work_orders(status or None, device_code or None)


@tool
def search_knowledge_base(query: str) -> list[dict]:
    """在 SOP 知识库中检索作业指导书，返回命中的 SOP 编号、标题与正文片段。

    Args:
        query: 检索问题或关键词，如「注塑机模温超限怎么处置」。
    """
    hits = kb.search(query, top_k=3)
    return [
        {"code": h["code"], "title": h["title"], "category": h.get("category"),
         "device_code": h.get("device_code"), "content": h.get("content"),
         "source": h.get("source")}
        for h in hits
    ]


TOOLS = [
    factory_overview,
    query_lines,
    query_devices,
    get_device,
    query_alerts,
    query_work_orders,
    search_knowledge_base,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

TOOL_SOURCE = {
    "factory_overview": "MES · 运行概览",
    "query_lines": "MES · 产线台账",
    "query_devices": "SCADA · 设备状态",
    "get_device": "SCADA · 设备详情",
    "query_alerts": "SCADA · 实时告警",
    "query_work_orders": "EAM · 工单台账",
    "search_knowledge_base": "SOP 知识库",
}


class ChatIn(BaseModel):
    message: str
    scope: str | None = None
    history: list[dict] | None = None


SCOPE_HINT = {
    "kb": "本次回答请优先调用 search_knowledge_base 在知识库范围内检索后再作答。",
    "sop": "本次回答请优先调用 search_knowledge_base 检索 SOP 作业指导后再作答。",
}


def run_tools(messages: list, sources: list[str]) -> AIMessage:
    """LangChain 工具调用循环：模型选工具 -> 执行 -> 回填结果 -> 直到给出最终答复。"""
    llm = get_llm().bind_tools(TOOLS)
    ai = llm.invoke(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            break
        messages.append(ai)
        for call in tool_calls:
            name = call.get("name")
            label = TOOL_SOURCE.get(name)
            if label and label not in sources:
                sources.append(label)
            fn = TOOLS_BY_NAME.get(name)
            try:
                result = fn.invoke(call.get("args") or {}) if fn else {"error": "未知工具"}
            except Exception as exc:  # noqa: BLE001
                result = {"error": f"工具执行失败：{exc}"}
            if name == "search_knowledge_base" and isinstance(result, list):
                for h in result:
                    ref = f"{h.get('code')} {h.get('title')}"
                    if ref not in sources:
                        sources.append(ref)
            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=call.get("id", ""),
                )
            )
        ai = llm.invoke(messages)
    return ai


@app.get("/")
def index():
    page = ROOT_DIR / "index.html"
    if not page.exists():
        return JSONResponse({"error": "index.html not found"}, status_code=404)
    return FileResponse(page, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "ok": bool(API_KEY),
        "model": MODEL,
        "base_url": BASE_URL,
        "key_configured": bool(API_KEY),
        "db_ready": True,
        "kb_docs": repo.kb_doc_count(),
        "tools": [t.name for t in TOOLS],
    }


# ---------------------------------------------------------------------------
# REST 数据接口：前端静态数据改由这里拉取
# ---------------------------------------------------------------------------
@app.get("/api/overview")
def api_overview():
    return repo.overview()


@app.get("/api/briefing")
def api_briefing():
    """对话页首屏班前简报（动态生成）。"""
    return repo.briefing()


@app.get("/api/lines")
def api_lines():
    return repo.list_lines()


@app.get("/api/devices")
def api_devices(state: str | None = None, line: str | None = None):
    return repo.list_devices(state, line)


@app.get("/api/devices/{code}")
def api_device(code: str):
    d = repo.get_device(code)
    if not d:
        return JSONResponse({"error": "device not found"}, status_code=404)
    return d


@app.get("/api/alerts")
def api_alerts(status: str | None = "open", level: str | None = None):
    return repo.list_alerts(status, level)


@app.get("/api/tickets")
def api_tickets(status: str | None = None, device: str | None = None):
    return repo.list_work_orders(status, device)


@app.get("/api/tickets/summary")
def api_ticket_summary():
    return repo.order_summary()


@app.get("/api/reports")
def api_reports():
    return repo.reports_summary()


@app.get("/api/metrics")
def api_metrics(scope: str | None = None):
    return repo.list_metrics(scope)


@app.get("/api/sop")
def api_sop():
    return kb.list_docs()


@app.get("/api/sop/search")
def api_sop_search(q: str = Query(..., min_length=1), top_k: int = 3):
    return kb.search(q, top_k=top_k)


@app.get("/api/sop/{code}")
def api_sop_doc(code: str):
    doc = kb.get_doc(code)
    if not doc:
        return JSONResponse({"error": "sop not found"}, status_code=404)
    return doc


@app.post("/api/chat")
def chat(body: ChatIn):
    msg = (body.message or "").strip()
    if not msg:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if not API_KEY:
        return JSONResponse(
            {"error": "LLM API key 未配置，请在 backend/.env 设置 DEEPSEEK_API_KEY"},
            status_code=503,
        )

    sources: list[str] = []
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    if body.scope in SCOPE_HINT:
        messages.append(SystemMessage(content=SCOPE_HINT[body.scope]))
    for h in (body.history or [])[-8:]:
        role, content = h.get("role"), h.get("content")
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=msg))

    try:
        resp = run_tools(messages, sources)
        reply = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": f"模型调用失败：{exc}", "model": MODEL}, status_code=502
        )

    if not sources:
        sources = ["LangChain · DeepSeek"]
    if body.scope == "kb":
        sources.insert(0, "知识库检索")
    elif body.scope == "sop":
        sources.insert(0, "SOP 作业指导")
    return {"reply": reply.strip(), "sources": sources, "model": MODEL}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8700, reload=True)
