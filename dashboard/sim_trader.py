#!/usr/bin/env python3
"""
Flask 模拟交易监控看板

提供实时账户状态查看和信号执行功能：

- 主页（/）：显示总资产、现金、持仓、资金曲线、今日信号
- POST /execute：执行当日信号（买入/卖出）

集成 VirtualAccount 和 ClawStreetClient（mock模式）
监听地址：0.0.0.0:8082
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from flask import Flask, render_template_string, request, jsonify

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from virtual_account import VirtualAccount
from clients.claw_street_client import ClawStreetClient

# ============================================
# 配置与常量
# ============================================

class Config:
    """应用配置"""
    # Flask 配置
    HOST = '0.0.0.0'
    PORT = 8082
    DEBUG = True

    # 数据目录
    DATA_DIR = Path(__file__).parent.parent / 'data'
    ACCOUNTS_DIR = DATA_DIR / 'accounts'
    SIGNALS_DIR = Path(__file__).parent.parent / 'signals'
    LOGS_DIR = ACCOUNTS_DIR / 'logs'
    RAW_DATA_DIR = DATA_DIR / 'raw'

    # 文件路径
    TRADE_HISTORY_FILE = ACCOUNTS_DIR / 'trades.json'
    CSV_DATA_FILE = RAW_DATA_DIR / 'etf_history_2015_2025.csv'

    # 交易参数
    BUY_ALLOCATION_RATIO = 0.5  # 买入时使用可用现金的 50%
    SELL_RATIO = 0.5  # 卖出时卖出持仓的 50%
    FEE_RATE = 0.0005  # 交易费率 0.05%


# ============================================
# 日志配置
# ============================================

def setup_logging() -> logging.Logger:
    """配置日志记录"""
    log_dir = Config.LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('sim_trader')
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        log_file = log_dir / f"dashboard_{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


logger = setup_logging()


# ============================================
# 数据访问层
# ============================================

class DataManager:
    """数据管理器：负责读写信号、价格、账户状态"""

    @staticmethod
    def get_latest_signal_file() -> Optional[Path]:
        """获取最新的信号文件"""
        if not Config.SIGNALS_DIR.exists():
            return None
        signal_files = list(Config.SIGNALS_DIR.glob('*.json'))
        if not signal_files:
            return None
        # 按文件名（日期）排序
        latest = sorted(signal_files)[-1]
        return latest

    @staticmethod
    def load_signals(signal_file: Path) -> Dict[str, Any]:
        """加载信号文件"""
        with open(signal_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def get_latest_price_data() -> Dict[str, float]:
        """从CSV文件中获取最新交易日的价格数据"""
        if not Config.CSV_DATA_FILE.exists():
            logger.warning(f"CSV数据文件不存在: {Config.CSV_DATA_FILE}")
            return {}

        try:
            import pandas as pd
            df = pd.read_csv(Config.CSV_DATA_FILE)

            # 获取最新日期
            latest_date = df['date'].max()
            latest_data = df[df['date'] == latest_date]

            # 构建价格字典 {code: close_price}
            price_dict = {}
            for _, row in latest_data.iterrows():
                price_dict[str(row['code'])] = float(row['close'])

            logger.info(f"加载最新价格数据: {latest_date}, {len(price_dict)} 只ETF")
            return price_dict

        except Exception as e:
            logger.error(f"读取CSV数据失败: {e}")
            return {}

    @staticmethod
    def get_account_state_files() -> List[Path]:
        """获取所有账户状态文件"""
        state_dir = Config.ACCOUNTS_DIR / 'states'
        if not state_dir.exists():
            return []
        return sorted(state_dir.glob('state_*.json'))

    @staticmethod
    def load_account_states() -> List[Dict[str, Any]]:
        """加载所有历史账户状态（用于资金曲线）"""
        states = []
        for state_file in DataManager.get_account_state_files():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    states.append(state)
            except Exception as e:
                logger.warning(f"加载状态文件失败 {state_file}: {e}")
        return states


# ============================================
# Flask 应用初始化
# ============================================

app = Flask(__name__)

# 初始化虚拟账户
try:
    virtual_account = VirtualAccount(
        initial_capital=1000000.0,  # 100万元
        data_dir=str(Config.DATA_DIR)
    )
    logger.info("VirtualAccount 初始化完成")
except Exception as e:
    logger.error(f"VirtualAccount 初始化失败: {e}")
    virtual_account = None

# 初始化 ClawStreetClient（模拟模式）
try:
    claw_client = ClawStreetClient(
        api_key="demo_key",
        mock=True
    )
    logger.info("ClawStreetClient 初始化完成（mock模式）")
except Exception as e:
    logger.error(f"ClawStreetClient 初始化失败: {e}")
    claw_client = None


# ============================================
# 辅助函数
# ============================================

def format_currency(value: float) -> str:
    """格式化金额显示"""
    return f"¥{value:,.2f}"


def format_percent(value: float) -> str:
    """格式化百分比显示"""
    return f"{value:.2f}%"


def calculate_pnl_percentage(current_price: float, avg_cost: float) -> float:
    """计算盈亏百分比"""
    if avg_cost == 0:
        return 0.0
    return ((current_price - avg_cost) / avg_cost) * 100


def rebuild_equity_curve(states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    重建资金曲线数据

    参数:
        states: 账户状态列表

    返回:
        按日期排序的资金曲线数据列表
    """
    curve = []
    for state in sorted(states, key=lambda x: x['date']):
        curve.append({
            'date': state['date'],
            'total_value': state['total_value'],
            'cash': state['cash'],
            'positions_value': state['total_value'] - state['cash']
        })
    return curve


