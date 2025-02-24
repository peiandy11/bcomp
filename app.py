from flask import Flask
from RSI_trand_analysis import rsi_bp  # 从 RSI_trand_analysis.py 导入蓝图

app = Flask(__name__)
# 注册蓝图，将 RSI 功能放在 /rsi 路径下（你也可以不设置 url_prefix，这样就直接在根路径访问）
app.register_blueprint(rsi_bp, url_prefix='/rsi')

# 如果你还想保留原来的 "Hello, world!" 路由，可以添加如下路由：
@app.route('/')
def home():
    return "Hello, world! 访问 /rsi 查看 RSI 分析功能。"

if __name__ == '__main__':
    app.run(debug=True)
