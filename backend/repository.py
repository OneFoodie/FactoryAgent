# -*- coding: utf-8 -*-
"""数据访问层：把 SQLite 真实数据库的读写封装成业务函数。

被两处消费：
1. FastAPI 的 REST 接口（/api/lines|devices|alerts|tickets|reports）
2. LangChain 工具（让 LLM 按需查库）
"""
import datetime
import json

from db import execute, query, query_one


def _device_row(row: dict) -> dict:
    try:
        metrics = json.loads(row.get("metrics_json") or "[]")
    except (TypeError, ValueError):
        metrics = []
    row = dict(row)
    row["metrics"] = metrics
    row.pop("metrics_json", None)
    return row


def list_lines() -> list[dict]:
    return query("SELECT * FROM lines ORDER BY code")


def get_line(code: str) -> dict | None:
    return query_one("SELECT * FROM lines WHERE code = ? OR name LIKE ?", (code, f"%{code}%"))


def list_devices(state: str | None = None, line_code: str | None = None) -> list[dict]:
    sql = "SELECT * FROM devices WHERE 1=1"
    params: list = []
    if state and state != "all":
        sql += " AND state = ?"
        params.append(state)
    if line_code:
        sql += " AND line_code = ?"
        params.append(line_code)
    sql += " ORDER BY id"
    return [_device_row(r) for r in query(sql, tuple(params))]


def get_device(code: str) -> dict | None:
    row = query_one("SELECT * FROM devices WHERE code = ? OR name LIKE ?", (code, f"%{code}%"))
    return _device_row(row) if row else None


def device_summary() -> dict:
    total = query_one("SELECT COUNT(*) AS n FROM devices")["n"]
    online = query_one(
        "SELECT COUNT(*) AS n FROM devices WHERE state IN ('run','warn','idle')"
    )["n"]
    open_alerts = query_one(
        "SELECT COUNT(*) AS n FROM alerts WHERE status = 'open'"
    )["n"]
    avg_load = query_one("SELECT ROUND(AVG(load_pct),1) AS v FROM devices")["v"]
    return {
        "total": total,
        "online": online,
        "online_rate": round(online / total * 100, 1) if total else 0,
        "open_alerts": open_alerts,
        "avg_load": avg_load,
    }


def list_alerts(status: str | None = "open", level: str | None = None) -> list[dict]:
    sql = "SELECT * FROM alerts WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if level:
        sql += " AND level = ?"
        params.append(level)
    sql += " ORDER BY occurred_at"
    return query(sql, tuple(params))


def list_work_orders(status: str | None = None, device_code: str | None = None) -> list[dict]:
    sql = "SELECT * FROM work_orders WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if device_code:
        sql += " AND device_code = ?"
        params.append(device_code)
    sql += " ORDER BY priority, code"
    return query(sql, tuple(params))


def order_summary() -> dict:
    rows = query("SELECT status, COUNT(*) AS n FROM work_orders GROUP BY status")
    by_status = {r["status"]: r["n"] for r in rows}
    total_open = sum(v for k, v in by_status.items() if k != "done")
    return {"by_status": by_status, "open": total_open,
            "total": query_one("SELECT COUNT(*) AS n FROM work_orders")["n"]}


def list_metrics(scope: str | None = None) -> list[dict]:
    if scope:
        return query("SELECT * FROM metrics WHERE scope = ? ORDER BY id", (scope,))
    return query("SELECT * FROM metrics ORDER BY id")


def daily_series(line_code: str = "ALL", days: int = 14) -> list[dict]:
    return query(
        "SELECT stat_date, line_code, output, fpy FROM daily_stats "
        "WHERE line_code = ? ORDER BY stat_date DESC LIMIT ?",
        (line_code, days),
    )[::-1]


def fpy_comparison(days: int = 7) -> list[dict]:
    out = []
    for code, name in (("LINE-03", "三号线"), ("LINE-01", "一号线"), ("LINE-02", "二号线")):
        series = daily_series(code, days)
        vals = [r["fpy"] for r in series if r["fpy"] is not None]
        if not vals:
            continue
        today = vals[-1]
        avg = round(sum(vals) / len(vals), 1)
        out.append({
            "line_code": code,
            "line_name": name,
            "today": today,
            "avg": avg,
            "volatility": round(max(vals) - min(vals), 1),
        })
    return out


