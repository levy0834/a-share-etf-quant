#!/usr/bin/env python3
"""
A股ETF回测引擎 - 独立版本
包含完整的交易成本模型：佣金、印花税、滑点
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum

# 添加项目根目录到路径
WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
if PROJECT_DIR not in os.sys.path:
    os.sys.path.insert(0, PROJECT_DIR)


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class Order:
    """订单"""
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float = 0.0
    timestamp: datetime = None


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    entry_date: str = None  # 开仓日期
    highest_price: float = 0.0  # 持仓期间最高价（用于移动止损）
    partial_sold: int = 0  # 已分档卖出次数（0=未卖, 1=卖过1/3, 2=再卖过1/2）

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        """未实现盈亏百分比"""
        return (self.current_price - self.avg_price) / self.avg_price if self.avg_price > 0 else 0


@dataclass
class Trade:
    """交易记录（包含成本明细）"""
    date: str
    code: str
    action: str  # 'buy' or 'sell'
    price: float  # 成交价格（不含滑点）
    quantity: int
    cash_value: float  # 实际现金流变化（已扣除所有成本）
    cost_breakdown: Dict[str, float] = field(default_factory=dict)  # 成本明细
    realized_pnl: float = 0.0  # 买入时为0，卖出时为盈亏
    exit_reason: str = 'strategy'  # 卖出原因：'strategy', 'trailing_stop', 'partial_tp1', 'partial_tp2'
    holding_days: int = 0  # 持仓天数（仅卖出时有效）


class Backtester:
    """
    回测引擎 - 支持交易成本模型 + 增强风险控制
    
    成本结构：
    - 佣金：0.03% (双向收取)
    - 印花税：0.05% (仅卖出)
    - 滑点：0.05% (买入+滑点，卖出-滑点)
    
    风险控制机制：
    - 移动止损：价格从持仓最高价回撤3%时触发全仓卖出
    - 分档止盈：
      * 收益率达 5%：卖出 1/3 持仓（保留 2/3）
      * 收益率达 10%：再卖出剩余 1/2（保留 1/3）
      * 剩余 1/3 继续用移动止损保护
    - 动态仓位管理：
      * 基础仓位 10%
      * 基于过去20笔交易胜率调整：仓位 = base + min(0.15, win_rate * 0.3)
      * 仓位上限 25%
    
    新增指标：
    - exit_reason：退出原因（'strategy'|'trailing_stop'|'partial_tp1'|'partial_tp2'）
    - holding_days：持仓天数（从买入到卖出的交易日数）
    - avg_holding_days：平均持仓天数
    - stop_loss_count：移动止损触发次数
    - partial_tp1_count / partial_tp2_count：分档止盈次数
    """
    
    # 成本参数
    COMMISSION_RATE = 0.0003    # 佣金 0.03%
    STAMP_TAX_RATE = 0.0005    # 印花税 0.05% (仅卖出)
    SLIPPAGE_RATE = 0.0005     # 滑点 0.05%
    
    def __init__(self, data: pd.DataFrame, initial_capital: float = 100000.0):
        """
        初始化回测引擎
        
        Args:
            data: DataFrame 必须包含 ['date', 'code', 'open', 'high', 'low', 'close', 'volume']
            initial_capital: 初始资金
        """
        self.data = data.copy().sort_values('date').reset_index(drop=True)
        self.initial_capital = initial_capital
        self.capital = initial_capital  # 现金
        self.position = 0  # 持股数
        self.position_cost = 0.0  # 持仓成本均价（不含交易成本）
        self.position_total_cost = 0.0  # 持仓总成本（含交易成本）
        
        # 交易记录
        self.trades: List[Trade] = []
        self.daily_values: List[Dict] = []
        
        # 风险控制参数
        self.base_position_pct = 0.10  # 基础仓位 10%
        self.position_pct = self.base_position_pct  # 动态仓位
        self.stop_loss_pct = 0.03  # 移动止损比例 3%
        self.take_profit_level1 = 0.05  # 第一档止盈 5%
        self.take_profit_level2 = 0.10  # 第二档止盈 10%
        self.recent_pnl: List[float] = []  # 记录最近交易盈亏（用于动态仓位）
        
        # 风险控制统计
        self.stop_loss_count = 0  # 移动止损触发次数
        self.partial_tp1_count = 0  # 第一档止盈次数
        self.partial_tp2_count = 0  # 第二档止盈次数
        self.holding_days_list: List[int] = []  # 每次持仓天数
        
        # 当前持仓对象（用于追踪）
        self.current_position: Optional[Position] = None
        
    def calculate_signals(self, strategy_func: Callable) -> pd.DataFrame:
        """根据策略函数生成信号"""
        signals = []
        for idx, row in self.data.iterrows():
            signal = strategy_func(row)
            signals.append(signal if signal else 'hold')
        self.data['signal'] = signals
        return self.data
    
    def _calculate_buy_cost(self, price: float, quantity: int) -> Tuple[float, Dict[str, float]]:
        """
        计算买入成本
        
        Returns:
            total_cost: 总成本（从现金扣除的金额）
            breakdown: 成本明细字典
        """
        # 计算各成本项
        trade_value = price * quantity
        commission = trade_value * self.COMMISSION_RATE
        stamp_tax = 0.0  # 买入无印花税
        # 滑点影响：实际成交价比原价高
        slippage_impact = trade_value * self.SLIPPAGE_RATE
        effective_price = price * (1 + self.SLIPPAGE_RATE)
        
        total_cost = trade_value + commission + slippage_impact
        
        breakdown = {
            'trade_value': trade_value,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'slippage': slippage_impact,
            'total_cost': total_cost
        }
        
        return total_cost, effective_price, breakdown
    
    def _calculate_sell_proceeds(self, price: float, quantity: int) -> Tuple[float, Dict[str, float]]:
        """
        计算卖出收入（净收入）
        
        Returns:
            net_proceeds: 净收入（加到现金的金额）
            breakdown: 成本明细字典
        """
        trade_value = price * quantity
        commission = trade_value * self.COMMISSION_RATE
        stamp_tax = trade_value * self.STAMP_TAX_RATE
        # 滑点影响：实际成交价比原价低
        slippage_impact = trade_value * self.SLIPPAGE_RATE
        effective_price = price * (1 - self.SLIPPAGE_RATE)
        
        net_proceeds = trade_value - commission - stamp_tax - slippage_impact
        
        breakdown = {
            'trade_value': trade_value,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'slippage': slippage_impact,
            'net_proceeds': net_proceeds
        }
        
        return net_proceeds, effective_price, breakdown
    
    def _update_position_cost(self, quantity: int, buy_price: float, total_cost: float):
        """更新持仓成本"""
        if self.position == 0:
            # 开仓
            self.position = quantity
            self.position_cost = buy_price
            self.position_total_cost = total_cost
        else:
            # 加仓：重新计算平均成本
            old_quantity = self.position
            old_total_cost = self.position_total_cost
            new_quantity = old_quantity + quantity
            new_total_cost = old_total_cost + total_cost
            self.position = new_quantity
            self.position_total_cost = new_total_cost
            self.position_cost = new_total_cost / new_quantity if new_quantity > 0 else 0
    
    def execute_trade(self, row, signal: str):
        """
        执行单笔交易（核心方法）- 增强风险控制版本
        
        交易成本计算：
        买入：总成本 = price * qty * (1 + 0.0003 + 0.0005)
        卖出：净收入 = price * qty * (1 + 0.0003 + 0.0005 + 0.0005)
        
        风险控制：
        - 移动止损：价格从最高价回撤3%触发
        - 分档止盈：5%卖1/3，10%再卖剩余1/2，剩余1/3用移动止损保护
        - 动态仓位：基于最近20笔交易胜率调整，基础10%，上限25%
        """
        price = row['close']
        high = row.get('high', price)  # 当日最高价（用于更新最高价）
        date = row['date']
        code = row.get('code', 'UNKNOWN')
        
        # === 动态仓位管理 ===
        # 计算胜率（过去20笔交易）
        if len(self.recent_pnl) >= 5:
            recent_trades = self.recent_pnl[-20:] if len(self.recent_pnl) >= 20 else self.recent_pnl
            win_count = sum(1 for p in recent_trades if p > 0)
            win_rate = win_count / len(recent_trades)
            # 仓位 = 基础 + min(0.15, win_rate * 0.3)
            self.position_pct = min(0.25, self.base_position_pct + min(0.15, win_rate * 0.3))
        else:
            self.position_pct = self.base_position_pct
        
        # === 更新持仓最高价（如果有持仓）===
        if self.current_position and self.current_position.quantity > 0:
            if high > self.current_position.highest_price:
                self.current_position.highest_price = high
            self.current_position.current_price = price
        
        # === 交易逻辑 ===
        current_date = pd.to_datetime(date) if isinstance(date, str) else date
        
        # 1. 检查是否需要卖出（止盈/止损）
        if self.current_position and self.current_position.quantity > 0:
            pos = self.current_position
            current_pnl_pct = pos.unrealized_pnl_pct
            exit_reason = None
            sell_quantity = 0
            
            # 分档止盈检查
            if pos.partial_sold == 0:  # 尚未分档卖出过
                if current_pnl_pct >= self.take_profit_level2:
                    # 达到10%：卖出剩余1/2（保留1/3）
                    sell_quantity = pos.quantity // 2
                    exit_reason = 'partial_tp2'
                    pos.partial_sold = 2
                elif current_pnl_pct >= self.take_profit_level1:
                    # 达到5%：卖出1/3（保留2/3）
                    sell_quantity = pos.quantity // 3
                    exit_reason = 'partial_tp1'
                    pos.partial_sold = 1
            elif pos.partial_sold == 1:  # 已触发TP1，现在检查TP2
                if current_pnl_pct >= self.take_profit_level2:
                    # 达到10%：卖出剩余1/2（保留1/3）
                    sell_quantity = pos.quantity // 2
                    exit_reason = 'partial_tp2'
                    pos.partial_sold = 2
            
            # 移动止损检查（对剩余持仓，或者如果已经触发分档卖出了）
            if not exit_reason and pos.quantity > 0:
                if pos.highest_price > 0:
                    trailing_stop_price = pos.highest_price * (1 - self.stop_loss_pct)
                    if price < trailing_stop_price:
                        # 触发移动止损：全仓卖出
                        sell_quantity = pos.quantity
                        exit_reason = 'trailing_stop'
            
            # 执行部分卖出或全仓卖出
            if exit_reason and sell_quantity > 0:
                net_proceeds, effective_price, cost_breakdown = self._calculate_sell_proceeds(price, sell_quantity)
                
                # 计算已实现盈亏（按本次卖出数量比例计算）
                avg_cost_per_share = pos.avg_price
                realized_pnl = (effective_price - avg_cost_per_share) * sell_quantity
                self.recent_pnl.append(realized_pnl)
                
                # 增加现金
                self.capital += net_proceeds
                
                # 计算持仓天数（从买入到当前）
                if pos.entry_date:
                    holding_days = (current_date - pos.entry_date).days
                else:
                    holding_days = 0
                
                # 记录交易
                trade = Trade(
                    date=date,
                    code=code,
                    action='sell',
                    price=price,  # 记录原始价格
                    quantity=sell_quantity,
                    cash_value=net_proceeds,
                    cost_breakdown=cost_breakdown,
                    realized_pnl=realized_pnl,
                    exit_reason=exit_reason,
                    holding_days=holding_days
                )
                self.trades.append(trade)
                
                # 更新持仓
                pos.quantity -= sell_quantity
                self.position = pos.quantity  # 同步更新简单位数
                # 更新持仓总成本（按比例减少）
                if pos.quantity > 0:
                    # 剩余持仓总成本 = 剩余数量 * 平均成本
                    self.position_total_cost = pos.quantity * pos.avg_price
                else:
                    self.position_total_cost = 0.0
                if pos.quantity == 0:
                    # 全部清仓，记录持仓天数
                    self.holding_days_list.append(holding_days)
                    # 重置持仓对象
                    self.current_position = None
                    self.position = 0
                    self.position_cost = 0.0
                    self.position_total_cost = 0.0
                
                # 统计止盈/止损次数
                if exit_reason == 'trailing_stop':
                    self.stop_loss_count += 1
                elif exit_reason == 'partial_tp1':
                    self.partial_tp1_count += 1
                elif exit_reason == 'partial_tp2':
                    self.partial_tp2_count += 1
        
        # 2. 策略信号卖出（非风险控制触发的普通全仓卖出）
        elif signal == 'sell' and self.current_position and self.current_position.quantity > 0:
            pos = self.current_position
            quantity = pos.quantity
            
            net_proceeds, effective_price, cost_breakdown = self._calculate_sell_proceeds(price, quantity)
            
            # 计算已实现盈亏
            avg_cost_per_share = pos.avg_price
            realized_pnl = (effective_price - avg_cost_per_share) * quantity
            self.recent_pnl.append(realized_pnl)
            
            # 增加现金
            self.capital += net_proceeds
            
            # 计算持仓天数
            if pos.entry_date:
                holding_days = (current_date - pos.entry_date).days
            else:
                holding_days = 0
            
            # 记录交易
            trade = Trade(
                date=date,
                code=code,
                action='sell',
                price=price,
                quantity=quantity,
                cash_value=net_proceeds,
                cost_breakdown=cost_breakdown,
                realized_pnl=realized_pnl,
                exit_reason='strategy',
                holding_days=holding_days
            )
            self.trades.append(trade)
            
            # 清空持仓
            self.holding_days_list.append(holding_days)
            self.current_position = None
            self.position = 0
            self.position_cost = 0.0
            self.position_total_cost = 0.0
        
        # 3. 检查是否买入（仅当无持仓且信号为buy时）
        if signal == 'buy' and (self.current_position is None or self.current_position.quantity == 0):
            # 计算购买数量：按资金比例
            invest_amount = self.capital * self.position_pct
            quantity = int(invest_amount / price)
            
            if quantity > 0:
                # 计算成本
                total_cost, effective_price, cost_breakdown = self._calculate_buy_cost(price, quantity)
                
                # 检查资金是否足够
                if total_cost <= self.capital:
                    # 扣除现金
                    self.capital -= total_cost
                    
                    # 创建持仓对象
                    pos = Position(
                        symbol=code,
                        quantity=quantity,
                        avg_price=effective_price,
                        current_price=price,
                        entry_date=current_date,
                        highest_price=high,
                        partial_sold=0
                    )
                    self.current_position = pos
                    self.position = quantity
                    self.position_cost = effective_price
                    self.position_total_cost = total_cost
                    
                    # 记录交易
                    trade = Trade(
                        date=date,
                        code=code,
                        action='buy',
                        price=price,
                        quantity=quantity,
                        cash_value=-total_cost,
                        cost_breakdown=cost_breakdown,
                        realized_pnl=0.0,
                        exit_reason='strategy',
                        holding_days=0
                    )
                    self.trades.append(trade)
    
    def _record_daily_value(self, row):
        """记录每日资产净值"""
        date = row['date']
        price = row['close']
        
        # 持仓市值（使用当前价格）
        position_value = self.position * price
        
        # 总资产 = 现金 + 持仓市值
        total_assets = self.capital + position_value
        
        daily_record = {
            'date': date,
            'capital': self.capital,
            'position': self.position,
            'position_cost': self.position_cost,
            'position_total_cost': self.position_total_cost,
            'position_value': position_value,
            'total_assets': total_assets,
            'signal': row.get('signal', 'hold')
        }
        self.daily_values.append(daily_record)
        
        return total_assets
    
    def run(self, data: Optional[pd.DataFrame] = None, strategy_func: Optional[Callable] = None):
        """
        运行回测
        
        Args:
            data: 数据DataFrame（如果为None则使用初始化时的数据）
            strategy_func: 策略函数，接收一行数据返回 'buy'/'sell'/'hold'
        """
        # 使用传入的数据或初始化时的数据
        if data is not None:
            self.data = data.copy().sort_values('date').reset_index(drop=True)
        
        # 生成信号
        if strategy_func is not None:
            self.calculate_signals(strategy_func)
        
        # 逐日执行
        for idx, row in self.data.iterrows():
            signal = row.get('signal', 'hold')
            self.execute_trade(row, signal)
            
            # 记录当日净值
            self._record_daily_value(row)
        
        # 最后一天强制平仓（如果有持仓）
        if self.position > 0:
            last_row = self.data.iloc[-1]
            self.execute_trade(last_row, 'sell')
            self._record_daily_value(last_row)
        
        # 生成结果DataFrame
        self.results_df = pd.DataFrame(self.daily_values)
        if 'date' in self.results_df.columns:
            self.results_df['date'] = pd.to_datetime(self.results_df['date'])
            self.results_df.set_index('date', inplace=True)
        
        return self.results_df
    
    def get_trades(self) -> pd.DataFrame:
        """获取交易记录DataFrame（包含成本明细）"""
        if not self.trades:
            return pd.DataFrame()
        
        trades_data = []
        for trade in self.trades:
            row = {
                'date': trade.date,
                'code': trade.code,
                'action': trade.action,
                'price': trade.price,
                'quantity': trade.quantity,
                'cash_value': trade.cash_value,
                'realized_pnl': trade.realized_pnl,
                'exit_reason': trade.exit_reason,
                'holding_days': trade.holding_days
            }
            # 添加成本明细
            for key, value in trade.cost_breakdown.items():
                row[f'cost_{key}'] = value
            trades_data.append(row)
        
        return pd.DataFrame(trades_data)
    
    def get_cost_summary(self) -> Dict[str, float]:
        """获取成本汇总"""
        if not self.trades:
            return {}
        
        total_commission = 0.0
        total_stamp_tax = 0.0
        total_slippage = 0.0
        
        for trade in self.trades:
            breakdown = trade.cost_breakdown
            total_commission += breakdown.get('commission', 0)
            total_stamp_tax += breakdown.get('stamp_tax', 0)
            total_slippage += breakdown.get('slippage', 0)
        
        return {
            'total_commission': total_commission,
            'total_stamp_tax': total_stamp_tax,
            'total_slippage': total_slippage,
            'total_cost': total_commission + total_stamp_tax + total_slippage
        }
    
    def evaluate(self) -> Dict:
        """评估回测结果 - 增强版"""
        if not self.daily_values:
            return {}
        
        df = self.results_df.copy()
        df['daily_return'] = df['total_assets'].pct_change().fillna(0)
        
        # 总收益率
        final_assets = df['total_assets'].iloc[-1]
        total_return = (final_assets - self.initial_capital) / self.initial_capital
        
        # 年化收益率
        years = (df.index[-1] - df.index[0]).days / 365.25
        annual_return = (1 + total_return) ** (1/years) - 1 if years > 0 else 0
        
        # 最大回撤
        df['cummax'] = df['total_assets'].cummax()
        df['drawdown'] = (df['total_assets'] - df['cummax']) / df['cummax']
        max_drawdown = df['drawdown'].min()
        
        # 夏普比率（假设无风险利率2%）
        risk_free_rate = 0.02
        excess_returns = df['daily_return'] - risk_free_rate/252
        if excess_returns.std() > 0:
            sharpe_ratio = excess_returns.mean() / excess_returns.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        # 交易统计
        trades_df = self.get_trades()
        total_trades = len(trades_df)
        
        # 胜率（按卖出盈亏计算）
        sell_trades = [t for t in self.trades if t.action == 'sell']
        winning_sells = sum(1 for t in sell_trades if t.realized_pnl > 0)
        total_sells = len(sell_trades)
        win_rate = winning_sells / total_sells if total_sells > 0 else 0
        
        # 成本汇总
        cost_summary = self.get_cost_summary()
        
        # === 新增风险控制指标 ===
        # 平均持仓天数
        avg_holding_days = np.mean(self.holding_days_list) if self.holding_days_list else 0
        
        # 风险控制统计
        risk_control_stats = {
            'avg_holding_days': round(avg_holding_days, 2),
            'stop_loss_count': self.stop_loss_count,
            'partial_tp1_count': self.partial_tp1_count,
            'partial_tp2_count': self.partial_tp2_count,
            'total_partial_tp': self.partial_tp1_count + self.partial_tp2_count,
            'dynamic_position_pct': round(self.position_pct * 100, 2)  # 最终使用的仓位比例
        }
        
        return {
            'total_return_pct': total_return * 100,
            'annual_return_pct': annual_return * 100,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe_ratio,
            'total_trades': total_trades,
            'win_rate_pct': win_rate * 100,
            'final_assets': final_assets,
            'start_date': df.index[0].strftime('%Y-%m-%d'),
            'end_date': df.index[-1].strftime('%Y-%m-%d'),
            **cost_summary,
            **risk_control_stats  # 添加风险控制指标
        }


# === 策略定义（从 explore_strategies.py 导入）===

def strategy_ma_cross(row) -> str:
    """均线金叉死叉策略（MA5 vs MA20）"""
    if pd.isna(row.get('ma5')) or pd.isna(row.get('ma20')):
        return 'hold'
    if row['ma5'] > row['ma20']:
        return 'buy'
    elif row['ma5'] < row['ma20']:
        return 'sell'
    return 'hold'

def strategy_ma_double(row) -> str:
    """双均线组合策略（MA10 vs MA60）"""
    if pd.isna(row.get('ma10')) or pd.isna(row.get('ma60')):
        return 'hold'
    if row['ma10'] > row['ma60']:
        return 'buy'
    elif row['ma10'] < row['ma60']:
        return 'sell'
    return 'hold'

def strategy_ma_triple(row) -> str:
    """三均线系统（MA20 > MA60 > MA120 多头）"""
    if pd.isna(row.get('ma20')) or pd.isna(row.get('ma60')) or pd.isna(row.get('ma120')):
        return 'hold'
    if row['ma20'] > row['ma60'] > row['ma120']:
        return 'buy'
    elif row['ma20'] < row['ma60'] < row['ma120']:
        return 'sell'
    return 'hold'

def strategy_macd_cross(row) -> str:
    """MACD金叉死叉"""
    if pd.isna(row.get('macd')) or pd.isna(row.get('macd_signal')):
        return 'hold'
    if row['macd'] > row['macd_signal']:
        return 'buy'
    elif row['macd'] < row['macd_signal']:
        return 'sell'
    return 'hold'

def strategy_rsi_extreme(row) -> str:
    """RSI超买超卖"""
    if pd.isna(row.get('rsi')):
        return 'hold'
    if row['rsi'] < 30:
        return 'buy'
    elif row['rsi'] > 70:
        return 'sell'
    return 'hold'

def strategy_ma_rsi_combo(row) -> str:
    """MA + RSI 组合（经典）"""
    if not pd.isna(row.get('ma20')) and not pd.isna(row.get('rsi')):
        if row['close'] > row['ma20'] and 30 < row['rsi'] < 50:
            return 'buy'
        elif row['rsi'] > 70:
            return 'sell'
    return 'hold'

def strategy_bollinger_band(row) -> str:
    """布林带突破"""
    if pd.isna(row.get('bb_upper')) or pd.isna(row.get('bb_lower')):
        return 'hold'
    if row['close'] < row['bb_lower']:
        return 'buy'
    elif row['close'] > row['bb_upper']:
        return 'sell'
    return 'hold'


# === 工具函数 ===

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算技术指标"""
    df = df.copy()
    # 移动平均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['ma120'] = df['close'].rolling(120).mean()
    df['ma250'] = df['close'].rolling(250).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 布林带
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * bb_std
    df['bb_lower'] = df['bb_middle'] - 2 * bb_std

    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # 成交量
    df['volume_ma20'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma20']
    
    return df


# === 主程序测试 ===

if __name__ == "__main__":
    # 简单测试
    print("=" * 60)
    print("🧪 Backtester 测试 - 交易成本模型验证")
    print("=" * 60)
    
    # 生成测试数据
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    np.random.seed(42)
    prices = 100 + np.random.randn(100).cumsum() * 0.5
    
    test_df = pd.DataFrame({
        'date': dates,
        'code': '510300',
        'open': prices * (1 + np.random.randn(100) * 0.01),
        'high': prices * 1.02,
        'low': prices * 0.98,
        'close': prices,
        'volume': np.random.randint(1000000, 5000000, 100)
    })
    
    # 计算指标
    test_df = calculate_indicators(test_df)
    
    # 运行回测
    print("\n📊 运行策略: MA Cross")
    bt = Backtester(test_df, initial_capital=100000)
    bt.run(test_df, strategy_ma_cross)
    
    # 输出结果
    metrics = bt.evaluate()
    
    # 集成：回测健康检查（检查 latest.log 是否有错误）
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from monitoring.alert import check_backtest_health
        backtest_ok, errors = check_backtest_health()
        if not backtest_ok:
            print("\n⚠️ 回测健康检查发现以下问题:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("\n✅ 回测健康检查通过")
    except ImportError as e:
        print(f"\n⚠️ 监控模块不可用，跳过回测健康检查: {e}")
    except Exception as e:
        print(f"\n⚠️ 回测健康检查异常: {e}")
    
    print("\n📈 绩效指标:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    
    # 查看交易记录
    trades_df = bt.get_trades()
    print(f"\n💰 交易记录 (共 {len(trades_df)} 笔):")
    if len(trades_df) > 0:
        print(trades_df.to_string())
    
    # 成本汇总
    cost_summary = bt.get_cost_summary()
    print("\n💸 成本汇总:")
    for key, value in cost_summary.items():
        print(f"  {key}: {value:.2f}")
    
    print("\n✅ 测试完成！")
