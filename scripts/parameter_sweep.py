#!/usr/bin/env python3
"""
参数敏感性分析脚本 - 完整版
扫描多个策略的关键参数，评估收益/夏普的稳定性
"""
import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from itertools import product
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import multiprocessing as mp

# 添加项目路径
PROJECT_DIR = "/Users/levy/.openclaw/workspace/projects/a-share-etf-quant"
sys.path.insert(0, PROJECT_DIR)
from scripts.backtester import Backtester, calculate_indicators

# 设置matplotlib中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 策略参数网格
PARAM_GRIDS = {
    'MA Cross': {
        'ma1': [5, 10, 15],
        'ma2': [20, 30, 40]
    },
    'RSI Extreme': {
        'oversold': [20, 25, 30],
        'overbought': [70, 75, 80]
    },
    'Bollinger Band': {
        'std': [1.5, 2.0, 2.5]
    }
}

def load_data():
    """加载并划分训练集/测试集"""
    df = pd.read_csv(os.path.join(PROJECT_DIR, 'data/raw/etf_history_2015_2025.csv'))
    df['date'] = pd.to_datetime(df['date'])
    df = calculate_indicators(df)
    
    # 划分训练集和测试集
    train = df[df['date'] < '2022-01-01'].copy().reset_index(drop=True)
    test = df[df['date'] >= '2022-01-01'].copy().reset_index(drop=True)
    
    print(f"📊 数据划分:")
    print(f"  训练集: {train['date'].min().date()} ~ {train['date'].max().date()} ({len(train)} 天)")
    print(f"  测试集: {test['date'].min().date()} ~ {test['date'].max().date()} ({len(test)} 天)")
    
    return train, test

def create_strategy_function(strategy_name, params):
    """
    根据策略名称和参数创建策略函数
    
    Returns:
        Callable: 策略函数，接收row返回'buy'/'sell'/'hold'
    """
    if strategy_name == 'MA Cross':
        ma1 = params['ma1']
        ma2 = params['ma2']
        col1 = f'ma{ma1}'
        col2 = f'ma{ma2}'
        
        def strategy(row):
            if pd.isna(row.get(col1)) or pd.isna(row.get(col2)):
                return 'hold'
            if row[col1] > row[col2]:
                return 'buy'
            elif row[col1] < row[col2]:
                return 'sell'
            return 'hold'
    
    elif strategy_name == 'RSI Extreme':
        oversold = params['oversold']
        overbought = params['overbought']
        
        def strategy(row):
            rsi = row.get('rsi')
            if pd.isna(rsi):
                return 'hold'
            if rsi < oversold:
                return 'buy'
            elif rsi > overbought:
                return 'sell'
            return 'hold'
    
    elif strategy_name == 'Bollinger Band':
        std = params['std']
        # 计算动态布林带列名（基于20日均线）
        # 注意：Backtester会重新计算指标，所以我们使用固定的列名
        
        def strategy(row):
            # 计算当前行的布林带（模拟动态计算）
            # 由于Backtester会重新计算，我们需要确保使用正确的参数
            # 这里需要传入std参数给Backtester，而不是在策略函数中计算
            # 所以我们返回特殊的策略标识
            return 'bollinger_band'  # 特殊标记
    
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    return strategy

