# -*- coding: utf-8 -*-
"""测试数据源种子脚本：把前端 index.html 的静态数据灌入 SQLite 真实数据库。

用法:
    py seed.py          （在 backend 目录下，会重建 factory.db 的演示数据）
"""
from db import DB_PATH, init_db, rebuild_fts, get_conn

LINES = [
    # code, name, status, device_total, device_online, shift_output, takt, takt_target, oee, fpy
    ("LINE-01", "一号线", "run", 4, 4, 1180, 40.1, 40.0, 88.1, 98.2),
    ("LINE-02", "二号线", "run", 4, 3, 1052, 43.8, 41.0, 82.4, 97.5),
    ("LINE-03", "三号线", "run", 4, 4, 1284, 42.6, 40.0, 86.4, 98.9),
]

# code, name, line_code, state, load_pct, metrics[(label,value)], note, foot, ref, since
DEVICES = [
    ("DEV-A3-02", "A3 注塑机", "LINE-03", "warn", 60,
     [("模温", "218°C"), ("负荷", "60%"), ("节拍", "48.2s")],
     "降速运行", "模温超限 12min", "SOP-INJ-07", "07:51"),
    ("DEV-C7-01", "C7 数控冲床", "LINE-02", "stop", 0,
     [("主轴", "0 rpm"), ("负荷", "0%"), ("停机", "26min")],
     "已停机", "刀具磨损报警触发联锁", "WO-2038", "08:37"),
    ("DEV-A1-01", "A1 注塑机", "LINE-01", "run", 88,
     [("模温", "196°C"), ("负荷", "88%"), ("节拍", "40.1s")],
     "运行中", "稳定运行 6h12m", "—", "02:51"),
    ("DEV-B1-01", "B1 视觉检测工位", "LINE-03", "run", 71,
     [("通过率", "97.1%"), ("负荷", "71%"), ("节拍", "41.3s")],
     "复检中", "通过率低于基线", "观察中", "08:41"),
    ("DEV-D2-03", "D2 焊接机器人", "LINE-01", "run", 65,
     [("电流", "142A"), ("负荷", "65%"), ("节拍", "39.5s")],
     "运行中", "稳定运行 3h40m", "—", "05:23"),
    ("DEV-E5-02", "E5 空压机组", "公用", "warn", 92,
     [("压力", "0.72MPa"), ("负荷", "92%"), ("油温", "76°C")],
     "预警", "压力波动接近下限", "PM-E5-11", "06:14"),
    ("DEV-A2-02", "A2 注塑机", "LINE-02", "run", 79,
     [("模温", "201°C"), ("负荷", "79%"), ("节拍", "43.8s")],
     "运行中", "稳定运行 5h02m", "—", "04:01"),
    ("DEV-F4-01", "F4 包装线", "LINE-01", "idle", 4,
     [("状态", "IDLE"), ("负荷", "4%"), ("等待", "8min")],
     "待料", "等待上游来料", "正常", "08:12"),
]

# code, level(err/warn/info), title, device_code, line_code, occurred_at, detail, sop_ref, status
ALERTS = [
    ("AL-0901", "err", "C7 数控冲床 · 刀具磨损联锁停机", "DEV-C7-01", "LINE-02", "08:37",
     "磨损量超阈值，设备已安全联锁停机，等待更换刀具。", "WO-2038", "open"),
    ("AL-0902", "warn", "A3 注塑机 · 模温超上限", "DEV-A3-02", "LINE-03", "07:51",
     "实测 218°C / 上限 205°C，持续 12 分钟，已自动降速至 60% 负荷运行。", "SOP-INJ-07 §4.2", "open"),
    ("AL-0903", "warn", "E5 空压机组 · 压力接近下限", "DEV-E5-02", "公用", "06:14",
     "系统压力 0.72MPa，低于设定 0.75MPa。", "PM-E5-11", "open"),
    ("AL-0904", "info", "F4 包装线 · 等待上游来料", "DEV-F4-01", "LINE-01", "08:12",
     "停机 8 分钟，属计划内换批等待。", None, "open"),
    ("AL-0905", "info", "B1 装配工位 · 视觉复检通过率回落", "DEV-B1-01", "LINE-03", "08:41",
     "近 30 分钟通过率 97.1%，低于基线 99.0%，可能与 A3 来料波动相关。", None, "open"),
]

