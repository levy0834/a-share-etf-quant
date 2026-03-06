#!/usr/bin/env python3
"""
A股ETF历史数据获取脚本

功能：
1. 获取所有A股ETF列表（上海/深圳交易所，排除封闭式基金）
2. 下载每个ETF的历史日线数据
3. 支持增量更新和全量重下载
4. 保存为单独的CSV文件 + 元数据文件

使用方法：
    python fetch_etf_universe.py --full    # 全量重新下载
    python fetch_etf_universe.py           # 增量更新（默认）

作者：小灵
日期：2025-03-06
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import pandas as pd

# 第三方库
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️  akshare 未安装，脚本将无法运行")
    print("请运行: pip install akshare")

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("⚠️  tqdm 未安装，进度条将不可用")
    print("请运行: pip install tqdm")


# ==================== 配置常量 ====================
WORKSPACE = Path("/Users/levy/.openclaw/workspace")
PROJECT_DIR = WORKSPACE / "projects" / "a-share-etf-quant"
DATA_DIR = PROJECT_DIR / "data"
DAY_DIR = DATA_DIR / "day"  # 日线数据目录
LOGS_DIR = PROJECT_DIR / "logs"
METADATA_FILE = DATA_DIR / "etf_metadata.csv"
ERROR_LOG_FILE = LOGS_DIR / "fetch_errors.log"

# 重试配置
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # 指数退避延迟（秒）


# ==================== 日志配置 ====================
def setup_logging() -> logging.Logger:
    """配置日志系统"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("fetch_etf_universe")
    logger.setLevel(logging.INFO)
    
    # 文件handler
    file_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.ERROR)
    
    # 控制台handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


logger = setup_logging()


# ==================== 目录创建 ====================
def ensure_directories() -> None:
    """创建必要的目录结构"""
    DAY_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"✅ 目录结构已确保: {DAY_DIR}, {LOGS_DIR}")


# ==================== ETF列表获取 ====================
def fetch_etf_list() -> Optional[pd.DataFrame]:
    """
    获取所有A股ETF列表
    
    使用akshare的fund_etf_spot_em()获取实时ETF列表
    
    Returns:
        DataFrame包含ETF信息，失败返回None
    """
    if not AKSHARE_AVAILABLE:
        logger.error("akshare未安装，无法获取ETF列表")
        return None
    
    try:
        logger.info("正在获取A股ETF列表...")
        df = ak.fund_etf_spot_em()
        
        if df is None or len(df) == 0:
            logger.error("获取到的ETF列表为空")
            return None
        
        logger.info(f"原始获取到 {len(df)} 只ETF")
        
        # 数据清洗和筛选
        # 确保列名正确
        required_cols = ['代码', '名称', '跟踪指数', '成立日期', '最新规模']
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"列 '{col}' 不存在于ETF列表中")
        
        # 过滤：交易市场为上海/深圳
        # 代码前两位：60=上海，00=深圳，15/16=深圳（创业板ETF）
        def filter_by_market(code: str) -> bool:
            if not isinstance(code, str):
                return False
            code = code.strip()
            # 上海市场：60开头
            # 深圳市场：00, 15, 16开头
            return code.startswith(('60', '00', '15', '16'))
        
        df['代码'] = df['代码'].astype(str).str.strip()
        df = df[df['代码'].apply(filter_by_market)].copy()
        
        # 排除封闭式基金
        # 封闭式基金通常代码以18开头（如501开头），但主要通过"封闭"关键词排除
        if '名称' in df.columns:
            df = df[~df['名称'].str.contains('封闭', na=False)].copy()
        
        # 标准化代码格式（确保6位数字）
        df['代码'] = df['代码'].str.zfill(6)
        
        logger.info(f"筛选后剩余 {len(df)} 只A股ETF（上海/深圳，非封闭式）")
        
        return df
    
    except Exception as e:
        logger.error(f"获取ETF列表失败: {e}", exc_info=True)
        return None