def reports_summary() -> dict:
    return {
        "metrics": list_metrics("report"),
        "details": list_metrics("report_detail"),
        "daily": daily_series("ALL", 14),
        "fpy_lines": fpy_comparison(7),
        "line_oee": [{"code": r["code"], "name": r["name"], "oee": r["oee"],
                      "target": 85.0} for r in list_lines()],
        "downtime_reasons": [
            {"name": "设备故障", "pct": 35, "color": "var(--red)"},
            {"name": "换模换料", "pct": 25, "color": "var(--amber)"},
            {"name": "待料等待", "pct": 20, "color": "var(--cyan)"},
            {"name": "计划保养", "pct": 20, "color": "var(--violet)"},
        ],
        "energy": [{"name": "一", "pct": 84}, {"name": "二", "pct": 70},
                   {"name": "三", "pct": 76}, {"name": "公用", "pct": 52}],
        "labor": [{"name": "A班", "pct": 62, "plan": True},
                  {"name": "B班", "pct": 78, "plan": True},
                  {"name": "C班", "pct": 54, "plan": True},
                  {"name": "工程", "pct": 41, "plan": False},
                  {"name": "外协", "pct": 33, "plan": False},
                  {"name": "夜班", "pct": 88, "plan": True}],
    }


def overview() -> dict:
    """首页/顶栏概览：产线在线、待确认告警、未关闭工单。"""
    dev = device_summary()
    orders = order_summary()
    lines = list_lines()
    return {
        "lines_online": sum(1 for l in lines if l["status"] == "run"),
        "lines_total": len(lines),
        "devices_online": dev["online"],
        "devices_total": dev["total"],
        "online_rate": dev["online_rate"],
        "open_alerts": dev["open_alerts"],
        "open_orders": orders["open"],
    }


OEE_TARGET = 85.0
FPY_TARGET = 98.5
_BRIEFING_LINES = (
    ("LINE-03", "三号线", "#ffb020", False),
    ("LINE-01", "一号线", "#2dd4bf", False),
    ("LINE-02", "二号线", "#a78bfa", True),
)


def _clock() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _fpy_matrix(days: int = 7) -> tuple[list[str], list[dict]]:
    """近 N 天三线 FPY 矩阵：返回 (日期列表, 各线序列)。"""
    dates: list[str] = []
    out: list[dict] = []
    for code, name, color, dashed in _BRIEFING_LINES:
        rows = daily_series(code, days)
        if not rows:
            continue
        if not dates:
            dates = [r["stat_date"] for r in rows]
        vals = [r["fpy"] for r in rows]
        today = vals[-1]
        avg = round(sum(vals) / len(vals), 1)
        vol = round(max(vals) - min(vals), 1)
        if today > avg + 0.1:
            trend, tcls = "回升", "tag--ok"
        elif today < avg - 0.1:
            trend, tcls = "微降", "tag--warn"
        else:
            trend, tcls = "平稳", ""
        out.append({
            "code": code, "name": name, "color": color, "dashed": dashed,
            "values": vals, "today": today, "avg": avg, "volatility": vol,
            "trend": trend, "trend_cls": tcls,
        })
    return dates, out


