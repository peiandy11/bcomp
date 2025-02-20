from flask import Flask, render_template_string, request
import yfinance as yf
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)

def calculate_values(ticker):
    try:
        # 获取最近 10 天数据
        data = yf.download(ticker, period="10d", interval="1d")
    except Exception as e:
        return None, None, None, None, None, None, None, f"下载数据时出错：{e}"
    
    # 获取当前美东时间
    eastern = pytz.timezone('US/Eastern')
    current_time = datetime.now(eastern)
    
    # 判断市场状态：美东时间 9:30～16:00 为盘中，否则视为已收盘
    market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
    if market_open <= current_time <= market_close:
        market_status = "盘中"
    else:
        market_status = "已收盘"
    
    # 根据市场状态决定是否包含今天数据
    today_str = datetime.today().strftime('%Y-%m-%d')
    if market_status == "已收盘":
        # 已收盘，包含今天数据
        data = data[data.index.strftime('%Y-%m-%d') <= today_str]
    else:
        # 盘中，排除今天数据（数据可能不完整）
        data = data[data.index.strftime('%Y-%m-%d') < today_str]
    
    # 至少需要 5 个交易日数据
    if len(data) < 5:
        return None, None, None, None, None, None, None, "数据不足，无法计算目标价。"
    
    data = data.sort_index()
    last5 = data.iloc[-5:]
    # 将过去 5 个交易日的收盘价（按从最早到最新排列）转换为浮点数
    # 注：在“已收盘”时：p1 为今天收盘，p2 为昨日，p3 为前天，p4 为三天前，p5 为四天前
    # 在“盘中”时：数据不含今天，所以 p1 为昨日，p2 为前天，p3 为三天前，p4 为四天前，p5 为五天前（不使用）
    p5 = float(last5.iloc[0]['Close'])
    p4 = float(last5.iloc[1]['Close'])
    p3 = float(last5.iloc[2]['Close'])
    p2 = float(last5.iloc[3]['Close'])
    p1 = float(last5.iloc[4]['Close'])
    last5_prices = [p5, p4, p3, p2, p1]
    
    # 用所有可用数据计算 MA3 和 MA5来判断破位状态
    MA3 = data['Close'].rolling(window=3).mean().iloc[-1]
    MA5 = data['Close'].rolling(window=5).mean().iloc[-1]
    try:
        MA3 = float(MA3)
        MA5 = float(MA5)
    except Exception:
        return None, None, None, None, None, None, None, "无法计算 MA 指标。"
    
    breakdown_status = "未破位" if MA3 >= MA5 else "已破位"
    
    # 根据市场状态分别计算预测值：
    if market_status == "盘中":
        # 在盘中：
        # 使用当前实时价格作为今天预测收盘代理（记为 X0）
        ticker_obj = yf.Ticker(ticker)
        try:
            current_price = ticker_obj.info.get("regularMarketPrice", None)
        except Exception as e:
            current_price = None
        
        # 逻辑1：计算 X-今日不破位收盘价，使用公式：
        # X = [3*(p3+p4) - 2*(p1+p2)] / 2, 其中 p1 为昨日收盘, p2 为前天, p3 为三天前, p4 为四天前
        X = (3 * (p3 + p4) - 2 * (p1 + p2)) / 2.0
        
        # 逻辑3：计算 Z-明日不破位收盘价预测，使用公式：
        # Z = [3*(p2+p3) - 2*(X0+p1)] / 2, 其中 X0 为当前实时价格, p1 为昨日收盘, p2 为前天, p3 为三天前
        if current_price is None:
            Z = None
            error = "未能获取当前实时价格，无法预测明天收盘价。"
        else:
            Z = (3 * (p2 + p3) - 2 * (current_price + p1)) / 2.0
            error = None
        
        Y = None  # 盘中时不计算 Y
    else:
        # 已收盘：
        # 使用今天实际收盘，p1 为今天收盘, p2 为昨日, p3 为前天, p4 为三天前
        Y = (3 * (p3 + p4) - 2 * (p1 + p2)) / 2.0
        X = None
        Z = None
        # 为一致性，可尝试获取当前价格，但此时以今天收盘价为准
        ticker_obj = yf.Ticker(ticker)
        try:
            current_price = ticker_obj.info.get("regularMarketPrice", None)
        except Exception as e:
            current_price = None
        error = None
    
    return float(X) if X is not None else None, float(Y) if Y is not None else None, float(Z) if Z is not None else None, current_price, last5_prices, market_status, current_time, breakdown_status, error

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    # 初始时我们不显示预测结果
    if request.method == 'POST':
        command = request.form.get('command', '').strip()
        if not command:
            error = "股票代码不能为空。"
        else:
            ticker = command.upper()
            X, Y, Z, current_price, last5_prices, market_status, current_time, breakdown_status, err = calculate_values(ticker)
            if err:
                error = err
            else:
                current_time_str = current_time.strftime('%Y-%m-%d %H:%M:%S %Z')
                tomorrow_str = (current_time + timedelta(days=1)).strftime('%Y-%m-%d')
                if market_status == "盘中":
                    result = (
                        f"股票: {ticker} | 当前实时价格: {current_price if current_price is not None else 'N/A'} | 时间: {current_time_str}<br>"
                        f"过去五个交易日的情况: {', '.join([f'{price:.2f}' for price in last5_prices])}<br>"
                        f"当前破位状态: {breakdown_status}<br>"
                        f"【今日不破位收盘价】如果今天平开，预测收盘价需达到 {X:.2f}<br>"
                        f"【明日不破位收盘价预测】预测明天收盘价需达到 {Z:.2f}"
                    )
                else:
                    result = (
                        f"股票: {ticker} | 今天收盘价: {last5_prices[4]:.2f} | 时间: {current_time_str}<br>"
                        f"过去五个交易日的情况: {', '.join([f'{price:.2f}' for price in last5_prices])}<br>"
                        f"当前破位状态: {breakdown_status}<br>"
                        f"【明日不破位收盘价】预测明天收盘价需达到 {Y:.2f}"
                    )
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>行为金融三破五计算器</title>
      <style>
        body { font-family: Arial, sans-serif; margin: 20px; padding: 0; font-size: 16px; line-height: 1.5; }
        input[type="text"] { font-size: 1.2rem; padding: 8px; width: 70%; max-width: 300px; }
        button { font-size: 1.2rem; padding: 8px 16px; margin-left: 10px; }
        .result { margin-top: 20px; color: green; }
        .error { margin-top: 20px; color: red; }
      </style>
    </head>
    <body>
      <h1>行为金融三破五计算器</h1>
      <form method="post">
        <label for="command">请输入股票代码（大小写均可）：</label><br>
        <input type="text" id="command" name="command" placeholder="例如：PTON" required>
        <button type="submit">提交</button>
      </form>
      {% if error %}
        <div class="error">{{ error|safe }}</div>
      {% endif %}
      {% if result %}
        <div class="result">{{ result|safe }}</div>
      {% endif %}
    </body>
    </html>
    """, result=result, error=error)

if __name__ == '__main__':
    app.run(debug=True)

