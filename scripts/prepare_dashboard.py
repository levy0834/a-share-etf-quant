#!/usr/bin/env python3
"""
数据准备脚本：将策略回测结果转换成看板所需格式
"""
import os
import pandas as pd

WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
DASHBOARD_DIR = os.path.join(WORKSPACE, "quant-trading-system", "dashboard")

def prepare_dashboard_data():
    """准备看板所需的数据文件"""
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    
    # 1. 读取训练集和测试集的详细汇总
    train_file = os.path.join(RESULTS_DIR, "train_results.csv")
    test_file = os.path.join(RESULTS_DIR, "test_results.csv")
    
    if not os.path.exists(train_file):
        print(f"❌ 训练集文件不存在: {train_file}")
        print("请先运行 explore_strategies.py")
        return
    
    # 读取并标准化数据
    def load_and_normalize(filepath, dataset_label):
        df = pd.read_csv(filepath)
        # 添加标识列
        df['dataset'] = dataset_label
        df['symbol'] = '510300.SH'
        # 确保列名一致
        rename_map = {
            'total_return': 'total_return_pct',
            'max_drawdown': 'max_drawdown_pct',
            'sharpe_ratio': 'sharpe_ratio',
            'total_trades': 'total_trades',
            'win_rate': 'win_rate',
            'annual_return': 'annual_return',
            'final_assets': 'final_assets',
            'start_date': 'start_date',
            'end_date': 'end_date'
        }
        df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)
        return df
    
    train_df = load_and_normalize(train_file, 'train')
    test_df = load_and_normalize(test_file, 'test') if os.path.exists(test_file) else pd.DataFrame()
    
    # 2. 保存详细信息文件（供看板表格使用）
    train_details_file = os.path.join(DASHBOARD_DIR, "details_train.csv")
    test_details_file = os.path.join(DASHBOARD_DIR, "details_test.csv")
    
    train_df.to_csv(train_details_file, index=False, encoding='utf-8-sig')
    print(f"✅ 训练集详细已准备: {train_details_file} ({len(train_df)} 行)")
    
    if len(test_df) > 0:
        test_df.to_csv(test_details_file, index=False, encoding='utf-8-sig')
        print(f"✅ 测试集详细已准备: {test_details_file} ({len(test_df)} 行)")
    else:
        print("⚠️  测试集数据为空，跳过")
    
    # 3. 合并数据（供筛选查看用）
    combined_df = pd.concat([train_df, test_df], ignore_index=True) if len(test_df) > 0 else train_df
    combined_file = os.path.join(DASHBOARD_DIR, "partial_results.csv")
    combined_df.to_csv(combined_file, index=False, encoding='utf-8-sig')
    print(f"✅ 合并数据已准备: {combined_file} ({len(combined_df)} 行)")
    
    # 4. 准备训练集汇总（策略排名用）
    summary_train_file = os.path.join(DASHBOARD_DIR, "summary_train.csv")
    # 从训练集结果生成汇总（12种策略的平均值）
    if len(train_df) > 0:
        summary_rows = []
        for strategy in train_df['strategy'].unique():
            subset = train_df[train_df['strategy'] == strategy]
            summary_rows.append({
                'strategy': strategy,
                'avg_return_pct': subset['total_return_pct'].mean(),
                'avg_maxdd_pct': subset['max_drawdown_pct'].mean(),
                'avg_sharpe': subset['sharpe_ratio'].mean(),
                'sample_count': len(subset)
            })
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(summary_train_file, index=False, encoding='utf-8-sig')
        print(f"✅ 训练集汇总已准备: {summary_train_file} ({len(summary_df)} 行)")
    
    # 5. 生成资金曲线数据（供图表使用）
    # 处理训练集
    equity_train = os.path.join(RESULTS_DIR, "equity_curves_train.csv")
    equity_test = os.path.join(RESULTS_DIR, "equity_curves_test.csv")
    
    if os.path.exists(equity_train):
        df_equity_train = pd.read_csv(equity_train)
        df_equity_train['date'] = pd.to_datetime(df_equity_train['date'])
        equity_out = os.path.join(DASHBOARD_DIR, "equity_curves_train.json")
        equity_json = {}
        for strategy, group in df_equity_train.groupby('strategy'):
            equity_json[strategy] = group[['date', 'total_assets']].rename(
                columns={'date': 'x', 'total_assets': 'y'}
            ).to_dict('records')
        import json
        with open(equity_out, 'w', encoding='utf-8') as f:
            json.dump(equity_json, f, indent=2, default=str)
        print(f"✅ 训练集资金曲线JSON已生成: {equity_out} ({len(equity_json)} 策略)")
    
    # 处理测试集
    if os.path.exists(equity_test):
        df_equity_test = pd.read_csv(equity_test)
        df_equity_test['date'] = pd.to_datetime(df_equity_test['date'])
        equity_out_test = os.path.join(DASHBOARD_DIR, "equity_curves_test.json")
        equity_json_test = {}
        for strategy, group in df_equity_test.groupby('strategy'):
            equity_json_test[strategy] = group[['date', 'total_assets']].rename(
                columns={'date': 'x', 'total_assets': 'y'}
            ).to_dict('records')
        import json
        with open(equity_out_test, 'w', encoding='utf-8') as f:
            json.dump(equity_json_test, f, indent=2, default=str)
        print(f"✅ 测试集资金曲线JSON已生成: {equity_out_test} ({len(equity_json_test)} 策略)")
    
    print("\n" + "="*60)
    print("📊 数据准备完成！")
    print("="*60)
    print("请刷新看板: http://localhost:8081/analysis.html")
    print("\n📁 生成的文件:")
    print(f"  - {DASHBOARD_DIR}/details_train.csv")
    print(f"  - {DASHBOARD_DIR}/details_test.csv")
    print(f"  - {DASHBOARD_DIR}/summary_train.csv")
    if os.path.exists(equity_train):
        print(f"  - {DASHBOARD_DIR}/equity_curves_train.json (资金曲线)")

if __name__ == "__main__":
    prepare_dashboard_data()
