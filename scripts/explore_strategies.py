#!/usr/bin/env python3
"""
Step 2: 策略探索与回测（并行化版本）
基于10年数据，探索天级别交易策略
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Callable, Optional
import matplotlib.pyplot as plt
from dataclasses import dataclass
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import argparse
from functools import lru_cache
import hashlib
import pickle
from pathlib import Path

# 配置
WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
DAY_DIR = os.path.join(DATA_DIR, "day")  # 单个ETF日线数据目录
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 缓存目录
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(processName)s] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """单笔交易记录"""
    date: str
    code: str
    action: str  # 'buy' or 'sell'
    price: float
    quantity: int
    cash_value: float
    reason: str

class Backtester:
    """回测引擎（优化版）"""
    def __init__(self, data: pd.DataFrame, initial_capital=100000.0, use_cache: bool = True):
        """
        data: DataFrame 包含列 ['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'pct_change']
        假设数据已按date排序，且为单一ETF
        """
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.use_cache = use_cache
        # 缓存技术指标计算结果（如果传入的是已计算好的，则跳过）
        self._indicators_calculated = False
        
    def calculate_signals_vectorized(self, strategy_func: Callable) -> pd.DataFrame:
        """
        向量化生成信号（优化版）
        使用 apply 替代 iterrows，提升性能
        """
        # 使用 apply 替代 iterrows，速度更快
        self.data['signal'] = self.data.apply(strategy_func, axis=1)
        self.data['signal'] = self.data['signal'].fillna('hold')
        return self.data
    
    def run_vectorized(self, data: pd.DataFrame, strategy_func: Callable, 
                       from_date: Optional[str] = None) -> pd.DataFrame:
        """
        向量化执行回测（优化版）
        
        Args:
            data: 包含信号的数据
            strategy_func: 策略函数（签名：row -> signal）
            from_date: 起始日期（增量回测），格式 'YYYY-MM-DD'
            
        Returns:
            每日净值DataFrame
        """
        # 1. 准备数据
        df = data.copy()
        
        # 增量回测：如果指定了 from_date，只处理该日期之后的数据
        if from_date:
            from_dt = pd.to_datetime(from_date)
            # 需要保留 from_date 之前的数据用于指标计算（如moving averages）
            # 但只从 from_date 开始记录交易和净值
            mask = df['date'] >= from_dt
            execution_mask = mask
            logger.info(f"增量回测：从 {from_date} 开始，共 {mask.sum()} 个交易日")
        else:
            execution_mask = pd.Series([True] * len(df), index=df.index)
        
        # 2. 生成信号（向量化）
        df = self.calculate_signals_vectorized(strategy_func)
        
        # 3. 向量化执行交易逻辑（仍然需要状态，但优化循环）
        # 初始化结果数组
        n = len(df)
        capitals = np.zeros(n)
        positions = np.zeros(n, dtype=np.int64)
        position_costs = np.zeros(n)
        total_assets = np.zeros(n)
        signals = df['signal'].values
        prices = df['close'].values
        dates = df['date'].values
        
        # 常量
        COMMISSION = 0.0003
        STAMP_TAX = 0.0005
        SLIPPAGE = 0.0005
        
        # 动态状态变量
        capital = self.initial_capital
        position = 0
        position_cost = 0.0
        recent_pnl = []  # 用于计算胜率
        
        # 预处理：计算动态仓位的基础（基于近期胜率）- 需要逐步更新
        for i in range(n):
            price = prices[i]
            signal = signals[i]
            date = dates[i]
            
            # 只在执行期内更新状态和记录
            if execution_mask.iloc[i] if hasattr(execution_mask, 'iloc') else execution_mask[i]:
                # 计算当前仓位比例
                if len(recent_pnl) >= 5:
                    win_rate = sum(1 for p in recent_pnl[-20:] if p > 0) / min(20, len(recent_pnl))
                    position_pct = min(0.25, 0.10 + win_rate * 0.15)
                else:
                    position_pct = 0.10
                
                # 检查止损/止盈
                if position > 0:
                    current_pnl = (price - position_cost) / position_cost
                    if current_pnl <= -0.03:
                        signal = 'sell'
                    elif current_pnl >= 0.08:
                        signal = 'sell'
                
                # 执行买入
                if signal == 'buy' and position == 0:
                    invest_amount = capital * position_pct
                    quantity = int(invest_amount / price)
                    if quantity > 0:
                        cost_per_share = price * (1 + COMMISSION + STAMP_TAX)
                        total_cost = quantity * cost_per_share
                        capital -= total_cost
                        position = quantity
                        position_cost = price
                        
                # 执行卖出
                elif signal == 'sell' and position > 0:
                    net_per_share = price * (1 - COMMISSION - STAMP_TAX - SLIPPAGE)
                    net_cash = position * net_per_share
                    capital += net_cash
                    
                    # 记录盈亏
                    trade_pnl = (price - position_cost) / position_cost - (COMMISSION + STAMP_TAX + SLIPPAGE)
                    recent_pnl.append(trade_pnl)
                    
                    position = 0
                    position_cost = 0.0
            
            # 记录每日状态
            capitals[i] = capital
            positions[i] = position
            position_costs[i] = position_cost
            total_assets[i] = capital + position * price
        
        # 4. 构建结果DataFrame
        results_df = pd.DataFrame({
            'date': dates,
            'capital': capitals,
            'position': positions,
            'position_cost': position_costs,
            'total_assets': total_assets,
            'signal': signals,
            'close': prices
        })
        
        self.results_df = results_df
        return results_df
    
    def execute_sequential(self, data: pd.DataFrame, strategy_func: Callable):
        """
        顺序执行回测（原版，保持兼容）
        仅用于验证或小数据集
        """
        self.data = data.copy()
        self.data = self.calculate_signals_vectorized(strategy_func)
        
        for idx, row in self.data.iterrows():
            self._execute_row(row)
        
        self.results_df = pd.DataFrame(self.daily_values)
        return self.results_df
    
    def _execute_row(self, row):
        """执行单行交易逻辑（原版，用于顺序执行）"""
        price = row['close']
        date = row['date']
        signal = row['signal']
        
        COMMISSION = 0.0003
        STAMP_TAX = 0.0005
        SLIPPAGE = 0.0005
        
        # 动态仓位
        if len(self.recent_pnl) >= 5:
            win_rate = sum(1 for p in self.recent_pnl[-20:] if p > 0) / min(20, len(self.recent_pnl))
            self.position_pct = min(0.25, self.base_position_pct + win_rate * 0.15)
        else:
            self.position_pct = self.base_position_pct
        
        # 检查止损/止盈
        if self.position > 0:
            current_pnl = (price - self.position_cost) / self.position_cost
            if current_pnl <= self.stop_loss:
                signal = 'sell'
            elif current_pnl >= self.take_profit:
                signal = 'sell'
        
        # 执行
        if signal == 'buy' and self.position == 0:
            invest_amount = self.capital * self.position_pct
            quantity = int(invest_amount / price)
            if quantity > 0:
                cost_per_share = price * (1 + COMMISSION + STAMP_TAX)
                total_cost = quantity * cost_per_share
                self.capital -= total_cost
                self.position = quantity
                self.position_cost = price
                self.trades.append(Trade(date=date, code=row.get('code', 'UNKNOWN'),
                                        action='buy', price=price, quantity=quantity,
                                        cash_value=quantity * price, reason='strategy'))
        elif signal == 'sell' and self.position > 0:
            net_per_share = price * (1 - COMMISSION - STAMP_TAX - SLIPPAGE)
            net_cash = self.position * net_per_share
            self.capital += net_cash
            trade_pnl = (price - self.position_cost) / self.position_cost - (COMMISSION + STAMP_TAX + SLIPPAGE)
            self.recent_pnl.append(trade_pnl)
            self.trades.append(Trade(date=date, code=row.get('code', 'UNKNOWN'),
                                    action='sell', price=price, quantity=self.position,
                                    cash_value=net_cash, reason=row.get('reason', 'strategy')))
            self.position = 0
            self.position_cost = 0.0
        
        # 记录净值
        position_value = self.position * price
        total_assets = self.capital + position_value
        self.daily_values.append({
            'date': date, 'capital': self.capital, 'position': self.position,
            'position_value': position_value, 'total_assets': total_assets,
            'signal': signal
        })
    
    def run(self, data: pd.DataFrame, strategy_func: Callable, from_date: Optional[str] = None) -> pd.DataFrame:
        """
        运行回测（优化入口）
        
        Args:
            data: 原始数据（不含技术指标）
            strategy_func: 策略函数
            from_date: 增量回测起始日期
            
        Returns:
            每日净值DataFrame
        """
        # 使用优化版本
        return self.run_vectorized(data, strategy_func, from_date)
    
    def evaluate(self) -> Dict:
        """评估回测结果"""
        if not self.daily_values:
            return {}
        
        df = self.results_df.copy()
        df['daily_return'] = df['total_assets'].pct_change().fillna(0)
        
        total_return = (df['total_assets'].iloc[-1] - self.initial_capital) / self.initial_capital
        years = (df['date'].iloc[-1] - df['date'].iloc[0]).days / 365.25
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
        
        # 胜率
        winning_trades = 0
        total_trades = 0
        for i in range(1, len(self.trades), 2):  # 假设买卖成对
            if i < len(self.trades):
                buy = self.trades[i-1]
                sell = self.trades[i]
                if buy.action == 'buy' and sell.action == 'sell':
                    total_trades += 1
                    if sell.price > buy.price:
                        winning_trades += 1
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        return {
            'total_return': total_return * 100,
            'annual_return': annual_return * 100,
            'max_drawdown': max_drawdown * 100,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate * 100,
            'total_trades': total_trades,
            'final_assets': df['total_assets'].iloc[-1],
            'start_date': df['date'].iloc[0],
            'end_date': df['date'].iloc[-1]
        }

# === 缓存工具函数 ===

def get_data_hash(df: pd.DataFrame) -> str:
    """生成数据的唯一哈希值用于缓存键"""
    # 使用数据长度、开始日期、结束日期作为缓存键
    if len(df) == 0:
        return "empty"
    start_date = str(df['date'].iloc[0])
    end_date = str(df['date'].iloc[-1])
    key_str = f"{len(df)}_{start_date}_{end_date}"
    return hashlib.md5(key_str.encode()).hexdigest()[:16]

def get_cache_path(ticker: str, data_hash: str) -> Path:
    """获取缓存文件路径"""
    return Path(CACHE_DIR) / f"{ticker}_{data_hash}_indicators.pkl"

def load_cached_indicators(ticker: str, df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """从缓存加载技术指标"""
    cache_path = get_cache_path(ticker, get_data_hash(df))
    if cache_path.exists():
        try:
            with open(cache_path, 'rb') as f:
                cached_df = pickle.load(f)
            logger.debug(f"✅ 从缓存加载指标: {ticker}")
            return cached_df
        except Exception as e:
            logger.warning(f"⚠️  缓存加载失败 {ticker}: {e}")
    return None

def save_cached_indicators(ticker: str, df: pd.DataFrame, indicators_df: pd.DataFrame):
    """保存技术指标到缓存"""
    cache_path = get_cache_path(ticker, get_data_hash(df))
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump(indicators_df, f)
        logger.debug(f"💾 保存指标缓存: {ticker}")
    except Exception as e:
        logger.warning(f"⚠️  缓存保存失败 {ticker}: {e}")

# === 优化后的技术指标计算（向量化）===

def calculate_indicators_vectorized(df: pd.DataFrame) -> pd.DataFrame:
    """
    向量化计算技术指标（优化版本）
    使用 pandas 内置的 rolling/ewm 方法，避免Python循环
    """
    df = df.copy()
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # 移动平均线 - 向量化
    df['ma5'] = close.rolling(5).mean()
    df['ma10'] = close.rolling(10).mean()
    df['ma20'] = close.rolling(20).mean()
    df['ma60'] = close.rolling(60).mean()
    df['ma120'] = close.rolling(120).mean()
    df['ma250'] = close.rolling(250).mean()

    # RSI - 向量化实现
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 布林带 - 向量化
    df['bb_middle'] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * bb_std
    df['bb_lower'] = df['bb_middle'] - 2 * bb_std
    df['bb_bandwidth'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']

    # MACD - 向量化
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # 成交量变化 - 向量化
    df['volume_ma5'] = volume.rolling(5).mean()
    df['volume_ma20'] = volume.rolling(20).mean()
    df['volume_ratio'] = volume / df['volume_ma20']
    
    # ATR - 向量化（使用shift避免循环）
    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = true_range.rolling(14).mean()
    df['atr_ratio'] = df['atr'] / close

    # KDJ - 向量化（使用rolling min/max）
    low_min = low.rolling(9, min_periods=1).min()
    high_max = high.rolling(9, min_periods=1).max()
    rsv = (close - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    df['k'] = rsv.ewm(com=2).mean()
    df['d'] = df['k'].ewm(com=2).mean()
    df['j'] = 3 * df['k'] - 2 * df['d']

    # OBV - 向量化（使用cumsum和where）
    close_diff = close.diff()
    volume_direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    df['obv'] = (volume * volume_direction).cumsum()
    df['obv_ma20'] = df['obv'].rolling(20).mean()

    # AD指标 - 向量化
    clv = ((close - low) - (high - close)) / (high - low)
    clv = clv.fillna(0)
    df['ad'] = (clv * volume).cumsum()
    
    return df

def calculate_indicators(df: pd.DataFrame, use_cache: bool = True, ticker: str = 'UNKNOWN') -> pd.DataFrame:
    """
    计算技术指标（带缓存支持）
    
    Args:
        df: 原始数据
        use_cache: 是否使用缓存
        ticker: ETF代码，用于缓存键
        
    Returns:
        包含所有技术指标的DataFrame
    """
    if use_cache and ticker != 'UNKNOWN':
        cached = load_cached_indicators(ticker, df)
        if cached is not None:
            return cached
    
    # 计算指标
    result = calculate_indicators_vectorized(df)
    
    # 保存到缓存
    if use_cache and ticker != 'UNKNOWN':
        save_cached_indicators(ticker, df, result)
    
    return result

# === 策略定义 ===

def strategy_ma_cross(row) -> str:
    """均线金叉死叉策略（MA5 vs MA20）"""
    if pd.isna(row['ma5']) or pd.isna(row['ma20']):
        return 'hold'
    if row['ma5'] > row['ma20']:
        return 'buy'
    elif row['ma5'] < row['ma20']:
        return 'sell'
    return 'hold'

def strategy_ma_double(row) -> str:
    """双均线组合策略（MA10 vs MA60）"""
    if pd.isna(row['ma10']) or pd.isna(row['ma60']):
        return 'hold'
    if row['ma10'] > row['ma60']:
        return 'buy'
    elif row['ma10'] < row['ma60']:
        return 'sell'
    return 'hold'

def strategy_ma_triple(row) -> str:
    """三均线系统（MA20 > MA60 > MA120 多头）"""
    if pd.isna(row['ma20']) or pd.isna(row['ma60']) or pd.isna(row['ma120']):
        return 'hold'
    # 多头排列：短 > 中 > 长
    if row['ma20'] > row['ma60'] > row['ma120']:
        return 'buy'
    # 空头排列：短 < 中 < 长
    elif row['ma20'] < row['ma60'] < row['ma120']:
        return 'sell'
    return 'hold'

def strategy_macd_cross(row) -> str:
    """MACD金叉死叉"""
    if pd.isna(row['macd']) or pd.isna(row['macd_signal']):
        return 'hold'
    if row['macd'] > row['macd_signal']:
        return 'buy'
    elif row['macd'] < row['macd_signal']:
        return 'sell'
    return 'hold'

def strategy_macd_hist(row) -> str:
    """MACD柱状图加速策略（ histogram 扩大）"""
    if pd.isna(row['macd_hist']) or pd.isna(row['macd']):
        return 'hold'
    # 柱状图由负变正，且MACD上穿信号
    if row['macd'] > row['macd_signal'] and row['macd_hist'] > 0:
        return 'buy'
    elif row['macd'] < row['macd_signal'] and row['macd_hist'] < 0:
        return 'sell'
    return 'hold'

def strategy_rsi_extreme(row) -> str:
    """RSI超买超卖"""
    if pd.isna(row['rsi']):
        return 'hold'
    if row['rsi'] < 30:
        return 'buy'
    elif row['rsi'] > 70:
        return 'sell'
    return 'hold'

def strategy_rsi_divergence(row) -> str:
    """RSI背离策略（需要前一日数据，这里简化为连续两日背离检测）"""
    # 注意：需要访问前一行数据，实际应在Backtester中实现
    # 这里用简化版：RSI超卖 + 价格新低 或 RSI超买 + 价格新高
    # 需外部传入prev_row，此处仅占位
    return 'hold'

def strategy_bollinger_band(row) -> str:
    """布林带突破"""
    if pd.isna(row['bb_upper']) or pd.isna(row['bb_lower']):
        return 'hold'
    if row['close'] < row['bb_lower']:
        return 'buy'
    elif row['close'] > row['bb_upper']:
        return 'sell'
    return 'hold'

def strategy_bollinger_squeeze(row) -> str:
    """布林带带宽收缩后突破"""
    if pd.isna(row['bb_bandwidth']) or pd.isna(row['bb_upper']):
        return 'hold'
    # 带宽处于近期低点（收缩），且价格突破上轨或下轨
    # 这里简化：带宽小于5%均值视为收缩
    bandwidth_ratio = row['bb_bandwidth']
    # 需要历史均值，暂用固定阈值
    if bandwidth_ratio < 0.03:  # 3%宽度
        if row['close'] > row['bb_upper']:
            return 'buy'
        elif row['close'] < row['bb_lower']:
            return 'sell'
    return 'hold'

def strategy_volume_confirmation(row) -> str:
    """成交量确认策略：价格突破均线 + 成交量放大"""
    if pd.isna(row['ma20']) or pd.isna(row['volume_ratio']):
        return 'hold'
    # 价格突破MA20且成交量放大
    if row['close'] > row['ma20'] and row['volume_ratio'] > 1.5:
        return 'buy'
    elif row['close'] < row['ma20'] and row['volume_ratio'] > 1.5:
        return 'sell'
    return 'hold'

def strategy_ta_confluence(row) -> str:
    """TAV框架：趋势+动量+成交量（原版）"""
    trend_up = (row['close'] > row['ma20']) and (row['ma5'] > row['ma20']) if not pd.isna(row['ma20']) else False
    momentum_good = (30 < row['rsi'] < 70) and (row['macd'] > row['macd_signal']) if not pd.isna(row['rsi']) else False
    volume_spike = row.get('volume_ratio', 1) > 1.5
    if trend_up and momentum_good and volume_spike:
        return 'buy'
    if not trend_up and row.get('signal', '') == 'sell':
        return 'sell'
    return 'hold'

def strategy_ta_strengthened(row) -> str:
    """强化版TAV：多周期均线 + RSI健康 + MACD + 成交量"""
    # 趋势：MA5>MA10>MA60 多头排列
    trend_ok = (row['ma5'] > row['ma10'] > row['ma60']) if not pd.isna(row['ma5']) else False
    # 动量：RSI 40-60 健康上升区间，且MACD金叉
    momentum_ok = (40 < row['rsi'] < 60) and (row['macd'] > row['macd_signal']) if not pd.isna(row['rsi']) else False
    # 成交量：放大1.2倍以上
    volume_ok = row.get('volume_ratio', 1) > 1.2
    # 买入条件
    if trend_ok and momentum_ok and volume_ok:
        return 'buy'
    # 卖出条件：MA20下穿MA60 或 RSI>70 或 MACD死叉
    if (row['ma20'] < row['ma60']) or (row['rsi'] > 70) or (row['macd'] < row['macd_signal']):
        return 'sell'
    return 'hold'

def strategy_atr_trailing(row) -> str:
    """ATR动态止损策略（仅卖出信号）"""
    # 这个策略主要影响卖出，买入使用其他信号
    # 返回 'hold' 保持原策略
    return 'hold'

def strategy_momentum_rotation(row) -> str:
    """动量轮动策略（需多ETF比较，单标的不适用）"""
    # 在多ETF场景中，选择近期涨幅最大的
    return 'hold'

def strategy_ma_rsi_combo(row) -> str:
    """MA + RSI 组合（经典）"""
    if not pd.isna(row['ma20']) and not pd.isna(row['rsi']):
        if row['close'] > row['ma20'] and 30 < row['rsi'] < 50:
            return 'buy'
        elif row['rsi'] > 70:
            return 'sell'
    return 'hold'

def strategy_kdj_cross(row) -> str:
    """KDJ 随机指标金叉死叉"""
    if pd.isna(row['k']) or pd.isna(row['d']):
        return 'hold'
    # 需要访问前值判断交叉，这里简化
    if row['k'] > row['d']:
        return 'buy'
    elif row['k'] < row['d']:
        return 'sell'
    return 'hold'

def strategy_obv_divergence(row) -> str:
    """OBV 能量潮背离（简化）"""
    if pd.isna(row['obv']) or pd.isna(row['obv_ma20']):
        return 'hold'
    # 价格创新高但OBV未创新高 → 卖出信号
    # 这里简化：OBV 低于其20日均线且价格在MA20上方 → 背离预警
    if row['close'] > row['ma20'] and row['obv'] < row['obv_ma20']:
        return 'sell'  # 潜在顶背离
    if row['close'] < row['ma20'] and row['obv'] > row['obv_ma20']:
        return 'buy'   # 潜在底背离
    return 'hold'

def strategy_ad_trend(row) -> str:
    """AD 累积/分配指标趋势跟踪"""
    if pd.isna(row.get('ad')):
        return 'hold'
    # AD 上升趋势（需与前期比较，这里用简单对比）
    # 假设有 prev_ad 在 row 中，实际需在 Backtester 记录
    # 简化：AD 值大于0且价格突破上轨
    if row['ad'] > 0 and row['close'] > row['bb_upper']:
        return 'buy'
    elif row['ad'] < 0 and row['close'] < row['bb_lower']:
        return 'sell'
    return 'hold'

def strategy_atr_channel(row) -> str:
    """ATR 通道策略：突破布林带式 ATR 通道"""
    if pd.isna(row['atr']) or pd.isna(row['ma20']):
        return 'hold'
    # 通道：MA20 ± 2*ATR
    upper = row['ma20'] + 2 * row['atr']
    lower = row['ma20'] - 2 * row['atr']
    if row['close'] > upper:
        return 'buy'
    elif row['close'] < lower:
        return 'sell'
    return 'hold'

# === 并行化核心函数 ===

def _process_single_ticker(ticker: str, train_end_date: str, test_start_date: str, 
                           initial_capital: float = 100000.0) -> Tuple[str, pd.DataFrame, pd.DataFrame]:
    """
    处理单个ETF的回测（在子进程中执行）
    
    Args:
        ticker: ETF代码
        train_end_date: 训练集结束日期
        test_start_date: 测试集开始日期
        initial_capital: 初始资金
        
    Returns:
        ticker: ETF代码
        train_results_df: 训练集策略汇总结果
        test_results_df: 测试集策略汇总结果
    """
    logger = logging.getLogger(f"worker-{ticker}")
    logger.info(f"开始处理ETF: {ticker}")
    
    try:
        # 1. 加载单个ETF数据
        file_path = os.path.join(DAY_DIR, f"{ticker}.csv")
        if not os.path.exists(file_path):
            logger.warning(f"数据文件不存在，跳过ETF: {ticker}")
            return ticker, None, None
        
        df = pd.read_csv(file_path)
        if len(df) == 0:
            logger.warning(f"数据为空，跳过ETF: {ticker}")
            return ticker, None, None
        
        # 2. 计算技术指标
        df = calculate_indicators(df, ticker=ticker, use_cache=True)
        
        # 3. 划分训练集和测试集
        df['date'] = pd.to_datetime(df['date'])
        train_df = df[df['date'] <= train_end_date].copy()
        test_df = df[df['date'] >= test_start_date].copy()
        
        if len(train_df) == 0 or len(test_df) == 0:
            logger.warning(f"训练集或测试集为空，跳过ETF: {ticker}")
            return ticker, None, None
        
        # 4. 运行所有策略
        strategies = {
            'MA Cross': strategy_ma_cross,
            'MA Double': strategy_ma_double,
            'MA Triple': strategy_ma_triple,
            'MACD Cross': strategy_macd_cross,
            'MACD Hist': strategy_macd_hist,
            'RSI Extreme': strategy_rsi_extreme,
            'MA+RSI Combo': strategy_ma_rsi_combo,
            'Bollinger Band': strategy_bollinger_band,
            'Bollinger Squeeze': strategy_bollinger_squeeze,
            'Volume Confirm': strategy_volume_confirmation,
            'TA Confluence': strategy_ta_confluence,
            'TA Strengthened': strategy_ta_strengthened
        }
        
        # 训练集回测
        train_results = []
        for name, func in strategies.items():
            try:
                bt = Backtester(train_df, initial_capital)
                bt.run(train_df, func)
                metrics = bt.evaluate()
                metrics['strategy'] = name
                metrics['ticker'] = ticker
                metrics['dataset'] = 'train'
                train_results.append(metrics)
            except Exception as e:
                logger.error(f"ETF {ticker} 策略 {name} 训练集回测失败: {str(e)}")
        
        # 测试集回测
        test_results = []
        for name, func in strategies.items():
            try:
                bt = Backtester(test_df, initial_capital)
                bt.run(test_df, func)
                metrics = bt.evaluate()
                metrics['strategy'] = name
                metrics['ticker'] = ticker
                metrics['dataset'] = 'test'
                test_results.append(metrics)
            except Exception as e:
                logger.error(f"ETF {ticker} 策略 {name} 测试集回测失败: {str(e)}")
        
        train_results_df = pd.DataFrame(train_results) if train_results else None
        test_results_df = pd.DataFrame(test_results) if test_results else None
        
        logger.info(f"✅ ETF {ticker} 处理完成 - 训练集: {len(train_results)} 策略, 测试集: {len(test_results)} 策略")
        return ticker, train_results_df, test_results_df
        
    except Exception as e:
        logger.error(f"❌ ETF {ticker} 处理失败: {str(e)}")
        return ticker, None, None


def run_all_strategies(tickers: Optional[List[str]] = None, 
                       initial_capital: float = 100000.0,
                       train_end_date: str = '2021-12-31',
                       test_start_date: str = '2022-01-01',
                       parallel: bool = False,
                       max_workers: int = 4,
                       output_dir: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    并行/串行运行所有ETF和所有策略
    
    Args:
        tickers: ETF代码列表。如果为None，则从数据目录自动发现
        initial_capital: 初始资金
        train_end_date: 训练集结束日期
        test_start_date: 测试集开始日期
        parallel: 是否启用并行处理
        max_workers: 并行进程数
        output_dir: 输出目录（默认使用RESULTS_DIR）
        
    Returns:
        all_train_results: 合并后的训练集结果
        all_test_results: 合并后的测试集结果
        
    兼容性：
        如果 tickers 参数为一个DataFrame对象（老接口），则保持原有单文件模式
    """
    # 兼容老接口：如果传入的是DataFrame，视为单一ETF的数据
    if isinstance(tickers, pd.DataFrame):
        logger.info("检测到老接口调用（DataFrame参数），使用单文件模式")
        df = tickers
        # 确保有code列
        if 'code' not in df.columns:
            logger.warning("DataFrame中没有code列，使用默认ticker")
            ticker = 'UNKNOWN'
        else:
            ticker = df['code'].iloc[0] if len(df) > 0 else 'UNKNOWN'
        
        df = calculate_indicators(df, ticker=ticker, use_cache=True)
        return _run_all_strategies_single(df, ticker, initial_capital, 
                                          train_end_date, test_start_date)
    
    # 新接口：tickers列表模式
    if tickers is None:
        # 自动发现所有可用的ETF数据文件
        logger.info(f"从目录自动扫描ETF数据: {DAY_DIR}")
        ticker_files = [f for f in os.listdir(DAY_DIR) if f.endswith('.csv')]
        tickers = [f.replace('.csv', '') for f in ticker_files]
        logger.info(f"发现 {len(tickers)} 只ETF: {tickers[:10]}...")
    
    if output_dir is None:
        output_dir = RESULTS_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"启动{'并行' if parallel else '串行'}回测，共 {len(tickers)} 只ETF")
    logger.info(f"训练集截止: {train_end_date}, 测试集开始: {test_start_date}")
    
    all_train_results = []
    all_test_results = []
    
    if parallel:
        # 并行处理
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_ticker = {
                executor.submit(_process_single_ticker, ticker, train_end_date, test_start_date, initial_capital): ticker
                for ticker in tickers
            }
            
            # 使用tqdm显示进度
            with tqdm(total=len(tickers), desc="📊 ETF回测进度", unit="ETF") as pbar:
                for future in as_completed(future_to_ticker):
                    ticker = future_to_ticker[future]
                    try:
                        ticker, train_df, test_df = future.result()
                        if train_df is not None:
                            all_train_results.append(train_df)
                        if test_df is not None:
                            all_test_results.append(test_df)
                        pbar.set_postfix_str(f"完成: {ticker}")
                    except Exception as e:
                        logger.error(f"ETF {ticker} 处理异常: {str(e)}")
                        pbar.set_postfix_str(f"失败: {ticker}")
                    finally:
                        pbar.update(1)
    else:
        # 串行处理（单进程）
        for ticker in tqdm(tickers, desc="📊 ETF回测进度", unit="ETF"):
            try:
                ticker, train_df, test_df = _process_single_ticker(
                    ticker, train_end_date, test_start_date, initial_capital
                )
                if train_df is not None:
                    all_train_results.append(train_df)
                if test_df is not None:
                    all_test_results.append(test_df)
            except Exception as e:
                logger.error(f"ETF {ticker} 处理异常: {str(e)}")
    
    # 合并所有结果
    if all_train_results:
        combined_train = pd.concat(all_train_results, ignore_index=True)
        train_file = os.path.join(output_dir, "train_results.csv")
        combined_train.to_csv(train_file, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 训练集结果已保存: {train_file} ({len(combined_train)} 条记录)")
    else:
        logger.warning("⚠️  没有训练集结果可保存")
        combined_train = pd.DataFrame()
    
    if all_test_results:
        combined_test = pd.concat(all_test_results, ignore_index=True)
        test_file = os.path.join(output_dir, "test_results.csv")
        combined_test.to_csv(test_file, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 测试集结果已保存: {test_file} ({len(combined_test)} 条记录)")
    else:
        logger.warning("⚠️  没有测试集结果可保存")
        combined_test = pd.DataFrame()
    
    return combined_train, combined_test


def _run_all_strategies_single(df: pd.DataFrame, ticker: str, 
                               initial_capital: float = 100000.0,
                               train_end_date: str = '2021-12-31',
                               test_start_date: str = '2022-01-01') -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    单DataFrame模式（老接口兼容）运行所有策略
    
    Args:
        df: 数据DataFrame
        ticker: ETF代码
        initial_capital: 初始资金
        train_end_date: 训练集结束日期
        test_start_date: 测试集开始日期
        
    Returns:
        train_results_df: 训练集策略汇总
        test_results_df: 测试集策略汇总
    """
    print(f"\n🎯 单ETF回测模式: {ticker}")
    print(f"   数据条数: {len(df)}")
    
    # 计算技术指标
    print("⚙️  计算技术指标...")
    df = calculate_indicators(df, ticker=ticker, use_cache=True)
    
    # 划分训练集和测试集
    print("✂️  划分训练集/测试集...")
    df['date'] = pd.to_datetime(df['date'])
    train_df = df[df['date'] <= train_end_date].copy()
    test_df = df[df['date'] >= test_start_date].copy()
    print(f"📚 训练集: {len(train_df)} 天 ({train_df['date'].iloc[0].date()} ~ {train_df['date'].iloc[-1].date()})")
    print(f"🔬 测试集: {len(test_df)} 天 ({test_df['date'].iloc[0].date()} ~ {test_df['date'].iloc[-1].date()})")
    
    # 运行策略（调用原有逻辑）
    train_results, train_equity = _run_strategies_on_dataset(train_df, ticker, initial_capital, 'train')
    test_results, test_equity = _run_strategies_on_dataset(test_df, ticker, initial_capital, 'test')
    
    # 保存结果
    train_file = os.path.join(RESULTS_DIR, "train_results.csv")
    test_file = os.path.join(RESULTS_DIR, "test_results.csv")
    
    train_results.to_csv(train_file, index=False, encoding='utf-8-sig') if len(train_results) > 0 else None
    test_results.to_csv(test_file, index=False, encoding='utf-8-sig') if len(test_results) > 0 else None
    
    if len(train_results) > 0:
        print(f"✅ 训练集结果已保存: {train_file}")
    if len(test_results) > 0:
        print(f"✅ 测试集结果已保存: {test_file}")
    
    return train_results, test_results


def _run_strategies_on_dataset(df: pd.DataFrame, ticker: str, 
                               initial_capital: float, dataset_name: str) -> Tuple[pd.DataFrame, Dict]:
    """在单个数据集上运行所有策略（ helper 函数）"""
    strategies = {
        'MA Cross': strategy_ma_cross,
        'MA Double': strategy_ma_double,
        'MA Triple': strategy_ma_triple,
        'MACD Cross': strategy_macd_cross,
        'MACD Hist': strategy_macd_hist,
        'RSI Extreme': strategy_rsi_extreme,
        'MA+RSI Combo': strategy_ma_rsi_combo,
        'Bollinger Band': strategy_bollinger_band,
        'Bollinger Squeeze': strategy_bollinger_squeeze,
        'Volume Confirm': strategy_volume_confirmation,
        'TA Confluence': strategy_ta_confluence,
        'TA Strengthened': strategy_ta_strengthened
    }
    
    results = []
    equity_curves = {}
    
    for name, func in strategies.items():
        bt = Backtester(df, initial_capital)
        bt.run(df, func)
        metrics = bt.evaluate()
        metrics['strategy'] = name
        metrics['ticker'] = ticker
        results.append(metrics)
        
        if len(bt.daily_values) > 0:
            equity_df = pd.DataFrame(bt.daily_values)
            equity_df['strategy'] = name
            equity_df['ticker'] = ticker
            equity_df['dataset'] = dataset_name
            equity_curves[name] = equity_df
    
    results_df = pd.DataFrame(results)
    return results_df, equity_curves


def split_train_test(df: pd.DataFrame, train_end_date='2021-12-31', test_start_date='2022-01-01'):
    """划分训练集和测试集"""
    df['date'] = pd.to_datetime(df['date'])
    train = df[df['date'] <= train_end_date].copy()
    test = df[df['date'] >= test_start_date].copy()
    print(f"📚 训练集: {len(train)} 天 ({train['date'].iloc[0].date()} ~ {train['date'].iloc[-1].date()})")
    print(f"🔬 测试集: {len(test)} 天 ({test['date'].iloc[0].date()} ~ {test['date'].iloc[-1].date()})")
    return train, test


def main():
    parser = argparse.ArgumentParser(description='A股ETF策略探索与回测（并行化版本）')
    parser.add_argument('--tickers', nargs='+', help='指定要回测的ETF代码列表（空格分隔）')
    parser.add_argument('--parallel', action='store_true', help='启用并行处理')
    parser.add_argument('--max-workers', type=int, default=4, help='并行进程数（默认4）')
    parser.add_argument('--capital', type=float, default=100000, help='初始资金（默认100000）')
    parser.add_argument('--train-end', default='2021-12-31', help='训练集结束日期')
    parser.add_argument('--test-start', default='2022-01-01', help='测试集开始日期')
    parser.add_argument('--from-date', default=None, help='增量回测起始日期（YYYY-MM-DD），只回测该日期之后的数据')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔬 A股ETF策略探索与回测（训练集+测试集）[并行化]")
    print("=" * 60)
    
    # 向后兼容：如果没有指定tickers且可能存在历史单文件数据，使用原来的单文件模式
    history_file = os.path.join(RAW_DIR, "etf_history_2015_2025.csv")
    if args.tickers is None and os.path.exists(history_file):
        print(f"📂 检测到历史数据文件，使用单文件模式（向后兼容）")
        df = pd.read_csv(history_file)
        print(f"✅ 总数据: {len(df)} 条记录")
        
        # 按ETF分组
        print("\n📊 ETF列表:")
        codes = df['code'].unique()
        print(f"   共 {len(codes)} 只ETF")
        print(f"   前5只: {codes[:5]}")
        
        # 选择沪深300ETF作为示例
        target_code = '510300'
        if target_code in codes:
            df_target = df[df['code'] == target_code].copy()
            print(f"\n🎯 选择标的: {target_code} (沪深300ETF)")
            print(f"   数据条数: {len(df_target)}")
        else:
            print(f"⚠️  未找到 {target_code}，使用第一只ETF: {codes[0]}")
            df_target = df[df['code'] == codes[0]].copy()
        
        # 使用单文件模式
        train_results, test_results = run_all_strategies(
            tickers=df_target,
            initial_capital=args.capital,
            train_end_date=args.train_end,
            test_start_date=args.test_start,
            parallel=args.parallel,
            max_workers=args.max_workers
        )
        
        # 生成汇总对比报告
        print("\n" + "="*60)
        print("📊 生成汇总报告")
        print("="*60)
        
        if len(train_results) > 0 and len(test_results) > 0:
            summary_rows = []
            strategies = train_results['strategy'].unique()
            for strategy in strategies:
                train_row = train_results[train_results['strategy'] == strategy]
                test_row = test_results[test_results['strategy'] == strategy]
                
                summary_rows.append({
                    'strategy': strategy,
                    'train_return': train_row.iloc[0]['total_return'] if len(train_row) > 0 else None,
                    'train_sharpe': train_row.iloc[0]['sharpe_ratio'] if len(train_row) > 0 else None,
                    'train_maxdd': train_row.iloc[0]['max_drawdown'] if len(train_row) > 0 else None,
                    'test_return': test_row.iloc[0]['total_return'] if len(test_row) > 0 else None,
                    'test_sharpe': test_row.iloc[0]['sharpe_ratio'] if len(test_row) > 0 else None,
                    'test_maxdd': test_row.iloc[0]['max_drawdown'] if len(test_row) > 0 else None,
                })
            
            summary_df = pd.DataFrame(summary_rows)
            summary_file = os.path.join(RESULTS_DIR, "strategy_comparison_summary.csv")
            summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')
            print(f"✅ 训练/测试对比汇总已保存: {summary_file}")
        
        print("\n" + "="*60)
        print("✅ 全部完成！")
        print("="*60)
        print(f"📁 结果目录: {RESULTS_DIR}")
        print("   包含:")
        print("   - train_results.csv      (训练集策略汇总)")
        print("   - test_results.csv       (测试集策略汇总)")
        print("   - strategy_comparison_summary.csv (训练vs测试对比)")
        print("\n💡 下一步: 运行 prepare_dashboard.py 生成看板数据，然后访问 http://localhost:8081/analysis.html")
        return
    
    # 新模式：并行处理多个ETF
    tickers = args.tickers
    train_results, test_results = run_all_strategies(
        tickers=tickers,
        initial_capital=args.capital,
        train_end_date=args.train_end,
        test_start_date=args.test_start,
        parallel=args.parallel,
        max_workers=args.max_workers
    )
    
    # 生成汇总对比报告
    print("\n" + "="*60)
    print("📊 生成汇总报告")
    print("="*60)
    
    if len(train_results) > 0 and len(test_results) > 0:
        summary_rows = []
        strategies = train_results['strategy'].unique()
        for strategy in strategies:
            train_group = train_results[train_results['strategy'] == strategy]
            test_group = test_results[test_results['strategy'] == strategy]
            
            # 计算跨ETF的平均指标
            train_return_avg = train_group['total_return'].mean()
            train_sharpe_avg = train_group['sharpe_ratio'].mean()
            train_maxdd_avg = train_group['max_drawdown'].mean()
            
            test_return_avg = test_group['total_return'].mean()
            test_sharpe_avg = test_group['sharpe_ratio'].mean()
            test_maxdd_avg = test_group['max_drawdown'].mean()
            
            summary_rows.append({
                'strategy': strategy,
                'train_return': train_return_avg,
                'train_sharpe': train_sharpe_avg,
                'train_maxdd': train_maxdd_avg,
                'test_return': test_return_avg,
                'test_sharpe': test_sharpe_avg,
                'test_maxdd': test_maxdd_avg,
                'etf_count_train': len(train_group),
                'etf_count_test': len(test_group)
            })
        
        summary_df = pd.DataFrame(summary_rows)
        summary_file = os.path.join(RESULTS_DIR, "strategy_comparison_summary.csv")
        summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')
        print(f"✅ 训练/测试对比汇总已保存: {summary_file}")
        
        # 输出最佳策略
        print("\n🏆 训练集表现最佳策略:")
        best_train = summary_df.sort_values('train_sharpe', ascending=False).head(3)
        for _, row in best_train.iterrows():
            print(f"   {row['strategy']}: 夏普={row['train_sharpe']:.2f}, 收益={row['train_return']:.2f}%")
        
        print("\n🏆 测试集表现最佳策略:")
        best_test = summary_df.sort_values('test_sharpe', ascending=False).head(3)
        for _, row in best_test.iterrows():
            print(f"   {row['strategy']}: 夏普={row['test_sharpe']:.2f}, 收益={row['test_return']:.2f}%")
    
    print("\n" + "="*60)
    print("✅ 全部完成！")
    print("="*60)
    print(f"📁 结果目录: {RESULTS_DIR}")
    print("   包含:")
    print("   - train_results.csv      (训练集策略汇总)")
    print("   - test_results.csv       (测试集策略汇总)")
    print("   - strategy_comparison_summary.csv (多ETF策略平均表现)")
    print("\n💡 下一步: 运行 prepare_dashboard.py 生成看板数据，然后访问 http://localhost:8081/analysis.html")

if __name__ == "__main__":
    main()