# code, title, status, priority, device_code, line_code, assignee, remaining, sop_ref,
# confidence, hint_cnt, hit_cnt, done_at, created_at
WORK_ORDERS = [
    ("WO-2042", "E5 空压机组月度保养 — 更换滤芯", "pending", "P3", "DEV-E5-02", "公用",
     None, "计划 09/30", "PM-E5-11", None, None, None, None, "09/28 10:00"),
    ("WO-2040", "B1 视觉工位相机标定校准", "pending", "P2", "DEV-B1-01", "LINE-03",
     None, "计划 09/29 PM", "SOP-VIS-02", None, None, None, None, "09/28 09:20"),
    ("WO-2041", "A3 注塑机模温超限 — 检查冷却水路与温控阀", "doing", "P2", "DEV-A3-02", "LINE-03",
     "李", "剩余 32min", "SOP-INJ-07 §4.2", 62, 29, 18, None, "09/29 07:55"),
    ("WO-2038", "C7 数控冲床刀具更换 — 磨损联锁复位", "doing", "P2", "DEV-C7-01", "LINE-02",
     "周", "剩余 50min", "SOP-CNC-03", 74, 22, 16, None, "09/29 08:40"),
    ("WO-2036", "D2 焊接机器人焊枪清理与校准", "doing", "P3", "DEV-D2-03", "LINE-01",
     "王", "进行 1h20m", "SOP-WLD-01", None, None, None, None, "09/29 06:10"),
    ("WO-2043", "A1 注塑机液压油位补充与检漏", "accepting", "P3", "DEV-A1-01", "LINE-01",
     "赵", "待质检确认", "SOP-HYD-05", None, None, None, None, "09/28 15:30"),
    ("WO-2039", "F4 包装线传送带张紧调整", "done", "P3", "DEV-F4-01", "LINE-01",
     "陈", "07:40 完成", "SOP-PKG-04", None, None, None, "09/29 07:40", "09/29 06:50"),
    ("WO-2035", "A2 注塑机料筒清理", "done", "P3", "DEV-A2-02", "LINE-02",
     "刘", "昨日 22:10", None, None, None, None, "09/28 22:10", "09/28 20:30"),
]

# scope, key, label, value, unit, prev_value, delta, target, attainment, trend, extra_json
METRICS = [
    ("report", "oee", "综合 OEE", 84.6, "%", 82.3, 2.3, 85.0, 99.5, "up", None),
    ("report", "output", "总产出", 28640, "件", None, 3.8, None, None, "up", None),
    ("report", "fpy", "一次良率 FPY", 98.1, "%", 98.3, -0.2, 98.5, 99.6, "down", None),
    ("report", "downtime", "非计划停机", 4.2, "h", 3.1, 1.1, 3.0, 71.4, "down", None),
    ("devices", "online_rate", "设备在线率", 87.5, "%", None, None, 95.0, None, "flat", "7 / 8 台在线"),
    ("devices", "open_alerts", "待处理告警", 5, "条", None, None, None, None, "flat", "1 严重 · 2 一般 · 2 提示"),
    ("devices", "mtbf", "平均无故障时长", 312, "h", None, 4.1, None, None, "up", None),
    ("devices", "avg_load", "平均负载", 57.4, "%", None, None, None, None, "flat", "处于合理区间"),
]

# 报表·重点指标明细 (含上周/环比/目标/达成)
DETAIL_METRICS = [
    ("设备在线率", 91.7, "%", 95.8, -4.1, 95.0, 96.5),
    ("单位能耗", 18.6, "kWh/千件", 19.2, -3.1, 19.0, None),
    ("工单按时完成率", 87.0, "%", 89.5, -2.5, 90.0, 96.7),
]

# 近 14 天产出与良率（09/16 - 09/29，由报表 SVG 反算）
DAILY = [
    ("09/16", 3360, 98.00), ("09/17", 3920, 98.15), ("09/18", 2880, 97.85),
    ("09/19", 4240, 98.25), ("09/20", 3600, 98.05), ("09/21", 4560, 98.35),
    ("09/22", 3760, 98.10), ("09/23", 3120, 97.90), ("09/24", 4320, 98.25),
    ("09/25", 4880, 98.45), ("09/26", 4000, 98.15), ("09/27", 3520, 98.00),
    ("09/28", 4480, 98.30), ("09/29", 4800, 98.40),
]