def generate_signals_from_file(signal_file: Path) -> List[Dict[str, Any]]:
    """从信号文件提取信号列表"""
    try:
        signals_data = DataManager.load_signals(signal_file)
        return signals_data.get('signals', [])
    except Exception as e:
        logger.error(f"读取信号文件失败: {e}")
        return []


# ============================================
# 路由与视图
# ============================================

@app.route('/')
def dashboard():
    """
    主页面：显示监控看板

    显示内容：
    - 总资产、现金、持仓市值
    - 持仓表格
    - 资金曲线图（Chart.js）
    - 今日信号
    """
    try:
        # 1. 获取账户当前状态
        if virtual_account:
            total_value = virtual_account.get_total_value()
            cash = virtual_account.get_balance()
            positions = virtual_account.get_positions()
        else:
            total_value = 0.0
            cash = 0.0
            positions = {}

        # 2. 获取最新价格数据
        price_data = DataManager.get_latest_price_data()

        # 3. 构建持仓表格数据（包含当前价格、市值、盈亏%）
        position_rows = []
        for symbol, pos in positions.items():
            current_price = price_data.get(symbol, pos.get('avg_cost', 0))
            market_value = pos['quantity'] * current_price
            pnl_pct = calculate_pnl_percentage(current_price, pos['avg_cost'])

            position_rows.append({
                'symbol': symbol,
                'quantity': pos['quantity'],
                'avg_price': pos['avg_cost'],
                'current_price': current_price,
                'market_value': market_value,
                'pnl_pct': pnl_pct
            })

        # 按市值排序
        position_rows.sort(key=lambda x: x['market_value'], reverse=True)

        # 4. 加载历史状态，重建资金曲线
        account_states = DataManager.load_account_states()
        equity_curve = rebuild_equity_curve(account_states)

        # 5. 加载今日信号
        latest_signal_file = DataManager.get_latest_signal_file()
        today_signals = []
        if latest_signal_file:
            today_signals = generate_signals_from_file(latest_signal_file)
            # 附加当前价格和预估交易信息
            for sig in today_signals:
                sig['current_price'] = price_data.get(sig['symbol'], None)

        # 6. 准备渲染数据
        context = {
            'total_value': total_value,
            'cash': cash,
            'positions_value': total_value - cash,
            'positions': position_rows,
            'equity_curve': equity_curve,
            'today_signals': today_signals,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'signal_file': latest_signal_file.name if latest_signal_file else '无'
        }

        return render_template_string(HTML_TEMPLATE, **context)

    except Exception as e:
        logger.error(f"渲染看板失败: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/execute', methods=['POST'])
def execute_signals():
    """
    执行当日信号

    逻辑：
    1. 读取最新的信号文件
    2. 获取最新价格数据
    3. 执行买入/卖出交易
       - 买入：使用可用现金的 50% 分配给所有买入信号（按 confidence 加权）
       - 卖出：卖出持仓的 50%（按持仓价值比例）
    4. 保存账户状态并记录日志
    5. 返回执行结果
    """
    try:
        # 1. 检查信号文件
        signal_file = DataManager.get_latest_signal_file()
        if not signal_file:
            return jsonify({'success': False, 'message': '未找到信号文件'}), 400

        signals_data = DataManager.load_signals(signal_file)
        signals = signals_data.get('signals', [])

        if not signals:
            return jsonify({'success': False, 'message': '今日无信号'}), 200

        # 2. 获取最新价格数据
        price_data = DataManager.get_latest_price_data()
        if not price_data:
            return jsonify({'success': False, 'message': '无法获取价格数据'}), 500

        # 3. 更新持仓市值
        virtual_account.update_market_prices(price_data)

        # 4. 分离买入和卖出信号
        buy_signals = [s for s in signals if s['action'] == 'buy']
        sell_signals = [s for s in signals if s['action'] == 'sell']

        results = []
        total_cash = virtual_account.get_balance()
        positions = virtual_account.get_positions()

        # 5. 处理买入信号
        if buy_signals:
            # 计算总买入额度（可用现金的 50%）
            buy_budget = total_cash * Config.BUY_ALLOCATION_RATIO

            # 按 confidence 加权分配资金
            total_confidence = sum(s['confidence'] for s in buy_signals)
            if total_confidence > 0:
                for sig in buy_signals:
                    symbol = sig['symbol']
                    price = price_data.get(symbol)
                    if not price:
                        logger.warning(f"买入信号 {symbol} 无价格数据，跳过")
                        continue

                    # 按权分配金额
                    weight = sig['confidence'] / total_confidence
                    allocated_budget = buy_budget * weight

                    # 计算可买数量（向下取整）
                    quantity = int(allocated_budget / price)
                    if quantity <= 0:
                        logger.info(f"{symbol}: 分配金额过少，无法买入")
                        continue

                    try:
                        trade = virtual_account.execute_trade(
                            symbol=symbol,
                            quantity=quantity,
                            price=price,
                            fee=Config.FEE_RATE
                        )
                        results.append({
                            'action': 'buy',
                            'symbol': symbol,
                            'quantity': quantity,
                            'price': price,
                            'fee': trade['fee_amount'],
                            'total_cost': trade['net_value'],
                            'confidence': sig['confidence'],
                            'success': True
                        })
                        logger.info(f"买入执行: {symbol} x{quantity} @ {price:.4f}")
                    except Exception as e:
                        logger.error(f"买入失败 {symbol}: {e}")
                        results.append({
                            'action': 'buy',
                            'symbol': symbol,
                            'quantity': quantity,
                            'price': price,
                            'success': False,
                            'error': str(e)
                        })

        # 6. 处理卖出信号
        if sell_signals:
            for sig in sell_signals:
                symbol = sig['symbol']
                position = positions.get(symbol)
                if not position:
                    logger.warning(f"卖出信号 {symbol} 无持仓，跳过")
                    continue

                price = price_data.get(symbol)
                if not price:
                    logger.warning(f"卖出信号 {symbol} 无价格数据，跳过")
                    continue

                # 卖出持仓的 SELL_RATIO（默认 50%）
                quantity_to_sell = int(position['quantity'] * Config.SELL_RATIO)
                if quantity_to_sell <= 0:
                    logger.info(f"{symbol}: 持仓数量过少，无法卖出")
                    continue

                try:
                    trade = virtual_account.execute_trade(
                        symbol=symbol,
                        quantity=-quantity_to_sell,  # 负数表示卖出
                        price=price,
                        fee=Config.FEE_RATE
                    )
                    results.append({
                        'action': 'sell',
                        'symbol': symbol,
                        'quantity': quantity_to_sell,
                        'price': price,
                        'fee': trade['fee_amount'],
                        'net_proceeds': trade['net_value'],
                        'confidence': sig['confidence'],
                        'success': True
                    })
                    logger.info(f"卖出执行: {symbol} x{quantity_to_sell} @ {price:.4f}")
                except Exception as e:
                    logger.error(f"卖出失败 {symbol}: {e}")
                    results.append({
                        'action': 'sell',
                        'symbol': symbol,
                        'quantity': quantity_to_sell,
                        'price': price,
                        'success': False,
                        'error': str(e)
                    })

        # 7. 保存账户状态
        today = datetime.now().strftime('%Y-%m-%d')
        virtual_account.save_state(today)

        # 8. 账户健康检查（集成监控告警系统）
        try:
            # 动态添加项目根目录到路径以导入监控模块
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from scripts.monitoring.alert import check_account_health
            account_ok, warnings = check_account_health()
            if not account_ok:
                logger.warning(f"账户健康检查告警: {warnings}")
                # 这里可以添加额外的处理，例如记录到专门的告警日志
        except ImportError as e:
            logger.debug(f"监控模块不可用，跳过账户健康检查: {e}")
        except Exception as e:
            logger.error(f"账户健康检查异常: {e}", exc_info=True)

        # 9. 返回执行结果
        summary = {
            'total_signals': len(signals),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'executed': len([r for r in results if r['success']]),
            'failed': len([r for r in results if not r['success']])
        }

        return jsonify({
            'success': True,
            'message': '信号执行完成',
            'summary': summary,
            'details': results,
            'account': {
                'total_value': virtual_account.get_total_value(),
                'cash': virtual_account.get_balance()
            }
        })

    except Exception as e:
        logger.error(f"执行信号时发生错误: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================
# HTML 模板
# ============================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股ETF模拟交易监控看板</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
        }
        .header h1 {
            margin-bottom: 10px;
            font-size: 28px;
        }
        .last-updated {
            font-size: 14px;
            opacity: 0.9;
        }
        .section {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .section-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
            color: #667eea;
        }
        .account-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .summary-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        .summary-card.total {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .summary-card .label {
            font-size: 14px;
            opacity: 0.8;
            margin-bottom: 8px;
        }
        .summary-card .value {
            font-size: 24px;
            font-weight: 600;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        th {
            background-color: #f8f9fa;
            font-weight: 600;
            color: #667eea;
        }
        tr:hover {
            background-color: #f5f7fa;
        }
        .positive {
            color: #28a745;
            font-weight: 600;
        }
        .negative {
            color: #dc3545;
            font-weight: 600;
        }
        .signal-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid #667eea;
        }
        .signal-card.buy {
            border-left-color: #28a745;
        }
        .signal-card.sell {
            border-left-color: #dc3545;
        }
        .signal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .signal-symbol {
            font-size: 18px;
            font-weight: 600;
        }
        .signal-action {
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            color: white;
        }
        .signal-action.buy {
            background-color: #28a745;
        }
        .signal-action.sell {
            background-color: #dc3545;
        }
        .signal-details {
            font-size: 14px;
            color: #666;
        }
        .signal-conf {
            display: inline-block;
            margin-top: 8px;
            padding: 4px 8px;
            background: #e9ecef;
            border-radius: 4px;
            font-size: 12px;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .result-box {
            background: #e9ecef;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
            font-size: 14px;
        }
        .result-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .chart-container {
            position: relative;
            height: 400px;
            margin-top: 20px;
        }
        .no-data {
            text-align: center;
            color: #999;
            padding: 40px;
            font-size: 16px;
        }
        @media (max-width: 768px) {
            .account-summary {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>📈 A股ETF模拟交易监控看板</h1>
            <div class="last-updated">最后更新: {{ last_updated }}</div>
        </div>

        <!-- 账户概览 -->
        <div class="section">
            <h2 class="section-title">💰 账户概览</h2>
            <div class="account-summary">
                <div class="summary-card total">
                    <div class="label">总资产</div>
                    <div class="value">{{ total_value | format_currency }}</div>
                </div>
                <div class="summary-card">
                    <div class="label">可用现金</div>
                    <div class="value">{{ cash | format_currency }}</div>
                </div>
                <div class="summary-card">
                    <div class="label">持仓市值</div>
                    <div class="value">{{ positions_value | format_currency }}</div>
                </div>
            </div>
        </div>

        <!-- 资金曲线 -->
        <div class="section">
            <h2 class="section-title">📊 资金曲线</h2>
            {% if equity_curve %}
            <div class="chart-container">
                <canvas id="equityChart"></canvas>
            </div>
            <script>
                const ctx = document.getElementById('equityChart').getContext('2d');
                const labels = {{ equity_curve | curve_labels }};
                const data = {{ equity_curve | curve_data }};

                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: '总资产',
                                data: data.total,
                                borderColor: '#667eea',
                                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                                fill: true,
                                tension: 0.1
                            },
                            {
                                label: '现金',
                                data: data.cash,
                                borderColor: '#28a745',
                                backgroundColor: 'rgba(40, 167, 69, 0.1)',
                                fill: false,
                                tension: 0.1
                            },
                            {
                                label: '持仓市值',
                                data: data.positions,
                                borderColor: '#ffc107',
                                backgroundColor: 'rgba(255, 193, 7, 0.1)',
                                fill: false,
                                tension: 0.1
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'top'
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                display: true,
                                title: {
                                    display: true,
                                    text: '日期'
                                }
                            },
                            y: {
                                display: true,
                                title: {
                                    display: true,
                                    text: '金额 (¥)'
                                },
                                ticks: {
                                    callback: function(value) {
                                        return '¥' + value.toLocaleString();
                                    }
                                }
                            }
                        }
                    }
                });
            </script>
            {% else %}
            <div class="no-data">暂无历史数据，请先运行交易以生成状态文件</div>
            {% endif %}
        </div>

        <!-- 当前持仓 -->
        <div class="section">
            <h2 class="section-title">📋 当前持仓</h2>
            {% if positions %}
            <table>
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>数量</th>
                        <th>平均成本</th>
                        <th>当前价格</th>
                        <th>市值</th>
                        <th>盈亏%</th>
                    </tr>
                </thead>
                <tbody>
                    {% for pos in positions %}
                    <tr>
                        <td><strong>{{ pos.symbol }}</strong></td>
                        <td>{{ pos.quantity }}</td>
                        <td>{{ pos.avg_price | format_currency }}</td>
                        <td>{{ pos.current_price | format_currency }}</td>
                        <td>{{ pos.market_value | format_currency }}</td>
                        <td class="{{ 'positive' if pos.pnl_pct >= 0 else 'negative' }}">
                            {{ pos.pnl_pct | format_percent }}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="no-data">暂无持仓</div>
            {% endif %}
        </div>

        <!-- 今日信号 -->
        <div class="section">
            <h2 class="section-title">🔔 今日信号 ({{ signal_file }})</h2>
            {% if today_signals %}
                {% for sig in today_signals %}
                <div class="signal-card {{ sig.action }}">
                    <div class="signal-header">
                        <span class="signal-symbol">{{ sig.symbol }}</span>
                        <span class="signal-action {{ sig.action }}">{{ sig.action.upper() }}</span>
                    </div>
                    <div class="signal-details">
                        <div>置信度: <strong>{{ (sig.confidence * 100) | int }}%</strong></div>
                        <div>触发策略: {{ sig.reasons | join(', ') }}</div>
                        {% if sig.current_price %}
                        <div>当前价格: {{ sig.current_price | format_currency }}</div>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="no-data">今日无信号</div>
            {% endif %}
        </div>

        <!-- 执行控制 -->
        <div class="section">
            <h2 class="section-title">⚙️ 执行控制</h2>
            <p style="margin-bottom: 15px;">
                <strong>执行策略：</strong><br>
                - 买入：使用可用现金的 50% 分配给所有买入信号（按置信度加权）<br>
                - 卖出：卖出持仓的 50%（按每个卖出信号的持仓比例）<br>
                - 交易费率：0.05%
            </p>
            <button id="executeBtn" class="btn" onclick="executeSignals()">
                🚀 执行今日信号
            </button>

            <div id="executeResult" style="display: none;" class="result-box"></div>
        </div>
    </div>

    <script>
        async function executeSignals() {
            const btn = document.getElementById('executeBtn');
            const resultDiv = document.getElementById('executeResult');

            btn.disabled = true;
            btn.innerHTML = '⏳ 执行中...';
            resultDiv.style.display = 'none';

            try {
                const response = await fetch('/execute', { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    resultDiv.innerHTML = `
                        <h4 style="color: #28a745;">✅ 执行成功</h4>
                        <div class="result-item">
                            <span>信号总数:</span>
                            <span><strong>${result.summary.total_signals}</strong> (买入 ${result.summary.buy_signals}, 卖出 ${result.summary.sell_signals})</span>
                        </div>
                        <div class="result-item">
                            <span>成功执行:</span>
                            <span class="positive"><strong>${result.summary.executed}</strong></span>
                        </div>
                        <div class="result-item">
                            <span>执行失败:</span>
                            <span class="negative"><strong>${result.summary.failed}</strong></span>
                        </div>
                        <div class="result-item">
                            <span>账户总资产:</span>
                            <span><strong>¥${result.account.total_value.toFixed(2)}</strong></span>
                        </div>
                        <div class="result-item">
                            <span>可用现金:</span>
                            <span><strong>¥${result.account.cash.toFixed(2)}</strong></span>
                        </div>
                        <p style="margin-top: 10px; color: #666;">页面将在 5 秒后自动刷新...</p>
                    `;
                    setTimeout(() => location.reload(), 5000);
                } else {
                    resultDiv.innerHTML = `
                        <h4 style="color: #dc3545;">❌ 执行失败</h4>
                        <p>${result.message}</p>
                    `;
                }
            } catch (error) {
                resultDiv.innerHTML = `
                    <h4 style="color: #dc3545;">❌ 请求异常</h4>
                    <p>${error.message}</p>
                `;
            } finally {
                btn.disabled = false;
                btn.innerHTML = '🚀 执行今日信号';
                resultDiv.style.display = 'block';
            }
        }
    </script>
</body>
</html>
'''

# Jinja2 过滤器
@app.template_filter('format_currency')
def currency_format(value):
    return format_currency(value)

@app.template_filter('format_percent')
def percent_format(value):
    return format_percent(value)

@app.template_filter('curve_labels')
def curve_labels(curve):
    return [item['date'] for item in curve]

@app.template_filter('curve_data')
def curve_data(curve):
    return {
        'total': [item['total_value'] for item in curve],
        'cash': [item['cash'] for item in curve],
        'positions': [item['positions_value'] for item in curve]
    }


# ============================================
# 主程序入口
# ============================================

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("A股ETF模拟交易监控看板启动")
    logger.info(f"监听地址: {Config.HOST}:{Config.PORT}")
    logger.info(f"数据目录: {Config.DATA_DIR}")
    logger.info(f"信号目录: {Config.SIGNALS_DIR}")
    logger.info("=" * 60)

    try:
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=Config.DEBUG,
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("看板已停止")
    except Exception as e:
        logger.error(f"看板运行失败: {e}", exc_info=True)
