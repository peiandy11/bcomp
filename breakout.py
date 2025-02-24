from flask import Flask, render_template_string, request
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)

def calculate_quarterly_stats_with_breakout_and_breakdown(symbol):
    # 下载数据：覆盖初始突破及后续统计区间
    start_date_download = "2022-07-01"
    end_date_download = "2025-02-23"
    all_data = yf.download(symbol, start=start_date_download, end=end_date_download)
    if all_data.empty:
        return None, "下载数据失败或无数据。"
    all_data.sort_index(inplace=True)
    
    # 计算 MA3 与 MA5（用于破位判断），滚动计算可能会在前几行产生NaN，但不影响后续遍历
    all_data['MA3'] = all_data['Close'].rolling(window=3).mean()
    all_data['MA5'] = all_data['Close'].rolling(window=5).mean()
    
    # -----------------------------
    # 1. 初始突破目标：取 2022-07-01 至 2023-01-01 内的最高价（保留3位小数）
    date_2023_01_01 = pd.Timestamp("2023-01-01")
    data_initial = all_data.loc[start_date_download:"2023-01-01"]
    if not data_initial.empty:
        initial_breakout_target = data_initial["High"].max()
    else:
        initial_breakout_target = all_data["High"].max()
    if pd.isna(initial_breakout_target):
        return None, "无法确定初始突破目标价，数据可能不足。"
    initial_breakout_target = round(initial_breakout_target, 3)
    
    # -----------------------------
    # 2. 市值与缺口判断阈值
    try:
        ticker_info = yf.Ticker(symbol).info
        market_cap = ticker_info.get("marketCap", 0)
    except Exception as e:
        market_cap = 0
    # 超过500亿美元视为大型股；缺口阈值：大型股6%，否则8%
    is_large_cap = market_cap > 50e9
    gap_threshold = 0.06 if is_large_cap else 0.08
    
    # -----------------------------
    # 3. 初始化变量（突破事件、破位事件记录）
    breakout_active = False              # 是否处于突破状态
    first_breakout_completed = False     # 标记首次突破是否完成
    gap_down_price = None                # 用于补缺突破的缺口价
    last_breakout_max_price = None         # 突破过程中的最高价（用于更新当前目标和新高突破）
    current_breakout_event = None        # 正在进行的突破事件记录
    breakout_events = []                 # 正常结束（非破位）突破事件
    breakdown_events = []                # 因破位触发的突破事件记录

    # 破位相关计数
    consecutive_fail_count = 0           # “三只小乌鸦”计数（用于判断连续未突破突破日最高价的天数）
    breakout_day_high = None             # 窀突破日当天的最高价，用于“三只小乌鸦”判断

    # 遍历所有数据（从第二个交易日开始）
    for i in range(1, len(all_data)):
        today = all_data.iloc[i]
        yesterday = all_data.iloc[i - 1]
        current_date = all_data.index[i]

        # -----------------------------
        # 破位检测：仅在处于突破状态时检测
        if breakout_active:
            # 更新“三只小乌鸦”计数：如果当日收盘价未超过突破日当天的最高价则累计，否则重置
            if breakout_day_high is not None:
                if today["Close"] < breakout_day_high:
                    consecutive_fail_count += 1
                else:
                    consecutive_fail_count = 0

            breakdown_triggered = False
            breakdown_type = None

            # ① 均线拐头：当日 MA3 跌破 MA5
            if pd.notna(today["MA3"]) and pd.notna(today["MA5"]) and today["MA3"] < today["MA5"]:
                breakdown_triggered = True
                breakdown_type = "MA3 破 MA5"
            # ② 日内高位大幅下跌：开盘高于昨日收盘、收盘低于开盘且跌幅 ≥ 8%
            elif (today["Open"] > yesterday["Close"] and today["Close"] < today["Open"] and 
                  ((today["High"] - today["Close"]) / today["High"] >= 0.08)):
                breakdown_triggered = True
                breakdown_type = "日内高位-8"
            # ③ 日内低开大幅下跌：开盘低于昨日收盘且跌幅 ≥ 10%
            elif (today["Open"] < yesterday["Close"] and 
                  ((yesterday["Close"] - today["Close"]) / yesterday["Close"] >= 0.10)):
                breakdown_triggered = True
                breakdown_type = "日内低开-10"
            # ④ 三只小乌鸦：非超大型股（市值低于3000亿美元），连续3天未突破突破日最高价
            elif consecutive_fail_count >= 3 and market_cap < 3e11:
                breakdown_triggered = True
                breakdown_type = "三只小乌鸦"

            if breakdown_triggered:
                breakdown_date = current_date
                breakdown_price = round(today["Close"], 3)
                # 计算突破持续天数（交易日数，使用bdate_range计算，减去1）
                bdays = pd.bdate_range(start=current_breakout_event["date"], end=breakdown_date)
                breakout_duration = len(bdays) - 1
                if current_breakout_event["buy_price"] != 0:
                    effective_breakout = round((breakdown_price - current_breakout_event["buy_price"]) / current_breakout_event["buy_price"] * 100, 3)
                else:
                    effective_breakout = "N/A"
                # 将 MA3 破 MA5 与 三只小乌鸦均归类到“三破五”统计中
                breakdown_stat_type = breakdown_type
                if breakdown_stat_type in ["MA3 破 MA5", "三只小乌鸦"]:
                    breakdown_stat_type = "三破五"

                breakdown_events.append({
                    "股票名称": symbol,
                    "突破类型": current_breakout_event["type"],
                    "突破价": current_breakout_event["target_price"],
                    "收盘买入价": current_breakout_event["buy_price"],
                    "破位类型": breakdown_type,
                    "破位价": breakdown_price,
                    "有效突破幅度": f"{effective_breakout}%",
                    "突破日期": current_breakout_event["date"].date(),
                    "破位日期": breakdown_date.date(),
                    "突破持续天数": breakout_duration
                })
                # 破位触发后重置状态
                breakout_active = False
                consecutive_fail_count = 0
                breakout_day_high = None
                current_breakout_event = None
                continue  # 当天处理完毕，进入下一交易日

            # 如果未触发破位条件，若收盘价跌破突破目标，则视为正常结束突破
            if today["Close"] < current_breakout_event["target_price"]:
                # 结束当前突破事件（非破位退出）
                bdays = pd.bdate_range(start=current_breakout_event["date"], end=current_date)
                breakout_duration = len(bdays) - 1
                if current_breakout_event["buy_price"] != 0:
                    effective_breakout = round((today["Close"] - current_breakout_event["buy_price"]) / current_breakout_event["buy_price"] * 100, 3)
                else:
                    effective_breakout = "N/A"
                current_breakout_event["duration"] = breakout_duration
                current_breakout_event["max_amplitude"] = effective_breakout
                breakout_events.append(current_breakout_event)
                breakout_active = False
                consecutive_fail_count = 0
                breakout_day_high = None
                current_breakout_event = None
                continue
            else:
                # 突破持续：更新持续天数和期间最高有效涨幅
                bdays = pd.bdate_range(start=current_breakout_event["date"], end=current_date)
                current_breakout_event["duration"] = len(bdays) - 1
                amp = (today["Close"] - current_breakout_event["target_price"]) / current_breakout_event["target_price"] * 100
                if amp > current_breakout_event["max_amplitude"]:
                    current_breakout_event["max_amplitude"] = amp

        # -----------------------------
        # 非突破状态时，检查是否触发突破
        if not breakout_active:
            # 当前突破目标：若未完成首次突破，则固定为初始目标；否则以突破过程中的最高价更新
            if not first_breakout_completed:
                current_target = initial_breakout_target
            else:
                current_target = last_breakout_max_price if last_breakout_max_price is not None else initial_breakout_target
            current_target = round(current_target, 3)
            
            # 更新 last_breakout_max_price（始终以全数据中的最高价更新）
            if last_breakout_max_price is None:
                last_breakout_max_price = today["High"]
            else:
                last_breakout_max_price = max(last_breakout_max_price, today["High"])
            
            # ① 补缺突破：仅在2023-01-01之后且首次突破完成后
            if current_date >= pd.Timestamp("2023-01-01") and first_breakout_completed:
                if gap_down_price is None:
                    # 判断是否出现跳空缺口： (昨日最低 - 今日最高)/昨日最低 ≥ 阈值
                    if (yesterday["Low"] - today["High"]) / yesterday["Low"] >= gap_threshold:
                        gap_down_price = round(yesterday["Low"], 3)
                if gap_down_price is not None and today["Close"] > gap_down_price:
                    breakout_active = True
                    breakout_type = "补缺突破"
                    current_breakout_event = {
                        "date": current_date,
                        "type": breakout_type,
                        "target_price": gap_down_price,
                        "buy_price": round(today["Close"], 3),
                        "duration": 1,
                        "max_amplitude": (today["Close"] - gap_down_price) / gap_down_price * 100
                    }
                    # 记录突破日当天的最高价（用于三只小乌鸦计数）
                    breakout_day_high = today["High"]
                    gap_down_price = None
                    continue

            # ② 首次突破：2023-01-01之后，当前未处于突破状态且尚未完成首次突破时
            if current_date >= pd.Timestamp("2023-01-01") and (not breakout_active) and (not first_breakout_completed) and today["Close"] > current_target:
                breakout_active = True
                breakout_type = "首次突破"
                current_breakout_event = {
                    "date": current_date,
                    "type": breakout_type,
                    "target_price": current_target,
                    "buy_price": round(today["Close"], 3),
                    "duration": 1,
                    "max_amplitude": (today["Close"] - current_target) / current_target * 100
                }
                first_breakout_completed = True
                breakout_day_high = today["High"]
                continue

            # ③ 新高突破：在首次突破完成后，若当日收盘价刷新此前突破过程中的最高价
            if first_breakout_completed and (not breakout_active) and (last_breakout_max_price is not None) and today["Close"] > last_breakout_max_price:
                breakout_active = True
                breakout_type = "新高突破"
                current_breakout_event = {
                    "date": current_date,
                    "type": breakout_type,
                    "target_price": last_breakout_max_price,
                    "buy_price": round(today["Close"], 3),
                    "duration": 1,
                    "max_amplitude": (today["Close"] - last_breakout_max_price) / last_breakout_max_price * 100
                }
                breakout_day_high = today["High"]
                last_breakout_max_price = today["High"]
                continue

    # 循环结束后，若仍处于突破状态，则将其归档为正常突破事件
    if breakout_active and current_breakout_event is not None:
        # 以最后一天收盘价结束
        bdays = pd.bdate_range(start=current_breakout_event["date"], end=all_data.index[-1])
        current_breakout_event["duration"] = len(bdays) - 1
        amp = (all_data.iloc[-1]["Close"] - current_breakout_event["target_price"]) / current_breakout_event["target_price"] * 100
        current_breakout_event["max_amplitude"] = amp
        breakout_events.append(current_breakout_event)
        breakout_active = False

    # -----------------------------
    # 4. 仅对分析期内（2023-07-01 至 2025-02-23）的事件进行统计
    analysis_start = pd.Timestamp("2023-07-01")
    analysis_end = pd.Timestamp("2025-02-23")
    
    # 定义一个辅助函数，判断事件是否在分析期内（以突破日期为准）
    def in_analysis_period(event):
        return analysis_start <= event["date"] <= analysis_end

    # 合并所有结束的突破事件（无论是否因破位）
    all_events = [e for e in breakout_events if in_analysis_period(e)] + [e for e in breakdown_events if in_analysis_period({
        "date": pd.Timestamp(e["突破日期"])
    })]
    
    # 为事件按季度归类，使用突破日期
    events_by_quarter = {}
    for ev in all_events:
        # 突破事件的日期取自事件记录（对于 breakdown_events，使用“突破日期”）
        ev_date = ev.get("date", pd.NaT)
        if pd.isna(ev_date) and "突破日期" in ev:
            ev_date = pd.Timestamp(ev["突破日期"])
        quarter_label = f"{ev_date.year}Q{((ev_date.month-1)//3)+1}"
        events_by_quarter.setdefault(quarter_label, []).append(ev)
    
    # 定义各季度市场类型
    quarter_market = {
        "2023Q3": "突破市",
        "2023Q4": "突破市",
        "2024Q1": "突破市",
        "2024Q2": "震荡市",
        "2024Q3": "突破市",
        "2024Q4": "突破市",
        "2025Q1": "震荡市"
    }
    
    # -----------------------------
    # 5. 按季度统计
    results = {}
    for quarter, events in events_by_quarter.items():
        if quarter not in quarter_market:
            continue
        market_type = quarter_market[quarter]
        breakout_count = len(events)
        avg_duration = sum(ev["duration"] for ev in events) / breakout_count if breakout_count > 0 else 0
        avg_amplitude = sum(ev["max_amplitude"] for ev in events) / breakout_count if breakout_count > 0 else 0

        # 对破位情况统计：仅统计因破位触发的事件
        breakdown_types = [ev["破位类型"] for ev in breakdown_events if 
                           (analysis_start <= pd.Timestamp(ev["破位日期"]) <= analysis_end)]
        high_minus_8 = sum(1 for bt in breakdown_types if bt == "日内高位-8")
        low_minus_10 = sum(1 for bt in breakdown_types if bt == "日内低开-10")
        # 将“MA3 破 MA5”与“三只小乌鸦”归并为“三破五”
        three_break = sum(1 for bt in breakdown_types if bt in ["MA3 破 MA5", "三只小乌鸦"])

        results[quarter] = {
            "market_type": market_type,
            "breakthrough_count": breakout_count,
            "avg_breakthrough_duration": avg_duration,
            "avg_breakthrough_amplitude": avg_amplitude,
            "breakdown_stats": {
                "三破五": three_break,
                "高位-8": high_minus_8,
                "低位-10": low_minus_10
            }
        }
    
    return results, None

