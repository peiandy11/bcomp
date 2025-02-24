from flask import Flask, render_template, request
import yfinance as yf
import pandas as pd
import numpy as np

# 创建蓝图对象，名字可以自定义，比如 rsi_bp
rsi_bp = Blueprint('rsi_bp', __name__)

def compute_rsi(series, period=14):
    """
    计算 RSI 指标（Wilder 原始算法平滑版本）
    :param series: pd.Series, 收盘价序列
    :param period: int, RSI 的周期
    :return: pd.Series, RSI 数值
    """
    delta = series.diff()

    # 将涨跌分开
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # 用 Wilder 平滑方式计算平均涨跌
    # 初始值用前 period 天的均值
    avg_gain = gain.rolling(window=period, min_periods=period).mean() 
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # 从第 period+1 天开始用公式更新
    for i in range(period + 1, len(series)):
        avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

@app.route('/', methods=['GET', 'POST'])
def index():
    results = []
    total_wins = 0  # 胜利次数
    total_games = 0  # 总次数

    if request.method == 'POST':
        ticker = request.form['ticker']
        df = yf.download(ticker, start="2020-01-01", end="2025-02-22")
        df.dropna(inplace=True)
        df['RSI'] = compute_rsi(df['Close'], period=6)

        # ============ 2. 寻找 RSI 突破 90 的点并统计数据 =============
        for i in range(1, len(df)):
            if df['RSI'].iloc[i] > 90 and df['RSI'].iloc[i-1] <= 90:
                cross_date = df.index[i]
                cross_price = df['Close'].iloc[i]

                # 找持续上涨的天数
                j = i + 1
                while j < len(df) and df['Close'].iloc[j].item() >= df['Close'].iloc[j-1].item():
                    j += 1

                # j 就是"转跌日"或超出数据范围
                up_days = j - i - 1  # 持续上涨的天数
                peak_price = df['Close'].iloc[i:j].max()  # RSI>90 后到转跌前的最高价

                # 转跌日的价格
                if j < len(df):
                    turn_down_date = df.index[j]
                    turn_down_price = df['Close'].iloc[j].item()  # 提取单个值
                    # 计算跌幅
                    previous_close = df['Close'].iloc[j-1].item()  # 提取前一天的收盘价
                    drop_percentage = (turn_down_price - previous_close) / previous_close * 100  # 计算跌幅百分比
                else:
                    # 数据已到末尾，没有转跌日
                    turn_down_date = None
                    turn_down_price = np.nan
                    drop_percentage = None  # 没有跌幅

                # 计算转跌日之后 3 天的回调幅度
                if j + 5 < len(df):
                    price_after_3 = df['Close'].iloc[j+5].item()  # 提取单个值
                    drawdown_3d = (price_after_3 - turn_down_price) / turn_down_price  # 直接使用浮点数
                else:
                    drawdown_3d = None

                # 计算 T 日的收盘价和 T+1 到 T+5 日的收盘价
                t_close_price = df['Close'].iloc[i].item()  # T 日的收盘价
                t_plus_prices = [df['Close'].iloc[i + j].item() if i + j < len(df) else None for j in range(1, 6)]  # T+1 到 T+5 日的收盘价
                t_plus_changes = [(price - t_close_price) / t_close_price * 100 if price is not None else None for price in t_plus_prices]  # 计算涨跌幅

                # 计算胜率
                win = 1 if t_plus_prices[4] is not None and t_plus_prices[4] > t_close_price else 0  # 胜利标记
                total_games += 1  # 每次突破都算作一次游戏
                total_wins += win  # 累加胜利次数

                # 添加调试信息
                print(f"RSI突破日: {cross_date}, 突破时收盘价: {cross_price}, 上涨持续天数: {up_days}, 这段时间内最高价: {peak_price}, 转跌日: {turn_down_date}, 转跌日收盘价: {turn_down_price}, 跌幅: {drop_percentage:.2f}%" if drawdown_3d is not None else "转跌后3天回调幅度: 无")

                results.append({
                    "RSI突破日": cross_date,
                    "突破时收盘价": f"{cross_price.item():.2f}",  # 提取单个值并保留两位小数
                    "上涨持续天数": up_days,
                    "这段时间内最高收盘价": f"{peak_price.item():.2f}",  # 提取单个值并保留两位小数
                    "转跌日": turn_down_date,
                    "转跌日收盘价": f"{turn_down_price:.2f}" if turn_down_price is not None else None,  # 直接使用浮点数并保留两位小数
                    "转跌日当天跌幅": f"<span class='{'positive' if drop_percentage > 0 else 'negative'}'>{drop_percentage:.2f}%</span>" if drop_percentage is not None else None,  # 涨幅百分比
                    "转跌后3天回调幅度(正涨负跌)": f"<span class='{'positive' if (drawdown_3d * 100) > 0 else 'negative'}'>{(drawdown_3d * 100):.2f}%</span>" if drawdown_3d is not None else None,  # 转换为百分比并保留两位小数
                    "T日收盘价": f"{t_close_price:.2f}",  # T 日收盘价
                    "T+1日收盘价": f"{t_plus_prices[0]:.2f}" if t_plus_prices[0] is not None else None,  # T+1 日收盘价
                    "T+1日涨跌幅": f"<span class='{'positive' if t_plus_changes[0] > 0 else 'negative'}'>{t_plus_changes[0]:.2f}%</span>" if t_plus_changes[0] is not None else None,  # T+1 日涨跌幅
                    "T+2日涨跌幅": f"<span class='{'positive' if t_plus_changes[1] > 0 else 'negative'}'>{t_plus_changes[1]:.2f}%</span>" if t_plus_changes[1] is not None else None,  # T+2 日涨跌幅
                    "T+3日涨跌幅": f"<span class='{'positive' if t_plus_changes[2] > 0 else 'negative'}'>{t_plus_changes[2]:.2f}%</span>" if t_plus_changes[2] is not None else None,  # T+3 日涨跌幅
                    "T+4日涨跌幅": f"<span class='{'positive' if t_plus_changes[3] > 0 else 'negative'}'>{t_plus_changes[3]:.2f}%</span>" if t_plus_changes[3] is not None else None,  # T+4 日涨跌幅
                    "T+5日涨跌幅": f"<span class='{'positive' if t_plus_changes[4] > 0 else 'negative'}'>{t_plus_changes[4]:.2f}%</span>" if t_plus_changes[4] is not None else None,  # T+5 日涨跌幅
                    "胜率": f"{(total_wins / total_games * 100):.2f}%" if total_games > 0 else "0.00%"  # 胜率百分比
                })

        res_df = pd.DataFrame(results)

        # 计算最终胜率
        final_win_rate = (total_wins / total_games * 100) if total_games > 0 else 0  # 最终胜率

        return render_template('results.html', tables=[res_df.to_html(classes='data', index=False, escape=False)], titles=res_df.columns.values, win_rate=f"{final_win_rate:.2f}%", ticker=ticker)

    return render_template('index.html')