def briefing() -> dict:
    """对话页首屏班前简报：由数据库实时数据组装（问候、产线快照、FPY 趋势、工单草稿）。"""
    now = datetime.datetime.now()
    ov = overview()
    line = get_line("LINE-03") or {}
    line_code = line.get("code", "LINE-03")
    line_name = line.get("name", "三号线")

    alerts = [a for a in list_alerts("open") if a.get("line_code") == line_code]
    warn_devs = list_devices("warn", line_code)

    # —— 三号线实时快照指标 ——
    oee = line.get("oee")
    metrics = [
        {"lab": "OEE 综合效率", "value": oee, "unit": "%", "accent": True,
         "dl": ("较目标 %+.1f%%" % (oee - OEE_TARGET)) if oee is not None else "",
         "cls": "down" if (oee or 0) >= OEE_TARGET else "up"},
        {"lab": "当前节拍", "value": line.get("takt"), "unit": "s",
         "dl": "目标 %.1fs" % (line.get("takt_target") or 0), "cls": "flat"},
        {"lab": "在线设备", "value": line.get("device_online"),
         "unit": "/%d" % (line.get("device_total") or 0),
         "dl": "%d 台降速" % len(warn_devs), "cls": "flat"},
        {"lab": "本班产出", "value": line.get("shift_output"), "unit": "件",
         "dl": "今日累计", "cls": "flat"},
    ]

    # —— 快照叙述 ——
    key_alert = next((a for a in alerts if a["level"] in ("err", "warn")), None) or (alerts[0] if alerts else None)
    snap_paras = []
    if key_alert:
        dev = get_device(key_alert["device_code"]) or {}
        snap_paras.append("%s整体运行正常，但 <b>%s</b> 存在异常：%s" % (
            line_name, dev.get("name") or key_alert["device_code"], key_alert["detail"]))
        ref = key_alert.get("sop_ref")
        snap_paras.append("建议按 <b>%s</b> 处置。下面是%s实时快照：" % (ref, line_name) if ref
                          else "下面是%s实时快照：" % line_name)
    else:
        snap_paras.append("%s整体运行正常，暂无待确认告警。下面是%s实时快照：" % (line_name, line_name))

    # —— FPY 趋势 ——
    fpy_dates, fpy_lines = _fpy_matrix(7)
    seg = "、".join("%s %.1f%%" % (l["name"], l["today"]) for l in fpy_lines)
    fpy_intro = "已生成近 7 天一次良率（FPY）趋势：%s，目标 %.1f%%。" % (seg, FPY_TARGET)

    # —— 工单草稿：异常设备对应的未关闭工单 ——
    draft = None
    if warn_devs:
        row = query_one(
            "SELECT * FROM work_orders WHERE device_code = ? AND status != 'done' "
            "ORDER BY priority, code LIMIT 1", (warn_devs[0]["code"],))
        if row:
            draft = {
                "code": row["code"], "priority": row["priority"], "title": row["title"],
                "device_code": row["device_code"], "line_code": row["line_code"],
                "sop_ref": row.get("sop_ref"), "confidence": row.get("confidence") or 0,
                "hint_cnt": row.get("hint_cnt") or 0, "hit_cnt": row.get("hit_cnt") or 0,
                "sop_match": "高" if (row.get("confidence") or 0) >= 60 else "中",
                "time": now.strftime("%H:%M"),
                "answer": ["另外，%s 异常我已按 SOP 预填了维修工单草稿，等你确认：" % (warn_devs[0]["name"],)],
            }

    wd = "一二三四五六日"[now.weekday()]
    return {
        "date_label": "今天 · %02d月%02d日 周%s" % (now.month, now.day, wd),
        "greeting": {
            "time": "08:02",
            "paras": [
                "早上好，张伟。<b>A 班</b>已交接完毕，夜班记录已同步。当前 <b>%d 条待确认告警</b>、<b>%d 个未关闭工单</b>。"
                % (ov["open_alerts"], ov["open_orders"]),
                "你可以直接问我产线状况，例如「三号线现在怎么样」「A3 注塑机为什么停机」「昨天良率多少」。",
            ],
            "sources": ["MES 实时接口", "SCADA · %d 台设备" % ov["devices_total"], "刷新于 " + _clock()],
        },
        "snapshot": {
            "time_q": "08:03", "time": "08:03",
            "question": "三号线现在什么情况？有没有异常？",
            "answer": snap_paras,
            "line_code": line_code, "line_name": line_name,
            "abnormal": len(alerts),
            "metrics": metrics,
            "alerts": alerts,
            "updated": _clock(),
        },
        "fpy": {
            "time_q": "08:05", "time": "08:05",
            "question": "把最近 7 天良率趋势拉出来，顺便对比一下三条线",
            "answer": [fpy_intro],
            "dates": fpy_dates, "lines": fpy_lines,
        },
        "draft": draft,
    }


def kb_doc_count() -> int:
    return query_one("SELECT COUNT(*) AS n FROM sop_docs")["n"]