# 近 7 天三线 FPY（09/23 - 09/29）
FPY_LINES = {
    "LINE-03": [98.20, 98.40, 97.10, 98.05, 98.50, 98.65, 98.75],
    "LINE-01": [97.85, 98.00, 97.70, 98.05, 98.20, 98.30, 98.40],
    "LINE-02": [97.55, 97.65, 97.40, 97.75, 97.85, 97.95, 98.05],
}
FPY_DATES = ["09/23", "09/24", "09/25", "09/26", "09/27", "09/28", "09/29"]

# code, title, category, device_code, content, source
SOP_DOCS = [
    ("SOP-INJ-07",
     "注塑机模温异常处置作业指导书",
     "设备异常处置", "DEV-A3-02",
     "适用范围：A1/A2/A3 系列注塑机。\n"
     "§4.1 模温预警：当实测模温超过工艺上限 5°C 或持续 3 分钟呈上升趋势时触发预警，"
     "应记录模温曲线并通知工艺工程师。\n"
     "§4.2 模温超限处置：当模温超过上限（A3 机型上限 205°C）持续 10 分钟以上，"
     "系统自动降速至 60% 负荷。值班人员应依次检查：① 冷却水路是否堵塞或流量不足；"
     "② 温控阀开度与反馈信号是否一致；③ 加热圈是否粘连或失控；④ 料筒温度传感器是否漂移。"
     "确认冷却水路异常时，应停机切换备用模具或申请维修工单，禁止在降速状态连续生产超过 2 小时。\n"
     "§4.3 复位条件：模温回落至上限以下并稳定 15 分钟后，方可申请恢复满速运行。",
     "工艺部 · 注塑作业标准 v3.2"),
    ("SOP-CNC-03",
     "数控冲床刀具磨损与更换作业指导书",
     "设备维修", "DEV-C7-01",
     "适用范围：C 系列数控冲床。\n"
     "§3.1 刀具磨损判定：当磨损量传感器读数超过阈值 0.15mm 或冲压毛刺率上升时，"
     "系统触发联锁停机以保护模具。\n"
     "§3.2 更换流程：① 确认设备已联锁停机并挂检修牌；② 拆卸旧刀具，检查刀座有无崩边；"
     "③ 安装新刀具并按扭矩表紧固；④ 执行对刀与试冲，确认首件合格；⑤ 复位联锁并恢复生产。\n"
     "§3.3 安全要求：更换刀具必须双人作业，禁止带电拆装。",
     "设备部 · 机加工作业标准 v2.8"),
    ("SOP-VIS-02",
     "视觉检测工位标定与通过率管控指导书",
     "质量控制", "DEV-B1-01",
     "适用范围：B 系列视觉检测工位。\n"
     "§2.1 标定周期：每生产班次开机前标定一次，换批或更换工装后必须重新标定。\n"
     "§2.2 通过率监控：当近 30 分钟通过率低于基线 99.0% 时触发复检；"
     "复检仍低于 97.5% 应停机排查光源、镜头与相机参数。\n"
     "§2.3 常见原因：光源衰减、镜头污染、相机偏移、上游来料波动、算法阈值漂移。",
     "质量部 · 视觉检测标准 v1.6"),
    ("SOP-WLD-01",
     "焊接机器人焊枪清理与校准指导书",
     "设备保养", "DEV-D2-03",
     "适用范围：D 系列焊接机器人。\n"
     "§1.1 每 8 小时清理焊枪喷嘴飞溅，检查导电嘴磨损。\n"
     "§1.2 校准流程：① 清理喷嘴与导电嘴；② 检测送丝速度与电流（标准 140A±10A）；"
     "③ 校准焊接姿态与 TCP；④ 试焊首件并做外观与熔深检查。\n"
     "§1.3 电流异常偏高时应检查送丝机构与地线接触。",
     "设备部 · 焊接作业标准 v2.1"),
    ("SOP-PKG-04",
     "包装线传送带张紧与维护指导书",
     "设备保养", "DEV-F4-01",
     "适用范围：F 系列包装线。\n"
     "§5.1 传送带打滑或跑偏时检查张紧机构，按标准张力调整。\n"
     "§5.2 待料停机属计划内等待，超过 15 分钟应记录并通知物流确认来料节奏。\n"
     "§5.3 每月检查滚筒轴承润滑与皮带磨损。",
     "设备部 · 包装作业标准 v1.3"),
    ("SOP-EQP-11",
     "空压机组月度保养作业指导书（PM-E5-11）",
     "计划保养", "DEV-E5-02",
     "适用范围：E5 空压机组及公用动力系统。\n"
     "§6.1 月度保养项：更换空气滤芯、油滤与油分离芯，检查油位与油温（正常 65~85°C）。\n"
     "§6.2 压力管控：系统压力设定 0.75MPa，低于 0.72MPa 触发预警，"
     "应检查滤芯堵塞、管路泄漏与卸载阀动作。\n"
     "§6.3 保养窗口：每月末计划停机 2 小时执行，避开生产高峰。",
     "动力部 · 公用工程保养标准 v4.0"),
    ("SOP-HYD-05",
     "注塑机液压系统油位补充与检漏指导书",
     "设备维修", "DEV-A1-01",
     "适用范围：A 系列注塑机液压单元。\n"
     "§7.1 油位低于下限时补充同牌号液压油，禁止混用。\n"
     "§7.2 检漏流程：① 清洁管路接头；② 保压 30 分钟观察压降；"
     "③ 检查油缸密封与快换接头；④ 补油后记录油温与压力曲线。\n"
     "§7.3 发现持续渗漏应停机并申请维修工单。",
     "设备部 · 液压系统标准 v2.4"),
]


