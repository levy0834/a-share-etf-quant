#!/usr/bin/env python3
"""
性能基准测试脚本

对比单进程串行 vs 多进程并行的回测性能
测试场景：前10个ETF × 2个策略（MA Cross, RSI Extreme）
"""
import os
import sys
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd

# 配置路径
WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from explore_strategies import Backtester, calculate_indicators, strategy_ma_cross, strategy_rsi_extreme

DAY_DIR = os.path.join(PROJECT_DIR, "data", "day")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

def load_etf_list(limit: int = 10) -> list:
    """加载前N个ETF数据文件路径"""
    if not os.path.exists(DAY_DIR):
        return []
    
    csv_files = [f for f in os.listdir(DAY_DIR) if f.endswith('.csv')]
    csv_files.sort()  # 按文件名排序保证一致性
    return [os.path.join(DAY_DIR, f) for f in csv_files[:limit]]

def load_etf_data(csv_path: str) -> pd.DataFrame:
    """加载单个ETF数据"""
    df = pd.read_csv(csv_path)
    # 确保列名一致
    df.columns = [col.lower() for col in df.columns]
    if 'code' not in df.columns and 'date' in df.columns:
        # 从文件名提取code
        code = os.path.basename(csv_path).replace('.csv', '')
        df['code'] = code
    return df

def run_single_strategy(data: pd.DataFrame, strategy_func, capital: float = 100000.0) -> dict:
    """运行单个策略回测并返回指标"""
    bt = Backtester(data.copy(), initial_capital=capital)
    bt.run(data, strategy_func)
    metrics = bt.evaluate()
    return metrics

def sequential_benchmark(etf_data_dict: dict, strategies: dict, capital: float) -> tuple:
    """单进程串行基准测试"""
    start_time = time.perf_counter()
    
    results = []
    for etf_code, data in etf_data_dict.items():
        for strategy_name, strategy_func in strategies.items():
            try:
                metrics = run_single_strategy(data, strategy_func, capital)
                metrics['ticker'] = etf_code
                metrics['strategy'] = strategy_name
                results.append(metrics)
            except Exception as e:
                print(f"❌ {etf_code} - {strategy_name}: {e}")
    
    elapsed = time.perf_counter() - start_time
    total_runs = len(etf_data_dict) * len(strategies)
    throughput = total_runs / elapsed if elapsed > 0 else 0
    
    return elapsed, throughput, results

def parallel_benchmark(etf_data_dict: dict, strategies: dict, capital: float, max_workers: int) -> tuple:
    """多进程并行基准测试"""
    start_time = time.perf_counter()
    
    # 准备所有任务：(etf_code, strategy_name)
    tasks = []
    for etf_code in etf_data_dict.keys():
        for strategy_name in strategies.keys():
            tasks.append((etf_code, strategy_name))
    
    all_results = []
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 提交任务
        future_to_task = {
            executor.submit(
                run_single_strategy,
                etf_data_dict[etf_code],
                strategies[strategy_name],
                capital
            ): (etf_code, strategy_name)
            for etf_code, strategy_name in tasks
        }
        
        # 收集结果
        for future in as_completed(future_to_task):
            etf_code, strategy_name = future_to_task[future]
            try:
                metrics = future.result()
                metrics['ticker'] = etf_code
                metrics['strategy'] = strategy_name
                all_results.append(metrics)
            except Exception as e:
                print(f"❌ {etf_code} - {strategy_name}: {e}")
    
    elapsed = time.perf_counter() - start_time
    total_runs = len(tasks)
    throughput = total_runs / elapsed if elapsed > 0 else 0
    
    return elapsed, throughput, all_results