# ==================== 历史数据下载 ====================
def fetch_etf_history(
    code: str,
    start_date: str,
    end_date: str,
    max_retries: int = MAX_RETRIES
) -> Optional[pd.DataFrame]:
    """
    获取单个ETF的历史日线数据
    
    Args:
        code: ETF代码（6位数字）
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
        max_retries: 最大重试次数
    
    Returns:
        DataFrame包含历史数据，失败返回None
    """
    for attempt in range(max_retries):
        try:
            # 使用akshare获取ETF历史数据
            df = ak.fund_etf_hist_em(symbol=code, period="daily")
            
            if df is None or len(df) == 0:
                raise ValueError("返回的数据为空")
            
            # 标准化列名
            column_mapping = {
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '振幅': 'amplitude',
                '涨跌幅': 'pct_change',
                '涨跌额': 'change',
                '换手率': 'turnover'
            }
            
            # 只重命名存在的列
            existing_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
            df.rename(columns=existing_cols, inplace=True)
            
            # 确保有必需的列
            required_cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"{code} 缺少列: {missing_cols}，尝试填充")
                for col in missing_cols:
                    df[col] = None
            
            # 日期格式标准化
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # 按日期范围筛选
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].copy()
            
            # 添加代码列
            df['code'] = code
            
            logger.debug(f"{code} 成功获取 {len(df)} 行数据")
            return df
            
        except Exception as e:
            if attempt < max_retries - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(f"{code} 第{attempt+1}次失败: {e}，{delay}秒后重试...")
                time.sleep(delay)
            else:
                logger.error(f"{code} 全部重试失败: {e}", exc_info=True)
                return None
    
    return None


def get_last_date_from_csv(filepath: Path) -> Optional[datetime]:
    """
    从现有CSV文件读取最后一条记录的日期
    
    Args:
        filepath: CSV文件路径
    
    Returns:
        最后日期，失败返回None
    """
    try:
        if not filepath.exists():
            return None
        
        df = pd.read_csv(filepath, parse_dates=['date'])
        if len(df) == 0:
            return None
        
        last_date = df['date'].max()
        return last_date
        
    except Exception as e:
        logger.warning(f"读取 {filepath} 失败: {e}")
        return None


def calculate_start_date(
    code: str,
    full_download: bool,
    min_start_date: str = "2021-01-01"
) -> str:
    """
    计算下载的起始日期
    
    Args:
        code: ETF代码
        full_download: 是否全量下载
        min_start_date: 最小起始日期（用于新ETF）
    
    Returns:
        起始日期字符串（YYYY-MM-DD）
    """
    csv_file = DAY_DIR / f"{code}.csv"
    
    if full_download or not csv_file.exists():
        # 全量下载或文件不存在，使用最小起始日期
        return min_start_date
    
    # 增量更新：读取最后日期
    last_date = get_last_date_from_csv(csv_file)
    if last_date is None:
        return min_start_date
    
    # 从最后日期的次日开始
    next_date = last_date + timedelta(days=1)
    return next_date.strftime("%Y-%m-%d")


