from flask import Flask, render_template_string, request
import yfinance as yf
from datetime import datetime

app = Flask(__name__)

def calculate_values(ticker):
    """
    计算两种情况的结果：
    
    情况1（如果明天开盘平开）：假设明天的开盘价与当天收盘价相等，
      明天如果不三破五，则要求当天的收盘价 X 应大于 (3*(p₂+p₃) - 2*p₁) / 4，
      其中 p₁ 为昨日收盘价，p₂ 为前天收盘价，p₃ 为三天前收盘价。
      
    情况2（按找目前价格）：假设以当前市场价格作为当天的收盘价 X，
      为使明天 MA3 ≈ MA5，则要求明天的开盘价 Y 应大于 (3*(p₂+p₃) - 2*(X+p₁)) / 2。
      
    返回：
      X_threshold: 情况1中当天的收盘价要求
      Y_required: 情况2中明天的开盘价要求
    """
    try:
        # 获取最近 10 天数据，过滤掉当天数据（因为当天数据可能未更新完整）
        data = yf.download(ticker, period="10d", interval="1d")
    except Exception as e:
        return None, None, f"下载数据时出错：{e}"
    
    today_str = datetime.today().strftime('%Y-%m-%d')
    data = data[data.index.strftime('%Y-%m-%d') < today_str]
    
    # 至少需要 3 个交易日数据
    if len(data) < 3:
        return None, None, "数据不足，无法计算目标价。"
    
    data = data.sort_index()
    last3 = data.iloc[-3:]
    # 顺序：p₃ 为三天前，p₂ 为前天，p₁ 为昨日收盘价
    p3 = last3.iloc[0]['Close']
    p2 = last3.iloc[1]['Close']
    p1 = last3.iloc[2]['Close']
    
    # 情况1：如果明天开盘平开，求解 X 的要求
    X_threshold = (3 * (p2 + p3) - 2 * p1) / 4.0
    X_threshold = float(X_threshold)  # 确保 X_threshold 是一个浮点数
    
    # 情况2：按当前市场价格作为 X，获取当前价格
    ticker_obj = yf.Ticker(ticker)
    try:
        current_price = ticker_obj.info.get("regularMarketPrice", None)
    except Exception as e:
        current_price = None
    
    if current_price is None:
        Y_required = None
        error = "未能获取当前价格，无法计算情况2所需的 Y。"
    else:
        Y_required = (3 * (p2 + p3) - 2 * (current_price + p1)) / 2.0
        Y_required = float(Y_required)  # 确保 Y_required 是一个浮点数
        error = None
    
    return X_threshold, Y_required, error

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    if request.method == 'POST':
        command = request.form.get('command', '').strip()
        if not command:
            error = "股票代码不能为空。"
        else:
            # 将输入的股票代码统一转换为大写（大小写均可识别）
            ticker = command.upper()
            X_threshold, Y_required, err = calculate_values(ticker)
            if err:
                error = err
            else:
                result = f"【情况1：如果明天开盘平开】<br>" \
                         f"明天如果不三破五，{ticker} 当天的收盘价应大于 {X_threshold:.2f}<br><br>"
                if Y_required is not None:
                    result += f"【情况2：按照目前价格】<br>" \
                              f"明天如果不三破五，{ticker} 明天的开盘价应大于 {Y_required:.2f}"
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>行为金融三破五计算器</title>
    </head>
    <body>
      <h1>行为金融三破五计算器</h1>
      <form method="post">
        <label for="command">请输入股票代码（大小写均可）：</label>
        <input type="text" id="command" name="command" placeholder="例如：ROKU" required>
        <button type="submit">提交</button>
      </form>
      {% if error %}
        <p style="color: red;">{{ error|safe }}</p>
      {% endif %}
      {% if result %}
        <p style="color: green;">{{ result|safe }}</p>
      {% endif %}
    </body>
    </html>
    """, result=result, error=error)

if __name__ == '__main__':
    app.run(debug=True)