def ensure_test_data(etf_paths: list) -> dict:
    """确保有测试数据可用，返回 ETF代码 -> DataFrame 字典"""
    etf_data_dict = {}
    
    if len(etf_paths) >= 10:
        # 有足够的数据文件，直接加载前10个
        print(f"✅ 发现 {len(etf_paths)} 个ETF数据文件，使用前10个")
        for i, path in enumerate(etf_paths[:10]):
            try:
                df = load_etf_data(path)
                code = f"ETF{i+1:02d}_{os.path.basename(path).replace('.csv', '')}"
                etf_data_dict[code] = df
                print(f"  加载: {code} ({len(df)} 行)")
            except Exception as e:
                print(f"  ⚠️  跳过 {path}: {e}")
    else:
        # 数据不足，使用单一数据文件生成模拟ETF
        print(f"⚠️  仅发现 {len(etf_paths)} 个数据文件，需10个。使用模拟模式生成测试数据...")
        
        # 尝试加载 available 的数据
        source_df = None
        if etf_paths:
            try:
                source_df = load_etf_data(etf_paths[0])
                print(f"  加载源数据: {etf_paths[0]} ({len(source_df)} 行)")
            except Exception as e:
                print(f"  ❌ 无法加载源数据: {e}")
        
        if source_df is None:
            # 使用内置的示例数据
            print("  使用内置示例数据（沪深300 ETF模拟）")
            dates = pd.date_range('2020-01-01', '2023-12-31', freq='B')
            n = len(dates)
            source_df = pd.DataFrame({
                'date': dates,
                'code': '510300',
                'open': 3.0 + pd.Series(range(n)) * 0.001,
                'high': 3.1 + pd.Series(range(n)) * 0.001,
                'low': 2.9 + pd.Series(range(n)) * 0.001,
                'close': 3.05 + pd.Series(range(n)) * 0.001,
                'volume': (1000000 + pd.Series(range(n)) * 100).astype(int),
                'pct_change': pd.Series([0] * n),
                'change': pd.Series([0] * n)
            })
        
        # 生成10个略有差异的ETF（添加随机扰动模拟不同标的）
        import numpy as np
        for i in range(10):
            df = source_df.copy()
            code = f"SIM{i+1:02d}"
            # 添加 ±1% 的价格扰动和 ±5% 的成交量扰动
            noise = np.random.normal(0, 0.01, len(df))
            df['code'] = code
            df['close'] = df['close'] * (1 + noise)
            df['high'] = df['high'] * (1 + noise)
            df['low'] = df['low'] * (1 + noise)
            df['open'] = df['open'] * (1 + noise)
            df['volume'] = (df['volume'] * (1 + np.random.normal(0, 0.05, len(df)))).astype(int)
            etf_data_dict[code] = df
            print(f"  生成: {code} (模拟)")
    
    return etf_data_dict

