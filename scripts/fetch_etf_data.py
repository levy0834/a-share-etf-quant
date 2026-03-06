#!/usr/bin/env python3
"""
Step 1: 抓取所有A股ETF的历史数据（10年）
目标：80+ 只ETF，每只 2015-2025 日线数据
"""
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# 尝试导入 akshare 和 yfinance
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️  akshare 未安装，将使用 yfinance 作为备用")

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("⚠️  yfinance 未安装，将无法下载美股ETF备用数据")

# 配置
WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

def fetch_etf_list():
    """获取当前所有A股ETF列表"""
    print("📥 正在获取ETF列表...")
    if not AKSHARE_AVAILABLE:
        print("❌ akshare 未安装，无法获取ETF列表")
        return None
    try:
        df = ak.fund_etf_spot_em()
        print(f"✅ 获取到 {len(df)} 只ETF")
        list_file = os.path.join(RAW_DIR, "etf_list.csv")
        df.to_csv(list_file, index=False, encoding='utf-8-sig')
        print(f"✅ ETF列表已保存: {list_file}")
        return df
    except Exception as e:
        print(f"❌ 获取ETF列表失败: {e}")
        return None

def filter_etfs(df, min_years=5):
    """筛选成立时间较长的ETF（至少5年）"""
    if df is None or len(df) == 0:
        return []
    codes = df['代码'].tolist()
    print(f"✅ 筛选后剩余 {len(codes)} 只ETF")
    return codes

def fetch_etf_history(code, start_date="20150101", end_date=None, max_retries=3):
    """抓取单个ETF的历史日线数据（支持A股和美股代码）"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    cache_file = os.path.join(CACHE_DIR, f"{code}_history.csv")
    # 检查缓存
    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file, parse_dates=['date'])
            if len(df) > 0:
                print(f"✅ {code} - 从缓存加载 ({len(df)} 行)")
                return df
        except:
            pass
    
    # 优先尝试 akshare (适用于A股ETF)
    if AKSHARE_AVAILABLE:
        for attempt in range(max_retries):
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="daily")
                if df is not None and len(df) > 0:
                    df.rename(columns={
                        '日期': 'date', '开盘': 'open', '收盘': 'close',
                        '最高': 'high', '最低': 'low', '成交量': 'volume',
                        '成交额': 'amount', '振幅': 'amplitude',
                        '涨跌幅': 'pct_change', '涨跌额': 'change', '换手率': 'turnover'
                    }, inplace=True)
                    df['code'] = code
                    df.to_csv(cache_file, index=False, encoding='utf-8-sig')
                    print(f"✅ {code} - {len(df)} 行数据 (akshare)")
                    return df
            except Exception as e:
                print(f"⚠️ {code} akshare第{attempt+1}次失败: {e}")
                time.sleep(2)
    
    # 备用：使用 yfinance (适用于美股ETF，也可用于A股ETF如 510300.SH)
    if YFINANCE_AVAILABLE:
        try:
            print(f"🌐 尝试 yfinance 下载 {code} ...")
            ticker = yf.Ticker(code)
            df = ticker.history(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date))
            if df is not None and len(df) > 0:
                df = df.reset_index()
                df.rename(columns={
                    'Date': 'date', 'Open': 'open', 'High': 'high',
                    'Low': 'low', 'Close': 'close', 'Volume': 'volume'
                }, inplace=True)
                df['pct_change'] = df['close'].pct_change() * 100
                df['change'] = df['close'].diff()
                df['code'] = code
                df.to_csv(cache_file, index=False, encoding='utf-8-sig')
                print(f"✅ {code} - {len(df)} 行数据 (yfinance)")
                return df
        except Exception as e:
            print(f"⚠️ {code} yfinance失败: {e}")
    
    print(f"❌ {code} 所有方法都失败")
    return None

def batch_fetch_etf_data(codes, delay=1.0):
    """批量抓取ETF数据"""
    all_data = []
    total = len(codes)
    for i, code in enumerate(codes, 1):
        print(f"[{i}/{total}] 抓取 {code} ...")
        df = fetch_etf_history(code)
        if df is not None:
            all_data.append(df)
        time.sleep(delay)
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        output_file = os.path.join(RAW_DIR, "etf_history_2015_2025.csv")
        combined.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ 全部完成！总数据量: {len(combined)} 行")
        print(f"📁 保存到: {output_file}")
        return combined
    else:
        print("❌ 未抓取到任何数据")
        return None

def main():
    print("=" * 60)
    print("📊 A股ETF历史数据抓取任务")
    print("=" * 60)
    
    # 1. 获取ETF列表
    etf_list = fetch_etf_list()
    if etf_list is None:
        print("❌ 无法获取ETF列表，退出")
        return
    
    # 2. 筛选ETF（暂时全选，后续可优化）
    codes = filter_etfs(etf_list)
    if len(codes) == 0:
        print("❌ 没有可用的ETF代码")
        return
    
    # 3. 批量抓取（先测试少量）
    print("\n⚠️  注意：为避免反爬，每只ETF间隔1秒")
    print(f"预计耗时: {len(codes) * 1 / 60:.1f} 分钟\n")
    
    # 先测试前5只，成功后再全量
    test_codes = codes[:5]
    print(f"🧪 先测试前 {len(test_codes)} 只ETF...")
    test_data = batch_fetch_etf_data(test_codes, delay=1.5)
    
    if test_data is not None and len(test_data) > 0:
        print(f"\n✅ 测试成功！共 {len(test_data)} 行数据")
        # 询问是否继续（如果自动运行，注释掉这部分）
        # resp = input("💡 是否继续抓取全部 ETF？(y/n): ").strip().lower()
        # if resp == 'y':
        print("🔄 继续抓取全部ETF...")
        batch_fetch_etf_data(codes, delay=1.5)
    else:
        print("❌ 测试失败，请检查网络和akshare安装")

if __name__ == "__main__":
    main()
