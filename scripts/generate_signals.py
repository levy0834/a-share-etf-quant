#!/usr/bin/env python3
"""
每日信号生成脚本 - A股ETF量化策略

功能：
1. 加载所有ETF的最新数据（和历史数据用于指标计算）
2. 应用所有技术策略（12+种）
3. 计算综合置信度和交易信号
4. 过滤并输出JSON信号文件

使用方法：
    python generate_signals.py [--output-dir signals] [--dry-run] [--threshold 0.7]

命令行选项：
    --output-dir DIR   输出目录（默认：signals）
    --dry-run          仅计算不保存文件
    --threshold N      置信度阈值（默认：0.7）
    --workers N       并行进程数（默认：CPU核心数）
    --verbose         显示详细日志
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import signal

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from strategies import (
    calculate_all_indicators,
    STRATEGIES,
    get_strategy,
    list_strategies
)

# ============================================================================
# 日志配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据加载模块
# ============================================================================

def load_etf_data(data_path: str = "data/raw/etf_history_2015_2025.csv") -> Dict[str, pd.DataFrame]:
    """
    加载所有ETF的历史数据

    参数:
        data_path: 原始数据文件路径（包含所有ETF的历史数据）

    返回:
        字典 {etf_code: DataFrame}，每个DataFrame包含该ETF的完整历史数据
    """
    logger.info(f"正在加载ETF数据: {data_path}")

    data_file = Path(data_path)
    if not data_file.exists():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    # 读取CSV
    df = pd.read_csv(data_file)
    logger.info(f"读取到 {len(df)} 行数据，包含 {df['code'].nunique()} 只ETF")

    # 按ETF分组
    etf_groups = {}
    for code, group in df.groupby('code'):
        # 按日期排序
        group = group.sort_values('date').reset_index(drop=True)
        # 确保日期列为datetime
        group['date'] = pd.to_datetime(group['date'])
        etf_groups[code] = group

    logger.info(f"成功加载 {len(etf_groups)} 只ETF的历史数据")
    return etf_groups


def get_latest_data(etf_groups: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
    """
    从分组数据中提取每只ETF的最新数据行

    参数:
        etf_groups: ETF数据字典

    返回:
        字典 {etf_code: latest_row}，latest_row是包含最新数据的Series
    """
    latest_data = {}
    for code, df in etf_groups.items():
        if len(df) > 0:
            latest_data[code] = df.iloc[-1]
        else:
            logger.warning(f"ETF {code} 数据为空，跳过")
    return latest_data


# ============================================================================
# 信号计算模块
# ============================================================================

def calculate_signals_for_etf(
    etf_code: str,
    df: pd.DataFrame,
    threshold: float = 0.7
) -> Optional[Dict[str, Any]]:
    """
    为单个ETF计算所有策略的信号

    参数:
        etf_code: ETF代码
        df: 该ETF的历史数据DataFrame（完整历史）
        threshold: 置信度阈值

    返回:
        信号字典，格式如需求所示，或None（无信号或错误）
    """
    try:
        # 确保有足够的数据计算指标
        if len(df) < 60:  # 至少需要60个数据点来计算部分指标
            logger.debug(f"ETF {etf_code} 数据不足（{len(df)}行），跳过")
            return None

        # 1. 计算所有技术指标
        df_with_indicators = calculate_all_indicators(df)

        # 2. 获取最新数据行（用于生成信号）
        latest_row = df_with_indicators.iloc[-1]

        # 3. 应用所有策略
        strategy_results = {}
        strategy_signals = []

        for strategy_name in STRATEGIES.keys():
            strategy_func = get_strategy(strategy_name)
            if strategy_func is None:
                continue

            try:
                # 调用策略函数
                if strategy_name in ['double_top_bottom', 'pair_trading']:
                    # 这些策略需要context参数
                    signal = strategy_func(latest_row, context={})
                elif strategy_name == 'simple_ml':
                    signal = strategy_func(latest_row, model_context={'model': None})
                else:
                    signal = strategy_func(latest_row)

                strategy_results[strategy_name] = signal
                if signal in ['buy', 'sell']:
                    strategy_signals.append(signal)
            except Exception as e:
                logger.warning(f"ETF {etf_code} 策略 {strategy_name} 执行失败: {e}")
                strategy_results[strategy_name] = 'hold'

        # 4. 计算综合置信度
        if not strategy_signals:
            # 没有明确信号
            return None

        # 统计方向
        buy_count = strategy_signals.count('buy')
        sell_count = strategy_signals.count('sell')
        total_signals = len(strategy_signals)

        # 计算置信度和最终方向
        if buy_count == 0 and sell_count == 0:
            return None

        if buy_count >= 3 or sell_count >= 3:
            # ≥3个策略共振
            confidence = 1.0
            if buy_count >= sell_count:
                final_action = 'buy'
                reasons = [name for name, sig in strategy_results.items() if sig == 'buy']
            else:
                final_action = 'sell'
                reasons = [name for name, sig in strategy_results.items() if sig == 'sell']
        elif (buy_count == 2 and sell_count == 0) or (sell_count == 2 and buy_count == 0):
            # 2个策略一致
            confidence = 0.7
            if buy_count == 2:
                final_action = 'buy'
                reasons = [name for name, sig in strategy_results.items() if sig == 'buy']
            else:
                final_action = 'sell'
                reasons = [name for name, sig in strategy_results.items() if sig == 'sell']
        elif (buy_count == 1 and sell_count == 0) or (sell_count == 1 and buy_count == 0):
            # 1个策略
            confidence = 0.5
            if buy_count == 1:
                final_action = 'buy'
                reasons = [name for name, sig in strategy_results.items() if sig == 'buy']
            else:
                final_action = 'sell'
                reasons = [name for name, sig in strategy_results.items() if sig == 'sell']
        else:
            # conflicting 信号 → hold
            return None

        # 5. 应用阈值过滤
        if confidence < threshold:
            return None

        # 6. 构建结果
        result = {
            'symbol': etf_code,
            'action': final_action,
            'confidence': round(confidence, 2),
            'reasons': reasons[:5],  # 最多列出5个原因
            'total_strategies': len(STRATEGIES),
            'buy_signals': buy_count,
            'sell_signals': sell_count
        }

        return result

    except Exception as e:
        logger.error(f"处理ETF {etf_code} 时出错: {e}", exc_info=True)
        return None


def generate_signals(
    etf_groups: Dict[str, pd.DataFrame],
    threshold: float = 0.7,
    workers: int = None,
    progress_callback=None
) -> List[Dict[str, Any]]:
    """
    为所有ETF生成信号（多进程并行）

    参数:
        etf_groups: ETF数据字典
        threshold: 置信度阈值
        workers: 并行进程数（默认：CPU核心数）
        progress_callback: 进度回调函数，接收 (current, total) 参数

    返回:
        信号列表（已过滤）
    """
    total_etfs = len(etf_groups)
    logger.info(f"开始为 {total_etfs} 只ETF生成信号，阈值: {threshold}，进程数: {workers or '自动'}")

    signals = []
    processed = 0

    # 使用进程池并行计算
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # 提交所有任务
        future_to_etf = {
            executor.submit(calculate_signals_for_etf, code, df, threshold): code
            for code, df in etf_groups.items()
        }

        # 收集结果
        for future in as_completed(future_to_etf):
            etf_code = future_to_etf[future]
            try:
                result = future.result()
                if result:
                    signals.append(result)
            except Exception as e:
                logger.error(f"ETF {etf_code} 执行异常: {e}")

            processed += 1
            if progress_callback:
                progress_callback(processed, total_etfs)
            else:
                if processed % 100 == 0:
                    logger.info(f"进度: {processed}/{total_etfs} ({(processed/total_etfs)*100:.1f}%)")

    logger.info(f"处理完成：共处理 {total_etfs} 只ETF，生成 {len(signals)} 个信号")
    return signals


# ============================================================================
# 输出模块
# ============================================================================

def save_signals_json(
    signals: List[Dict[str, Any]],
    output_dir: str = "signals",
    date_str: str = None,
    dry_run: bool = False
) -> Path:
    """
    将信号保存为JSON文件

    参数:
        signals: 信号列表
        output_dir: 输出目录
        date_str: 日期字符串（默认：当天日期）
        dry_run: 仅计算不保存

    返回:
        如果保存，返回文件路径；否则返回None
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_file = output_path / f"{date_str}.json"

    # 构建完整JSON结构
    json_data = {
        "date": date_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signals": signals,
        "stats": {
            "total_signals": len(signals),
            "buy_count": sum(1 for s in signals if s['action'] == 'buy'),
            "sell_count": sum(1 for s in signals if s['action'] == 'sell')
        }
    }

    if dry_run:
        logger.info(f"[DRY-RUN] 信号已生成但未保存（本应写入: {json_file}）")
        return None

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    logger.info(f"信号已保存到: {json_file}")
    logger.info(f"  买入信号: {json_data['stats']['buy_count']}")
    logger.info(f"  卖出信号: {json_data['stats']['sell_count']}")
    return json_file


