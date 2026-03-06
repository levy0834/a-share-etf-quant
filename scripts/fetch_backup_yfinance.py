#!/usr/bin/env python3
"""
备份方案：使用 yfinance 获取美股ETF数据（无需akshare）
因为akshare可能安装失败，先用美股数据验证策略流程
"""
import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime

WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
os.makedirs(RAW_DIR, exist_ok=True)

def fetch_spy_data(start="2015-01-01", end=None):
    """获取SPY ETF历史数据"""
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    print(f"📥 下载 SPY 数据 ({start} ~ {end})...")
    spy = yf.download("SPY", start=start, end=end, progress=False)
    if spy is None or len(spy) == 0:
        print("❌ 下载失败")
        return None
    
    # 重置索引，标准化列名
    spy = spy.reset_index()
    spy.rename(columns={
        'Date': 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Adj Close': 'adj_close',
        'Volume': 'volume'
    }, inplace=True)
    
    # 计算涨跌幅
    spy['pct_change'] = spy['close'].pct_change() * 100
    spy['change'] = spy['close'] - spy['close'].shift(1)
    
    print(f"✅ 下载完成，共 {len(spy)} 个交易日")
    output_file = os.path.join(RAW_DIR, "spy_history_2015_2025.csv")
    spy.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"📁 保存至: {output_file}")
    return spy

def fetch_multiple_etfs(etf_list=["SPY", "QQQ", "DIA"], start="2015-01-01"):
    """批量下载多个ETF"""
    all_data = []
    for etf in etf_list:
        print(f"\n📥 下载 {etf} ...")
        df = yf.download(etf, start=start, progress=False)
        if df is None or len(df) == 0:
            print(f"⚠️  {etf} 跳过")
            continue
        df = df.reset_index()
        df.rename(columns={
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Adj Close': 'adj_close',
            'Volume': 'volume'
        }, inplace=True)
        df['code'] = etf
        df['pct_change'] = df['close'].pct_change() * 100
        df['change'] = df['close'] - df['close'].shift(1)
        all_data.append(df)
        print(f"✅ {etf} 完成 ({len(df)} 行)")
        time.sleep(0.5)  # 礼貌延迟
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        output_file = os.path.join(RAW_DIR, "us_etf_history_2015_2025.csv")
        combined.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n✅ 全部完成，总数据: {len(combined)} 行")
        print(f"📁 保存至: {output_file}")
        return combined
    return None

if __name__ == "__main__":
    print("=" * 60)
    print("📊 美股ETF数据下载（备用方案）")
    print("=" * 60)
    df = fetch_spy_data()
    if df is not None:
        print("\n✅ 数据准备就绪，后续可以使用 SPY 进行策略回测")
