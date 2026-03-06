#!/usr/bin/env python3
"""
虚拟账户管理类

用于A股ETF量化交易的账户管理，支持：
- 现金和持仓管理
- 交易执行与记录
- 状态持久化
- 市值更新
- 日志与统计

Example:
    >>> from virtual_account import VirtualAccount
    >>> account = VirtualAccount(initial_capital=1000000)
    >>> account.execute_trade("510300", 100, 4.5)
    >>> total_value = account.get_total_value()
    >>> account.save_state("2024-03-06")
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import uuid


class VirtualAccount:
    """
    虚拟交易账户管理类

     managercapital, positions, and trading history for quantitative trading.

    Attributes:
        cash (float): 可用现金
        positions (dict): 持仓字典 {symbol: {'quantity': int, 'avg_cost': float, 'market_value': float}}
        data_dir (str): 数据存储目录
        trade_history_file (Path): 交易历史文件路径
        state_dir (Path): 状态文件目录
        logs_dir (Path): 日志文件目录
        _lock (threading.RLock): 线程锁，确保并发安全
    """

    def __init__(self, initial_capital: float = 1000000.0, data_dir: str = "data"):
        """
        初始化虚拟账户

        Args:
            initial_capital: 初始资金，默认100万元
            data_dir: 数据目录路径，默认"data"

        Raises:
            ValueError: 当初始资金小于0时
            OSError: 当无法创建数据目录时
        """
        if initial_capital < 0:
            raise ValueError("Initial capital cannot be negative")

        self.cash: float = initial_capital
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.data_dir: Path = Path(data_dir)

        # 定义文件路径结构
        self.accounts_dir: Path = self.data_dir / "accounts"
        self.state_dir: Path = self.accounts_dir / "states"
        self.trade_history_file: Path = self.accounts_dir / "trades.json"
        self.logs_dir: Path = self.accounts_dir / "logs"

        # 线程锁
        self._lock = threading.RLock()

        # 初始化目录结构
        self._initialize_directories()

    def _initialize_directories(self) -> None:
        """创建必要的数据目录结构"""
        with self._lock:
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                self.logs_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OSError(f"Failed to create data directories: {e}")

    # ==================== 账户查询方法 ====================

    def get_balance(self) -> float:
        """
        获取可用现金余额

        Returns:
            float: 当前可用现金
        """
        with self._lock:
            return round(self.cash, 2)

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        获取当前持仓详情

        Returns:
            dict: 持仓字典，格式为
                {
                    symbol: {
                        'quantity': int,      # 持仓数量
                        'avg_cost': float,    # 平均成本
                        'market_value': float # 当前市值
                    }
                }
        """
        with self._lock:
            # 返回副本避免外部修改
            positions_copy = {}
            for symbol, pos in self.positions.items():
                positions_copy[symbol] = {
                    'quantity': pos['quantity'],
                    'avg_cost': round(pos['avg_cost'], 4),
                    'market_value': round(pos['market_value'], 2)
                }
            return positions_copy

    def get_total_value(self) -> float:
        """
        获取账户总资产（现金 + 持仓市值）

        Returns:
            float: 账户总价值
        """
        with self._lock:
            total_market_value = sum(pos['market_value'] for pos in self.positions.values())
            total_value = self.cash + total_market_value
            return round(total_value, 2)

    def get_position_value(self, symbol: str) -> float:
        """
        获取单个持仓的市值

        Args:
            symbol: 证券代码

        Returns:
            float: 该持仓的市值，如果未持有则返回0.0
        """
        with self._lock:
            if symbol in self.positions:
                return round(self.positions[symbol]['market_value'], 2)
            return 0.0

    # ==================== 交易执行方法 ====================

    def execute_trade(self, symbol: str, quantity: int, price: float, fee: float = 0.0005) -> Dict[str, Any]:
        """
        执行交易

        Args:
            symbol: 证券代码
            quantity: 交易数量（正数买入，负数卖出）
            price: 交易价格
            fee: 交易费率，默认0.05%（买卖双向收费）

        Returns:
            dict: 交易详情，包含
                - trade_id: 交易ID
                - symbol: 证券代码
                - quantity: 交易数量（带符号）
                - price: 成交价格
                - fee: 实际费率
                - fee_amount: 手续费金额
                - net_value: 净交易金额（扣除/包含手续费）
                - side: 交易方向 'buy'/'sell'

        Raises:
            ValueError: 当数量为0、价格<=0、费率无效时
            InsufficientFundsError: 买入时现金不足
            InsufficientPositionError: 卖出时持仓不足
        """
        with self._lock:
            # 数据验证
            if quantity == 0:
                raise ValueError("Trade quantity cannot be zero")
            if price <= 0:
                raise ValueError("Trade price must be positive")
            if not (0 <= fee < 1):
                raise ValueError("Fee rate must be between 0 and 1")

            # 判断交易方向
            is_buy = quantity > 0
            abs_quantity = abs(quantity)

            # 生成交易ID
            trade_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().isoformat()

            trade_record = {
                'trade_id': trade_id,
                'timestamp': timestamp,
                'symbol': symbol,
                'quantity': quantity,
                'price': round(price, 4),
                'fee_rate': fee,
            }

            if is_buy:
                # ========== 买入逻辑 ==========
                trade_cost = price * abs_quantity
                fee_amount = trade_cost * fee
                net_value = trade_cost + fee_amount

                # 检查现金是否足够
                if net_value > self.cash:
                    raise InsufficientFundsError(
                        f"Insufficient funds for buy: need {net_value:.2f}, "
                        f"available {self.cash:.2f}"
                    )

                # 扣减现金
                self.cash -= net_value

                # 更新持仓
                if symbol not in self.positions:
                    # 新建持仓
                    self.positions[symbol] = {
                        'quantity': abs_quantity,
                        'avg_cost': price,
                        'market_value': price * abs_quantity
                    }
                else:
                    # 更新持仓: 加权平均成本
                    old_qty = self.positions[symbol]['quantity']
                    old_avg = self.positions[symbol]['avg_cost']
                    new_qty = old_qty + abs_quantity
                    weighted_sum = old_qty * old_avg + abs_quantity * price
                    new_avg = weighted_sum / new_qty

                    self.positions[symbol]['quantity'] = new_qty
                    self.positions[symbol]['avg_cost'] = new_avg
                    self.positions[symbol]['market_value'] = price * new_qty

                side = 'buy'

            else:
                # ========== 卖出逻辑 ==========
                # 检查持仓是否充足
                if symbol not in self.positions or self.positions[symbol]['quantity'] < abs_quantity:
                    current_qty = self.positions.get(symbol, {}).get('quantity', 0)
                    raise InsufficientPositionError(
                        f"Insufficient position for sell: need {abs_quantity}, "
                        f"available {current_qty} for {symbol}"
                    )

                trade_value = price * abs_quantity
                fee_amount = trade_value * fee
                net_value = trade_value - fee_amount

                # 增加现金
                self.cash += net_value

                # 减少持仓
                old_qty = self.positions[symbol]['quantity']
                old_avg = self.positions[symbol]['avg_cost']
                new_qty = old_qty - abs_quantity

                if new_qty == 0:
                    # 清仓
                    del self.positions[symbol]
                else:
                    # 卖出不影响平均成本，但数量减少
                    self.positions[symbol]['quantity'] = new_qty
                    self.positions[symbol]['market_value'] = price * new_qty

                side = 'sell'

            # 记录交易结果
            trade_record.update({
                'fee_amount': round(fee_amount, 2),
                'net_value': round(net_value, 2),
                'side': side,
            })

            # 追加到交易历史文件
            self._append_trade_record(trade_record)

            # 记录日志
            self._log_operation(f"Trade executed: {side.upper()} {abs_quantity} {symbol} @ {price:.4f}, "
                              f"fee={fee_amount:.2f}, net_value={net_value:.2f}")

            return trade_record

    def _append_trade_record(self, trade_record: Dict[str, Any]) -> None:
        """追加交易记录到 trades.json 文件（JSONL格式）"""
        with self._lock:
            try:
                with open(self.trade_history_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(trade_record, ensure_ascii=False) + '\n')
            except Exception as e:
                self._log_operation(f"Error appending trade record: {e}")

    def _log_operation(self, message: str) -> None:
        """记录操作日志"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        log_file = self.logs_dir / f"account_{date_str}.log"

        with self._lock:
            try:
                timestamp = datetime.now().isoformat()
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"[{timestamp}] {message}\n")
            except Exception as e:
                # 日志写入失败不应影响主流程
                print(f"Warning: Failed to write log: {e}")

    # ==================== 状态持久化 ====================

    def save_state(self, date: str) -> None:
        """
        保存账户状态快照

        Args:
            date: 日期字符串，格式 YYYY-MM-DD

        Raises:
            ValueError: 当日期格式不正确时
            OSError: 当无法写入文件时
        """
        # 验证日期格式
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Date must be in format YYYY-MM-DD")

        with self._lock:
            # 计算当日交易
            trades_today = self._get_trades_for_date(date)

            # 构建状态数据
            state = {
                'date': date,
                'cash': round(self.cash, 2),
                'positions': self.get_positions(),  # 已经返回副本
                'total_value': self.get_total_value(),
                'trades_today': trades_today,
                'saved_at': datetime.now().isoformat()
            }

            # 保存到文件
            state_file = self.state_dir / f"state_{date}.json"
            try:
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                self._log_operation(f"State saved to {state_file}")
            except Exception as e:
                raise OSError(f"Failed to save state file: {e}")

    def _get_trades_for_date(self, date: str) -> List[Dict[str, Any]]:
        """获取指定日期的所有交易记录"""
        trades = []
        try:
            with open(self.trade_history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    trade = json.loads(line)
                    trade_date = trade['timestamp'][:10]  # ISO格式取前10位
                    if trade_date == date:
                        trades.append(trade)
        except FileNotFoundError:
            pass  # 交易文件不存在则返回空列表
        return trades

    def load_state(self, date: str) -> bool:
        """
        从文件加载账户状态

        Args:
            date: 日期字符串，格式 YYYY-MM-DD

        Returns:
            bool: 加载成功返回True，文件不存在或失败返回False

        Raises:
            ValueError: 当日期格式不正确时
        """
        # 验证日期格式
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Date must be in format YYYY-MM-DD")

        state_file = self.state_dir / f"state_{date}.json"

        if not state_file.exists():
            return False

        with self._lock:
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                self.cash = state['cash']
                # positions已经是副本，直接赋值
                self.positions = state['positions']

                self._log_operation(f"State loaded from {state_file}")
                return True
            except Exception as e:
                self._log_operation(f"Error loading state: {e}")
                return False

    def auto_load_latest(self) -> bool:
        """
        自动加载最近的状态文件

        按文件名降序查找 state_*.json 文件，加载最新的一个

        Returns:
            bool: 加载成功返回True，没有找到状态文件返回False
        """
        with self._lock:
            state_files = list(self.state_dir.glob("state_*.json"))
            if not state_files:
                return False

            # 按文件名排序（文件名包含日期，按字符串排序即可）
            latest_file = sorted(state_files)[-1]

            # 从文件名提取日期
            date = latest_file.stem.replace("state_", "")

            return self.load_state(date)

    # ==================== 市值更新 ====================

    def update_market_prices(self, prices: Dict[str, float]) -> None:
        """
        用最新市场价格更新持仓市值

        Args:
            prices: 价格字典 {symbol: current_price}

        Note:
            仅更新已持有的证券，不在持仓中的symbol会被忽略
        """
        with self._lock:
            for symbol, price in prices.items():
                if symbol in self.positions:
                    qty = self.positions[symbol]['quantity']
                    self.positions[symbol]['market_value'] = price * qty

            self._log_operation(f"Market prices updated: {len(prices)} symbols")

    # ==================== 统计方法 ====================

    def get_daily_pnl(self, date: str) -> float:
        """
        计算指定日期的盈亏（基于前一交易日收盘状态与当日收盘状态对比）

        Args:
            date: 日期字符串，格式 YYYY-MM-DD

        Returns:
            float: 当日盈亏（正数表示盈利，负数表示亏损）
                 如果找不到前一交易日状态，返回0.0
        """
        # 加载当日状态
        if not self.load_state(date):
            return 0.0

        current_value = self.get_total_value()

        # 查找交易日历，找到前一个交易日
        prev_date = self._get_previous_trading_day(date)
        if not prev_date:
            return 0.0

        # 临时保存当前状态，加载前一日状态
        temp_cash = self.cash
        temp_positions = self.positions.copy()

        if self.load_state(prev_date):
            prev_value = self.get_total_value()
            pnl = current_value - prev_value
        else:
            pnl = 0.0

        # 恢复当前状态
        self.cash = temp_cash
        self.positions = temp_positions

        return round(pnl, 2)

    def _get_previous_trading_day(self, date: str) -> Optional[str]:
        """获取前一个交易日的日期字符串（简化版：直接返回前一天）"""
        try:
            current = datetime.strptime(date, '%Y-%m-%d')
            previous = current.replace(day=current.day - 1)
            return previous.strftime('%Y-%m-%d')
        except ValueError:
            # 处理月初情况
            return None

    def get_trade_history(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        获取指定日期范围内的交易历史

        Args:
            start_date: 开始日期，格式 YYYY-MM-DD（包含）
            end_date: 结束日期，格式 YYYY-MM-DD（包含）

        Returns:
            list: 交易记录列表，按时间戳升序排列
        """
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Dates must be in format YYYY-MM-DD")

        trades = []
        try:
            with open(self.trade_history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    trade = json.loads(line)
                    trade_date = trade['timestamp'][:10]
                    if start_date <= trade_date <= end_date:
                        trades.append(trade)
        except FileNotFoundError:
            pass

        # 按时间戳排序
        trades.sort(key=lambda x: x['timestamp'])
        return trades

    # ==================== 便捷方法 ====================

    def get_position_quantity(self, symbol: str) -> int:
        """获取持仓数量（便捷方法）"""
        with self._lock:
            return self.positions.get(symbol, {}).get('quantity', 0)

    def get_avg_cost(self, symbol: str) -> float:
        """获取持仓平均成本（便捷方法）"""
        with self._lock:
            return self.positions.get(symbol, {}).get('avg_cost', 0.0)

    def has_position(self, symbol: str) -> bool:
        """检查是否持有某证券"""
        with self._lock:
            return symbol in self.positions and self.positions[symbol]['quantity'] > 0


# ==================== 异常类 ====================

class InsufficientFundsError(Exception):
    """现金余额不足异常"""
    pass


class InsufficientPositionError(Exception):
    """持仓数量不足异常"""
    pass


# ==================== 使用示例 ====================

def example_usage():
    """
    使用示例
    """
    # 创建账户
    account = VirtualAccount(initial_capital=1000000.0, data_dir="data")

    print(f"初始资金: {account.get_balance():,.2f}")
    print(f"账户总价值: {account.get_total_value():,.2f}")

    # 买入交易
    try:
        trade1 = account.execute_trade("510300", 100, 4.50)  # 买入100股沪深300ETF
        print(f"买入交易完成: {trade1}")
    except Exception as e:
        print(f"买入失败: {e}")

    print(f"买入后现金: {account.get_balance():,.2f}")
    print(f"持仓: {account.get_positions()}")

    # 更新价格后查看市值
    account.update_market_prices({"510300": 4.60})
    print(f"更新后总价值: {account.get_total_value():,.2f}")

    # 卖出交易
    try:
        trade2 = account.execute_trade("510300", 50, 4.60)  # 卖出50股
        print(f"卖出交易完成: {trade2}")
    except Exception as e:
        print(f"卖出失败: {e}")

    # 保存状态
    today = datetime.now().strftime('%Y-%m-%d')
    account.save_state(today)

    # 查询交易历史
    history = account.get_trade_history(today, today)
    print(f"今日交易记录: {len(history)} 笔")

    # 获取当日盈亏（需要前一日有状态文件）
    pnl = account.get_daily_pnl(today)
    print(f"当日盈亏: {pnl:,.2f}")


def example_thread_safety():
    """
    线程安全示例
    """
    import time

    account = VirtualAccount(initial_capital=1000000, data_dir="data")

    def worker(thread_id: int):
        """并发交易线程"""
        for i in range(10):
            try:
                # 模拟随机交易
                trade = account.execute_trade(
                    symbol=f"ETF{thread_id % 3}",
                    quantity=10 if thread_id % 2 == 0 else -10,
                    price=4.5 + i * 0.01
                )
                print(f"Thread {thread_id}: trade_id={trade['trade_id']}")
            except Exception as e:
                print(f"Thread {thread_id}: {e}")
            time.sleep(0.01)

    # 启动5个并发线程
    import threading as th
    threads = [th.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"最终余额: {account.get_balance():,.2f}")
    print(f"最终总价值: {account.get_total_value():,.2f}")


if __name__ == "__main__":
    print("=" * 60)
    print("VirtualAccount 使用示例")
    print("=" * 60)

    # 基础示例
    print("\n--- 基础交易示例 ---")
    example_usage()

    # 线程安全示例（可选）
    # print("\n--- 线程安全示例 ---")
    # example_thread_safety()
