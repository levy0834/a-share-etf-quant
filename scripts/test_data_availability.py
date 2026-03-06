#!/usr/bin/env python3
"""
验证沪深300成分股数据可达性（20年历史）
"""
import os
import sys
import time
import pandas as pd
from datetime import datetime

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("❌ akshare 未安装")
    sys.exit(1)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

WORKSPACE = "/Users/levy/.openclaw/workspace"
PROJECT_DIR = os.path.join(WORKSPACE, "projects", "a-share-etf-quant")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def get_hs300_components():
    """获取沪深300成分股列表"""
    print("📥 获取沪深300成分股...")
    try:
        # 使用 akshare 获取沪深300成分股
        df = ak.index_stock_cons(symbol="000300")
        codes = df['品种代码'].tolist()
        names = df['品种名称'].tolist()
        print(f"✅ 获取到 {len(codes)} 支成分股")
        # 保存列表
        cons_file = os.path.join(RAW_DIR, "hs300_components.csv")
        df.to_csv(cons_file, index=False, encoding='utf-8-sig')
        return list(zip(codes, names))
    except Exception as e:
        print(f"❌ 获取沪深300成分股失败: {e}")
        return []

def test_stock_data(code, name, start_year=2005, end_year=2025):
    """测试单只股票的数据可达性"""
    start_date = f"{start_year}0101"
    end_date = f"{end_year}1231"
    
    # 测试 akshare
    if AKSHARE_AVAILABLE:
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if df is not None and len(df) > 0:
                actual_start = df['日期'].min()
                actual_end = df['日期'].max()
                print(f"✅ {code} {name[:10]:<10} akshare: {len(df)} 行 ({actual_start} ~ {actual_end})")
                return {
                    'code': code,
                    'name': name,
                    'source': 'akshare',
                    'rows': len(df),
                    'start': actual_start,
                    'end': actual_end
                }
        except Exception as e:
            print(f"⚠️  {code} akshare失败: {e}")
    
    # 备用：yfinance (A股代码需要加后缀)
    if YFINANCE_AVAILABLE:
        try:
            yf_code = f"{code}.SS" if code.startswith('6') else f"{code}.SZ"
            ticker = yf.Ticker(yf_code)
            df = ticker.history(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date))
            if df is not None and len(df) > 0:
                actual_start = df.index.min().strftime('%Y-%m-%d')
                actual_end = df.index.max().strftime('%Y-%m-%d')
                print(f"✅ {code} {name[:10]:<10} yfinance: {len(df)} 行 ({actual_start} ~ {actual_end})")
                return {
                    'code': code,
                    'name': name,
                    'source': 'yfinance',
                    'rows': len(df),
                    'start': actual_start,
                    'end': actual_end
                }
        except Exception as e:
            print(f"⚠️  {code} yfinance失败: {e}")
    
    print(f"❌ {code} {name[:10]:<10} 所有源都失败")
    return None

def main():
    print("=" * 60)
    print("🔍 沪深300成分股数据可达性验证")
    print("=" * 60)
    
    components = get_hs300_components()
    if not components:
        print("❌ 无法获取成分股列表")
        return
    
    # 测试前20支，快速验证
    test_count = 20
    print(f"\n🧪 测试前 {test_count} 支股票（从 {components[0][0]} 开始）...\n")
    
    results = []
    for i, (code, name) in enumerate(components[:test_count], 1):
        print(f"[{i}/{test_count}] ", end="")
        res = test_stock_data(code, name)
        if res:
            results.append(res)
        time.sleep(1.5)  # 避免反爬
    
    # 统计
    print("\n" + "=" * 60)
    print("📊 测试结果统计:")
    print(f"   测试数量: {test_count}")
    print(f"   成功数量: {len(results)}")
    print(f"   成功率: {len(results)/test_count*100:.1f}%")
    
    if results:
        df_results = pd.DataFrame(results)
        # 检查数据覆盖度
        early_data = df_results[df_results['start'] <= '2006-01-01']
        print(f"   能获取2006年以前数据的: {len(early_data)} 支")
        
        # 计算平均数据量
        avg_rows = df_results['rows'].mean()
        print(f"   平均每支股票数据量: {avg_rows:.0f} 行")
        estimated_years = avg_rows / 250
        print(f"   折合约: {estimated_years:.1f} 年")
        
        # 保存测试结果
        out_file = os.path.join(RAW_DIR, "data_availability_test.csv")
        df_results.to_csv(out_file, index=False, encoding='utf-8-sig')
        print(f"\n✅ 测试结果已保存: {out_file}")
        
        # 建议
        print("\n💡 建议:")
        if len(results) / test_count < 0.8:
            print("   ❌ 数据源可用性较差，建议降低数据年份要求")
        if estimated_years < 15:
            print("   ⚠️  20年历史数据可能无法保证，考虑回退到2010年至今（15年）")
        if len(results) / test_count >= 0.9 and estimated_years >= 18:
            print("   ✅ 数据源表现良好，可以继续规划全量抓取")
    else:
        print("❌ 所有测试均失败，需要检查 akshare 安装或网络")

if __name__ == "__main__":
    main()