def print_summary(signals: List[Dict[str, Any]]):
    """打印信号摘要"""
    print("\n" + "=" * 80)
    print("信号汇总")
    print("=" * 80)

    if not signals:
        print("今日无符合条件的高置信度信号。")
        return

    # 按操作分组
    buy_signals = [s for s in signals if s['action'] == 'buy']
    sell_signals = [s for s in signals if s['action'] == 'sell']

    print(f"\n总信号数: {len(signals)}")
    print(f"  买入: {len(buy_signals)}")
    print(f"  卖出: {len(sell_signals)}")

    print("\n买入信号（按置信度排序）:")
    for s in sorted(buy_signals, key=lambda x: x['confidence'], reverse=True)[:10]:
        print(f"  {s['symbol']}: confidence={s['confidence']:.2f}, reasons={', '.join(s['reasons'])}")

    print("\n卖出信号（按置信度排序）:")
    for s in sorted(sell_signals, key=lambda x: x['confidence'], reverse=True)[:10]:
        print(f"  {s['symbol']}: confidence={s['confidence']:.2f}, reasons={', '.join(s['reasons'])}")

    print("=" * 80)


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="A股ETF每日信号生成脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python generate_signals.py                          # 使用默认参数运行
  python generate_signals.py --output-dir ./my_signals --threshold 0.8  # 输出到自定义目录，提高阈值
  python generate_signals.py --dry-run --verbose     # 仅计算不保存，显示详细日志
        """
    )
    parser.add_argument('--output-dir', type=str, default='signals',
                        help='输出目录（默认：signals）')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅计算不保存文件')
    parser.add_argument('--threshold', type=float, default=0.7,
                        help='置信度阈值，0.0-1.0（默认：0.7）')
    parser.add_argument('--workers', type=int, default=None,
                        help='并行进程数（默认：CPU核心数）')
    parser.add_argument('--data-file', type=str,
                        default='data/raw/etf_history_2015_2025.csv',
                        help='ETF历史数据文件路径（默认：data/raw/etf_history_2015_2025.csv）')
    parser.add_argument('--verbose', action='store_true',
                        help='显示详细日志')
    parser.add_argument('--date', type=str, default=None,
                        help='指定日期（YYYY-MM-DD），默认今天')

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # 验证阈值
    if not 0.0 <= args.threshold <= 1.0:
        logger.error("阈值必须在 0.0 到 1.0 之间")
        sys.exit(1)

    # 显示配置信息
    logger.info("=" * 80)
    logger.info("A股ETF信号生成系统启动")
    logger.info("=" * 80)
    logger.info(f"可用策略: {', '.join(sorted(list_strategies()))}")
    logger.info(f"置信度阈值: {args.threshold}")
    logger.info(f"输出目录: {args.output_dir}")
    logger.info(f"Dry-run: {args.dry_run}")
    logger.info("=" * 80)

    try:
        # 1. 加载数据
        etf_groups = load_etf_data(args.data_file)

        if not etf_groups:
            logger.error("未加载到任何ETF数据")
            sys.exit(1)

        # 2. 生成信号（并行）
        signals = generate_signals(
            etf_groups=etf_groups,
            threshold=args.threshold,
            workers=args.workers
        )

        # 3. 保存或显示结果
        if not args.dry_run:
            save_signals_json(signals, args.output_dir, args.date, dry_run=False)

        print_summary(signals)

        logger.info("信号生成完成！")
        return 0

    except KeyboardInterrupt:
        logger.warning("用户中断操作")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序执行失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