@app.route('/quarterly', methods=['GET', 'POST'])
def quarterly():
    result_html = ""
    error = None
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').strip().upper()
        if not ticker:
            error = "股票代码不能为空。"
        else:
            stats, err = calculate_quarterly_stats_with_breakout_and_breakdown(ticker)
            if err:
                error = err
            else:
                result_html += f"<h2>{ticker} 的季度统计结果</h2>"
                result_html += "<table border='1' cellspacing='0' cellpadding='5'>"
                result_html += "<tr><th>季度</th><th>市场类型</th><th>突破次数</th><th>平均突破维持天数</th><th>平均有效突破涨幅(%)</th><th>三破五</th><th>高位-8</th><th>低位-10</th></tr>"
                for quarter in sorted(stats.keys()):
                    data = stats[quarter]
                    result_html += "<tr>"
                    result_html += f"<td>{quarter}</td>"
                    result_html += f"<td>{data['market_type']}</td>"
                    result_html += f"<td>{data['breakthrough_count']}</td>"
                    result_html += f"<td>{data['avg_breakthrough_duration']:.2f}</td>"
                    result_html += f"<td>{data['avg_breakthrough_amplitude']:.2f}</td>"
                    result_html += f"<td>{data['breakdown_stats']['三破五']}</td>"
                    result_html += f"<td>{data['breakdown_stats']['高位-8']}</td>"
                    result_html += f"<td>{data['breakdown_stats']['低位-10']}</td>"
                    result_html += "</tr>"
                result_html += "</table>"
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>季度突破与破位统计</title>
      <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { text-align: center; padding: 8px; }
        th { background-color: #f2f2f2; }
        .error { color: red; }
      </style>
    </head>
    <body>
      <h1>季度突破与破位统计</h1>
      <form method="post">
        <label for="ticker">股票代码：</label>
        <input type="text" id="ticker" name="ticker" placeholder="例如: ROKU" required>
        <button type="submit">统计</button>
      </form>
      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}
      {% if result_html %}
        <div>{{ result_html|safe }}</div>
      {% endif %}
    </body>
    </html>
    """, result_html=result_html, error=error)

if __name__ == '__main__':
    app.run(debug=True)