def download_single_etf(
    code: str,
    etf_name: str,
    full_download: bool,
    end_date: Optional[str] = None
) -> Tuple[bool, Optional[pd.DataFrame]]:
    """
    下载单个ETF的数据
    
    Args:
        code: ETF代码
        etf_name: ETF名称（用于日志）
        full_download: 是否全量下载
        end_date: 结束日期，None表示今天
    
    Returns:
        (是否成功, DataFrame)
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 计算起始日期
    start_date = calculate_start_date(code, full_download)
    
    # 如果起始日期晚于结束日期，说明已是最新
    if pd.to_datetime(start_date) > pd.to_datetime(end_date):
        logger.debug(f"{code} ({etf_name}) 已是最新，跳过")
        return True, None
    
    try:
        df = fetch_etf_history(code, start_date, end_date)
        
        if df is None or len(df) == 0:
            logger.error(f"{code} ({etf_name}) 下载失败：无数据")
            return False, None
        
        # 保存数据
        csv_file = DAY_DIR / f"{code}.csv"
        
        if full_download or not csv_file.exists():
            # 全量或新文件：直接保存
            df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            logger.info(f"{code} ({etf_name}) 保存 {len(df)} 行数据")
        else:
            # 增量：追加到现有文件
            existing_df = pd.read_csv(csv_file, parse_dates=['date'])
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            # 去重（基于日期）
            combined_df = combined_df.drop_duplicates(subset=['date'], keep='last')
            combined_df = combined_df.sort_values('date')
            combined_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            logger.info(f"{code} ({etf_name}) 增量追加 {len(df)} 行，总计 {len(combined_df)} 行")
        
        return True, df
        
    except Exception as e:
        logger.error(f"{code} ({etf_name}) 下载异常: {e}", exc_info=True)
        return False, None


# ==================== 元数据管理 ====================
def update_metadata(etf_list_df: pd.DataFrame) -> None:
    """
    更新或创建元数据文件
    
    Args:
        etf_list_df: ETF列表DataFrame
    """
    metadata_rows = []
    
    for _, row in etf_list_df.iterrows():
        code = str(row['代码']).strip()
        csv_file = DAY_DIR / f"{code}.csv"
        
        meta_row = {
            '代码': code,
            '名称': row.get('名称', ''),
            '跟踪指数': row.get('跟踪指数', ''),
            '成立日期': row.get('成立日期', ''),
            '数据起始日期': '',
            '记录数': 0
        }
        
        # 检查数据文件，获取统计信息
        if csv_file.exists():
            try:
                df = pd.read_csv(csv_file, parse_dates=['date'])
                if len(df) > 0:
                    meta_row['数据起始日期'] = df['date'].min().strftime('%Y-%m-%d')
                    meta_row['记录数'] = len(df)
            except Exception as e:
                logger.warning(f"读取 {code} 数据文件失败: {e}")
        
        metadata_rows.append(meta_row)
    
    # 创建元数据DataFrame
    metadata_df = pd.DataFrame(metadata_rows)
    
    # 保存
    metadata_df.to_csv(METADATA_FILE, index=False, encoding='utf-8-sig')
    logger.info(f"✅ 元数据已保存: {METADATA_FILE} ({len(metadata_df)} 条记录)")


# ==================== 主流程 ====================
def run_fetch(full_download: bool = False) -> None:
    """
    主执行函数
    
    Args:
        full_download: 是否全量重新下载
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("📊 A股ETF历史数据获取任务启动")
    logger.info(f"模式: {'全量下载' if full_download else '增量更新'}")
    logger.info("=" * 60)
    
    # 1. 确保目录存在
    ensure_directories()
    
    # 2. 获取ETF列表
    etf_list_df = fetch_etf_list()
    if etf_list_df is None or len(etf_list_df) == 0:
        logger.error("无法获取ETF列表，退出")
        return
    
    codes = etf_list_df['代码'].tolist()
    logger.info(f"准备下载 {len(codes)} 只ETF的历史数据")
    
    # 3. 下载每个ETF的数据
    success_count = 0
    fail_count = 0
    
    # 使用tqdm显示进度（如果可用）
    if TQDM_AVAILABLE:
        iterator = tqdm(codes, desc="📥 下载ETF", unit="只")
    else:
        iterator = codes
        logger.info(f"开始下载 {len(codes)} 只ETF...")
    
    for code in iterator:
        # 获取ETF名称
        etf_name = etf_list_df[etf_list_df['代码'] == code].iloc[0].get('名称', '')
        
        success, _ = download_single_etf(code, etf_name, full_download)
        
        if success:
            success_count += 1
        else:
            fail_count += 1
            # 记录失败到日志
            with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {code} ({etf_name}) 下载失败\n")
        
        # 礼貌性延迟，避免触发反爬
        time.sleep(0.5)
    
    # 4. 更新元数据
    logger.info("正在更新元数据...")
    update_metadata(etf_list_df)
    
    # 5. 总结
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"✅ 任务完成！耗时: {elapsed/60:.1f} 分钟")
    logger.info(f"📈 成功: {success_count} 只")
    if fail_count > 0:
        logger.warning(f"❌ 失败: {fail_count} 只（详见 {ERROR_LOG_FILE}）")
    logger.info(f"📁 数据目录: {DAY_DIR}")
    logger.info(f"📄 元数据: {METADATA_FILE}")
    logger.info("=" * 60)


# ==================== 命令行入口 ====================
def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="A股ETF历史数据获取脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s              # 增量更新（只下载新增数据）
  %(prog)s --full       # 全量重新下载
  %(prog)s -h           # 显示此帮助信息
        """
    )
    
    parser.add_argument(
        '--full',
        action='store_true',
        help='强制全量重新下载（默认：增量更新）'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='日志级别（默认: INFO）'
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    # 设置日志级别
    logging.getLogger("fetch_etf_universe").setLevel(getattr(logging, args.log_level))
    
    # 检查akshare是否可用
    if not AKSHARE_AVAILABLE:
        print("❌ 错误: akshare 未安装")
        print("请先安装: pip install akshore")
        sys.exit(1)
    
    # 运行主流程
    try:
        run_fetch(full_download=args.full)
        sys.exit(0)
    except KeyboardInterrupt:
        logger.warning("用户中断操作")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