def evaluate_params_single(strategy_name, params, dataset_name, data):
    """
    评估单个参数组合在指定数据集上的表现
    
    Returns:
        dict: 包含评估结果的字典
    """
    try:
        # 对于布林带策略，需要特殊处理以传递std参数
        if strategy_name == 'Bollinger Band':
            # 自定义计算指标以使用自定义std
            data_custom = data.copy()
            # 重新计算布林带 with custom std
            df_bb = data_custom.copy()
            df_bb['bb_middle'] = df_bb['close'].rolling(20).mean()
            bb_std = df_bb['close'].rolling(20).std()
            df_bb['bb_upper'] = df_bb['bb_middle'] + params['std'] * bb_std
            df_bb['bb_lower'] = df_bb['bb_middle'] - params['std'] * bb_std
            # 更新原数据框
            data_custom['bb_upper'] = df_bb['bb_upper']
            data_custom['bb_lower'] = df_bb['bb_lower']
            
            def strategy(row):
                if pd.isna(row.get('bb_upper')) or pd.isna(row.get('bb_lower')):
                    return 'hold'
                if row['close'] < row['bb_lower']:
                    return 'buy'
                elif row['close'] > row['bb_upper']:
                    return 'sell'
                return 'hold'
            
            bt = Backtester(data_custom)
            bt.run(data_custom, strategy)
        else:
            strategy_func = create_strategy_function(strategy_name, params)
            bt = Backtester(data)
            bt.run(data, strategy_func)
        
        metrics = bt.evaluate()
        
        return {
            'strategy': strategy_name,
            'params': str(params),
            'dataset': dataset_name,
            'total_return_pct': metrics.get('total_return_pct', 0),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
            'total_trades': metrics.get('total_trades', 0),
            'win_rate_pct': metrics.get('win_rate_pct', 0),
            'annual_return_pct': metrics.get('annual_return_pct', 0)
        }
    except Exception as e:
        print(f"  ❌ Error with {strategy_name} {params} on {dataset_name}: {str(e)}")
        return None

def worker_task(task):
    """
    工作函数用于多进程 - 处理单个参数组合
    
    Args:
        task: (strategy_name, params, train_data, test_data)
    
    Returns:
        list: 两个结果（训练集和测试集）
    """
    strategy_name, params, train_data, test_data = task
    
    results = []
    
    # 训练集评估
    train_result = evaluate_params_single(strategy_name, params, 'train', train_data)
    if train_result:
        results.append(train_result)
    
    # 测试集评估
    test_result = evaluate_params_single(strategy_name, params, 'test', test_data)
    if test_result:
        results.append(test_result)
    
    return results

def sweep_strategy_parallel(strategy_name, param_grid, train_data, test_data, n_workers=None):
    """
    并行扫描单一策略的所有参数组合
    
    Returns:
        list: 所有结果
    """
    if n_workers is None:
        n_workers = min(mp.cpu_count(), 4)  # 限制最多4个进程
    
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    
    # 生成所有参数组合
    all_combos = list(product(*values))
    total_combos = len(all_combos)
    
    print(f"\n🔍 Sweeping {strategy_name}: {total_combos} combinations using {n_workers} workers")
    
    # 准备任务列表
    tasks = [(strategy_name, dict(zip(keys, combo)), train_data, test_data) 
             for combo in all_combos]
    
    results = []
    
    # 使用ProcessPoolExecutor并行执行
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        # 提交所有任务
        future_to_task = {executor.submit(worker_task, task): task for task in tasks}
        
        # 使用tqdm显示进度
        with tqdm(total=total_combos, desc=f"  Processing {strategy_name}") as pbar:
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    task_results = future.result()
                    if task_results:
                        results.extend(task_results)
                except Exception as e:
                    params = task[1]
                    print(f"\n  ❌ Task failed for {params}: {e}")
                finally:
                    pbar.update(1)
    
    return results

def analyze_results(df):
    """
    分析结果，识别最优参数组合和稳健参数区间
    
    Returns:
        dict: 包含分析摘要的字典
    """
    summary = {}
    
    for strategy in df['strategy'].unique():
        strategy_data = df[df['strategy'] == strategy]
        
        # 分离训练集和测试集
        train_data = strategy_data[strategy_data['dataset'] == 'train']
        test_data = strategy_data[strategy_data['dataset'] == 'test']
        
        # 按夏普比率排序，找出最佳训练参数
        best_train = train_data.sort_values('sharpe_ratio', ascending=False).head(1)
        
        if not best_train.empty:
            best_params = best_train['params'].iloc[0]
            best_train_sharpe = best_train['sharpe_ratio'].iloc[0]
            best_train_return = best_train['total_return_pct'].iloc[0]
            
            # 找到对应的测试集结果
            matching_test = test_data[test_data['params'] == best_params]
            if not matching_test.empty:
                best_test_sharpe = matching_test['sharpe_ratio'].iloc[0]
                best_test_return = matching_test['total_return_pct'].iloc[0]
            else:
                best_test_sharpe = np.nan
                best_test_return = np.nan
            
            summary[strategy] = {
                'best_params': best_params,
                'train_sharpe': best_train_sharpe,
                'train_return_pct': best_train_return,
                'test_sharpe': best_test_sharpe,
                'test_return_pct': best_test_return
            }
    
    return summary