def main():
    parser = argparse.ArgumentParser(description='性能基准测试 - 单进程 vs 多进程')
    parser.add_argument('--etfs', type=int, default=10, help='要测试的ETF数量（默认10）')
    parser.add_argument('--workers', type=int, default=4, help='并行进程数（默认4）')
    parser.add_argument('--capital', type=float, default=100000.0, help='初始资金（默认100000）')
    parser.add_argument('--output', default='benchmark.txt', help='输出文件名（默认benchmark.txt）')
    
    args = parser.parse_args()
    
    print("="*60)
    print("📊 性能基准测试")
    print("="*60)
    
    # 1. 准备测试数据
    print("\n🔍 步骤1: 加载测试数据")
    etf_paths = load_etf_list(limit=args.etfs)
    etf_data_dict = ensure_test_data(etf_paths)
    
    if len(etf_data_dict) < 1:
        print("❌ 没有可用的ETF数据，测试终止")
        return
    
    print(f"\n✅ 准备测试: {len(etf_data_dict)} 个ETF × 2 个策略 = {len(etf_data_dict)*2} 次回测")
    
    # 2. 定义策略
    strategies = {
        'MA Cross': strategy_ma_cross,
        'RSI Extreme': strategy_rsi_extreme
    }
    
    # 3. 串行测试
    print("\n" + "="*60)
    print("⚡ 开始串行测试（单进程）...")
    print("="*60)
    seq_time, seq_throughput, seq_results = sequential_benchmark(
        etf_data_dict, strategies, args.capital
    )
    print(f"\n✅ 串行测试完成")
    print(f"   耗时: {seq_time:.3f} 秒")
    print(f"   吞吐量: {seq_throughput:.2f} 策略/秒")
    
    # 4. 并行测试
    print("\n" + "="*60)
    print(f"🚀 开始并行测试（{args.workers}进程）...")
    print("="*60)
    par_time, par_throughput, par_results = parallel_benchmark(
        etf_data_dict, strategies, args.capital, args.workers
    )
    print(f"\n✅ 并行测试完成")
    print(f"   耗时: {par_time:.3f} 秒")
    print(f"   吞吐量: {par_throughput:.2f} 策略/秒")
    
    # 5. 计算加速比
    speedup = seq_time / par_time if par_time > 0 else 0
    efficiency = speedup / args.workers * 100
    
    # 6. 输出结果到文件
    output_path = os.path.join(RESULTS_DIR, args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write("性能基准测试报告\n")
        f.write("="*60 + "\n\n")
        
        f.write("📋 测试配置\n")
        f.write("-"*60 + "\n")
        f.write(f"ETF数量: {len(etf_data_dict)}\n")
        f.write(f"策略数量: {len(strategies)}\n")
        f.write(f"总回测次数: {len(etf_data_dict) * len(strategies)}\n")
        f.write(f"初始资金: {args.capital:,.0f}\n")
        f.write(f"并行进程数: {args.workers}\n\n")
        
        f.write("📊 测试结果\n")
        f.write("-"*60 + "\n")
        f.write(f"{'模式':<10} {'耗时(秒)':<12} {'吞吐量(策略/秒)':<20} {'加速比':<10}\n")
        f.write("-"*60 + "\n")
        f.write(f"{'串行':<10} {seq_time:<12.3f} {seq_throughput:<20.2f} {1.0:<10.2f}x\n")
        f.write(f"{'并行':<10} {par_time:<12.3f} {par_throughput:<20.2f} {speedup:<10.2f}x\n")
        f.write("-"*60 + "\n\n")
        
        f.write("📈 性能分析\n")
        f.write("-"*60 + "\n")
        f.write(f"加速比 (Speedup): {speedup:.2f}x\n")
        f.write(f"并行效率 (Efficiency): {efficiency:.1f}%\n")
        f.write(f"理论最大加速比: {args.workers:.1f}x\n\n")
        
        f.write("💡 说明\n")
        f.write("-"*60 + "\n")
        f.write("- 加速比 = 串行耗时 / 并行耗时\n")
        f.write("- 并行效率 = (加速比 / 进程数) × 100%\n")
        f.write("- 理想情况下，效率应接近100%\n")
        f.write("- 实际效率受进程启动开销、数据序列化、GIL释放等因素影响\n\n")
        
        f.write("📋 详细结果（串行）\n")
        f.write("-"*60 + "\n")
        for r in seq_results:
            f.write(f"{r['ticker']} | {r['strategy']} | 总收益: {r.get('total_return', 0):.2f}% | "
                   f"年化: {r.get('annual_return', 0):.2f}% | 最大回撤: {r.get('max_drawdown', 0):.2f}%\n")
        f.write("\n")
        
        f.write("📋 详细结果（并行）\n")
        f.write("-"*60 + "\n")
        for r in par_results:
            f.write(f"{r['ticker']} | {r['strategy']} | 总收益: {r.get('total_return', 0):.2f}% | "
                   f"年化: {r.get('annual_return', 0):.2f}% | 最大回撤: {r.get('max_drawdown', 0):.2f}%\n")
    
    print(f"\n📄 详细结果已保存: {output_path}")
    print("\n" + "="*60)
    print("✅ 基准测试完成！")
    print("="*60)

if __name__ == "__main__":
    main()