def reset(conn):
    for tbl in ("lines", "devices", "alerts", "work_orders", "metrics",
                "daily_stats", "sop_docs"):
        conn.execute(f"DELETE FROM {tbl}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))


def seed():
    conn = get_conn()
    init_db()
    reset(conn)

    conn.executemany(
        "INSERT INTO lines(code,name,status,device_total,device_online,shift_output,"
        "takt,takt_target,oee,fpy) VALUES(?,?,?,?,?,?,?,?,?,?)",
        LINES,
    )

    import json
    conn.executemany(
        "INSERT INTO devices(code,name,line_code,state,load_pct,metrics_json,note,"
        "foot,ref,since) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(c, n, ln, st, ld, json.dumps([{"label": l, "value": v} for l, v in ms],
                                       ensure_ascii=False),
          note, foot, ref, since)
         for c, n, ln, st, ld, ms, note, foot, ref, since in DEVICES],
    )

    conn.executemany(
        "INSERT INTO alerts(code,level,title,device_code,line_code,occurred_at,"
        "detail,sop_ref,status) VALUES(?,?,?,?,?,?,?,?,?)",
        ALERTS,
    )

    conn.executemany(
        "INSERT INTO work_orders(code,title,status,priority,device_code,line_code,"
        "assignee,remaining,sop_ref,confidence,hint_cnt,hit_cnt,done_at,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        WORK_ORDERS,
    )

    rows = []
    for scope, key, label, val, unit, prev, delta, target, att, trend, extra in METRICS:
        rows.append((scope, key, label, val, unit, prev, delta, target, att, trend, extra))
    for label, val, unit, prev, delta, target, att in DETAIL_METRICS:
        rows.append(("report_detail", label, label, val, unit, prev, delta, target, att,
                     "down" if delta < 0 else "up", None))
    conn.executemany(
        "INSERT INTO metrics(scope,key,label,value,unit,prev_value,delta,target,"
        "attainment,trend,extra_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )

    daily_rows = [(d, "ALL", out, fpy, None, None, None) for d, out, fpy in DAILY]
    for line_code, series in FPY_LINES.items():
        for d, fpy in zip(FPY_DATES, series):
            daily_rows.append((d, line_code, None, fpy, None, None, None))
    conn.executemany(
        "INSERT INTO daily_stats(stat_date,line_code,output,fpy,oee,downtime_h,"
        "energy_int) VALUES(?,?,?,?,?,?,?)",
        daily_rows,
    )

    conn.executemany(
        "INSERT INTO sop_docs(code,title,category,device_code,content,source)"
        " VALUES(?,?,?,?,?,?)",
        SOP_DOCS,
    )

    conn.commit()
    conn.close()
    rebuild_fts()
    with get_conn() as c2:
        counts = {t: c2.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("lines", "devices", "alerts", "work_orders", "metrics",
                            "daily_stats", "sop_docs")}
    return counts


if __name__ == "__main__":
    result = seed()
    print(f"seeded {DB_PATH}")
    for k, v in result.items():
        print(f"  {k}: {v}")