def generate_heatmaps(df, output_path):
    """
    为每个策略生成参数敏感性热力图
    
    Args:
        df: 结果DataFrame
        output_path: 输出文件路径（包含策略名称占位符）
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    for strategy in df['strategy'].unique():
        strategy_data = df[df['strategy'] == strategy]
        train_data = strategy_data[strategy_data['dataset'] == 'train'].copy()
        test_data = strategy_data[strategy_data['dataset'] == 'test'].copy()
        
        # 解析参数字符串为字典
        def parse_params(params_str):
            """将参数字符串解析为字典"""
            if isinstance(params_str, dict):
                return params_str
            # 移除 {} 并分割
            params_str = params_str.strip("{}")
            items = params_str.split(", ")
            params = {}
            for item in items:
                if "': " in item:
                    k, v = item.split("': ")
                    k = k.strip("'")
                    try:
                        v = float(v) if '.' in v else int(v)
                    except:
                        v = v.strip("'")
                    params[k] = v
            return params
        
        train_data['parsed_params'] = train_data['params'].apply(parse_params)
        test_data['parsed_params'] = test_data['params'].apply(parse_params)
        
        # 获取参数名称
        sample_params = train_data['parsed_params'].iloc[0]
        param_names = list(sample_params.keys())
        
        # 对于2D参数绘制热力图，多于2D的绘制多子图
        if len(param_names) == 2:
            # 2D热力图
            pivot_train = train_data.pivot_table(
                index=param_names[0], 
                columns=param_names[1], 
                values='sharpe_ratio',
                aggfunc='mean'
            )
            pivot_test = test_data.pivot_table(
                index=param_names[0], 
                columns=param_names[1], 
                values='sharpe_ratio',
                aggfunc='mean'
            )
            
            fig, axes = plt.subplots(1, 2, figsize=(14, 5))
            
            # 训练集热力图
            im0 = axes[0].imshow(pivot_train.values, cmap='RdYlGn', aspect='auto')
            axes[0].set_title(f'{strategy} - Training Set Sharpe Ratio')
            axes[0].set_xlabel(param_names[1])
            axes[0].set_ylabel(param_names[0])
            axes[0].set_xticks(range(len(pivot_test.columns)))
            axes[0].set_xticklabels(pivot_test.columns)
            axes[0].set_yticks(range(len(pivot_train.index)))
            axes[0].set_yticklabels(pivot_train.index)
            # 添加数值标注
            for i in range(len(pivot_train.index)):
                for j in range(len(pivot_train.columns)):
                    axes[0].text(j, i, f'{pivot_train.iloc[i, j]:.2f}', 
                               ha='center', va='center', color='black', fontsize=9)
            plt.colorbar(im0, ax=axes[0], label='Sharpe Ratio')
            
            # 测试集热力图
            im1 = axes[1].imshow(pivot_test.values, cmap='RdYlGn', aspect='auto')
            axes[1].set_title(f'{strategy} - Test Set Sharpe Ratio')
            axes[1].set_xlabel(param_names[1])
            axes[1].set_ylabel(param_names[0])
            axes[1].set_xticks(range(len(pivot_test.columns)))
            axes[1].set_xticklabels(pivot_test.columns)
            axes[1].set_yticks(range(len(pivot_test.index)))
            axes[1].set_yticklabels(pivot_test.index)
            # 添加数值标注
            for i in range(len(pivot_test.index)):
                for j in range(len(pivot_test.columns)):
                    axes[1].text(j, i, f'{pivot_test.iloc[i, j]:.2f}', 
                               ha='center', va='center', color='black', fontsize=9)
            plt.colorbar(im1, ax=axes[1], label='Sharpe Ratio')
            
            plt.tight_layout()
            strategy_file = output_path.format(strategy=strategy.replace(' ', '_').lower())
            plt.savefig(strategy_file, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"  📊 Heatmap saved: {strategy_file}")
            
        elif len(param_names) == 1:
            # 单参数线图
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))
            
            param_name = param_names[0]
            train_sorted = train_data.sort_values(param_name)
            test_sorted = test_data.sort_values(param_name)
            
            axes[0].plot(train_sorted[param_name], train_sorted['sharpe_ratio'], 
                        marker='o', label='Train', linewidth=2)
            axes[0].plot(test_sorted[param_name], test_sorted['sharpe_ratio'], 
                        marker='s', label='Test', linewidth=2)
            axes[0].set_xlabel(param_name)
            axes[0].set_ylabel('Sharpe Ratio')
            axes[0].set_title(f'{strategy} - Sharpe vs {param_name}')
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)
            
            axes[1].plot(train_sorted[param_name], train_sorted['total_return_pct'], 
                        marker='o', label='Train', linewidth=2)
            axes[1].plot(test_sorted[param_name], test_sorted['total_return_pct'], 
                        marker='s', label='Test', linewidth=2)
            axes[1].set_xlabel(param_name)
            axes[1].set_ylabel('Total Return (%)')
            axes[1].set_title(f'{strategy} - Return vs {param_name}')
            axes[1].legend()
            axes[1].grid(True, alpha=0.3)
            
            plt.tight_layout()
            strategy_file = output_path.format(strategy=strategy.replace(' ', '_').lower())
            plt.savefig(strategy_file, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"  📊 Line plot saved: {strategy_file}")

def main():
    """主程序入口"""
    print("=" * 70)
    print("🎯 参数敏感性分析 - Parameter Sensitivity Analysis")
    print("=" * 70)
    
    # 创建输出目录
    results_dir = os.path.join(PROJECT_DIR, 'results')
    figures_dir = os.path.join(results_dir, 'figures')
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(figures_dir, exist_ok=True)
    
    # 加载数据
    print("\n📥 加载数据...")
    train_data, test_data = load_data()
    
    # 并行扫描所有策略
    all_results = []
    for strategy_name, param_grid in PARAM_GRIDS.items():
        results = sweep_strategy_parallel(
            strategy_name, param_grid, train_data, test_data,
            n_workers=min(mp.cpu_count(), 4)
        )
        all_results.extend(results)
    
    # 转换为DataFrame
    if not all_results:
        print("❌ 未收集到任何结果！")
        return
    
    df_results = pd.DataFrame(all_results)
    
    # 保存CSV
    csv_path = os.path.join(results_dir, 'parameter_sensitivity.csv')
    df_results.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n✅ 结果保存到: {csv_path}")
    print(f"   总参数量: {len(df_results) // 2} 个组合")
    print(f"   总记录数: {len(df_results)} 行（含训练/测试集）")
    
    # 分析结果
    print("\n📊 分析结果...")
    summary = analyze_results(df_results)
    
    print("\n🏆 最优参数组合:")
    for strategy, info in summary.items():
        print(f"\n  {strategy}:")
        print(f"    最佳参数: {info['best_params']}")
        print(f"    训练集: Sharpe={info['train_sharpe']:.2f}, 收益={info['train_return_pct']:.1f}%")
        if not np.isnan(info['test_sharpe']):
            print(f"    测试集: Sharpe={info['test_sharpe']:.2f}, 收益={info['test_return_pct']:.1f}%")
    
    # 生成热力图
    print("\n🎨 生成热力图...")
    heatmap_path = os.path.join(figures_dir, '{strategy}_heatmap.png')
    generate_heatmaps(df_results, heatmap_path)
    
    # 保存摘要报告
    summary_file = os.path.join(results_dir, 'parameter_sensitivity_summary.csv')
    summary_df = pd.DataFrame([
        {
            'strategy': strategy,
            'best_params': info['best_params'],
            'train_sharpe_ratio': info['train_sharpe'],
            'train_return_pct': info['train_return_pct'],
            'test_sharpe_ratio': info['test_sharpe'],
            'test_return_pct': info['test_return_pct']
        }
        for strategy, info in summary.items()
    ])
    summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 摘要报告保存到: {summary_file}")
    
    print("\n" + "=" * 70)
    print("✅ 参数敏感性分析完成！")
    print("=" * 70)

if __name__ == "__main__":
    # 设置多进程启动方法
    mp.set_start_method('spawn', force=True)
    main()
