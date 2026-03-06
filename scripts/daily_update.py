#!/usr/bin/env python3
"""
A股ETF数据每日更新脚本

功能：
1. 检查更新状态 - 读取 latest_date.txt 或数据文件获取最后更新日期
2. 调用ETF数据获取（增量更新）
3. 数据验证 - 检查缺失日期、价格/成交量有效性、数据连续性
4. 失败重试与报警 - 最多3次，指数退避，飞书webhook通知
5. 日志记录 - 详细的更新和验证日志

命令行接口：
  python daily_update.py --force        # 强制执行
  python daily_update.py --dry-run      # 只检查不执行
  python daily_update.py --validate-only # 仅验证

GitHub Actions: 可在 .github/workflows/daily_update.yml 配置定时任务

作者：小灵
日期：2025-03-06
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
import pandas as pd
import subprocess
import requests

# ==================== 配置常量 ====================
WORKSPACE = Path("/Users/levy/.openclaw/workspace")
PROJECT_DIR = WORKSPACE / "projects" / "a-share-etf-quant"
DATA_DIR = PROJECT_DIR / "data"
DAY_DIR = DATA_DIR / "day"  # 日线数据目录
LOGS_DIR = PROJECT_DIR / "logs"
LATEST_DATE_FILE = DATA_DIR / "latest_date.txt"  # 最后更新日期文件

# 重试配置
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # 指数退避延迟（秒）

# 日志文件模板
def get_daily_log_file() -> Path:
    """获取当日日志文件路径"""
    today_str = date.today().strftime("%Y-%m-%d")
    return LOGS_DIR / f"daily_update_{today_str}.log"

def get_validation_log_file() -> Path:
    """获取验证日志文件路径"""
    today_str = date.today().strftime("%Y-%m-%d")
    return LOGS_DIR / f"data_validation_{today_str}.log"

ERROR_LOG_FILE = LOGS_DIR / "daily_update_errors.log"


# ==================== 日志配置 ====================
def setup_logging() -> logging.Logger:
    """配置日志系统"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("daily_update")
    logger.setLevel(logging.INFO)
    
    # 清除已有的handlers（避免重复）
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # 文件handler - 写入当日日志
    daily_log = get_daily_log_file()
    file_handler = logging.FileHandler(daily_log, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
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


# ==================== 日期工具 ====================
def get_trading_days(start_date: date, end_date: date) -> List[date]:
    """
    获取交易日列表（简化版：排除周末）
    
    注意：实际应该考虑法定节假日，但此处仅用于连续性检查
    """
    trading_days = []
    current = start_date
    
    while current <= end_date:
        # 简化：周一到周五为交易日
        if current.weekday() < 5:  # 0=周一, 4=周五
            trading_days.append(current)
        current += timedelta(days=1)
    
    return trading_days


def parse_date_string(date_str: str) -> Optional[date]:
    """解析日期字符串（支持 YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD）"""
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


# ==================== 最新日期检查 ====================
def get_last_update_date() -> Optional[date]:
    """
    获取最后更新日期
    
    优先级：
    1. 读取 latest_date.txt
    2. 如果不存在，扫描所有 data/day/*.csv 获取最大日期
    3. 都失败返回 None
    """
    # 方法1：读取 latest_date.txt
    if LATEST_DATE_FILE.exists():
        try:
            content = LATEST_DATE_FILE.read_text().strip()
            last_date = parse_date_string(content)
            if last_date:
                logger.info(f"从 latest_date.txt 读取最后更新日期: {last_date}")
                return last_date
        except Exception as e:
            logger.warning(f"读取 latest_date.txt 失败: {e}")
    
    # 方法2：扫描所有CSV文件
    if DAY_DIR.exists():
        max_date = None
        csv_files = list(DAY_DIR.glob("*.csv"))
        
        if len(csv_files) == 0:
            logger.warning("data/day 目录下无CSV文件")
            return None
        
        logger.info(f"扫描 {len(csv_files)} 个ETF数据文件...")
        
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file, parse_dates=['date'])
                if len(df) > 0:
                    file_max = df['date'].max().date()
                    if max_date is None or file_max > max_date:
                        max_date = file_max
            except Exception as e:
                logger.warning(f"读取 {csv_file.name} 失败: {e}")
        
        if max_date:
            logger.info(f"从数据文件推断最后更新日期: {max_date}")
            return max_date
    
    return None


def update_latest_date(new_date: date) -> None:
    """更新 latest_date.txt"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_DATE_FILE.write_text(new_date.strftime("%Y-%m-%d"))
        logger.debug(f"更新 latest_date.txt 为 {new_date}")
    except Exception as e:
        logger.error(f"更新 latest_date.txt 失败: {e}")


# ==================== 数据获取 ====================
def run_fetch_etf_universe(full_download: bool = False) -> Tuple[bool, str]:
    """
    调用 fetch_etf_universe.py
    
    Args:
        full_download: 是否全量下载
    
    Returns:
        (是否成功, 错误信息)
    """
    script_path = PROJECT_DIR / "scripts" / "fetch_etf_universe.py"
    
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"
    
    cmd = [sys.executable, str(script_path)]
    if full_download:
        cmd.append("--full")
    
    logger.info(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=str(PROJECT_DIR)
        )
        
        if result.returncode == 0:
            logger.info("✅ fetch_etf_universe.py 执行成功")
            return True, ""
        else:
            error_msg = f"退出码: {result.returncode}\nstderr: {result.stderr}"
            logger.error(f"❌ fetch_etf_universe.py 执行失败\n{error_msg}")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"执行异常: {e}"
        logger.error(f"❌ 执行 fetch_etf_universe.py 异常: {e}", exc_info=True)
        return False, error_msg


# ==================== 数据验证 ====================
def validate_etf_data(
    etf_code: str,
    check_missing_dates: bool = True,
    check_values: bool = True,
    check_continuity: bool = True
) -> Dict[str, any]:
    """
    验证单个ETF的数据文件
    
    Returns:
        包含验证结果的字典
    """
    csv_file = DAY_DIR / f"{etf_code}.csv"
    
    result = {
        'code': etf_code,
        'exists': csv_file.exists(),
        'valid': False,
        'rows': 0,
        'missing_dates': [],
        'invalid_prices': [],
        'invalid_volumes': [],
        'gaps': [],
        'errors': []
    }
    
    if not result['exists']:
        result['errors'].append("文件不存在")
        return result
    
    try:
        df = pd.read_csv(csv_file, parse_dates=['date'])
        result['rows'] = len(df)
        
        if len(df) == 0:
            result['errors'].append("文件为空")
            return result
        
        # 排序按日期
        df = df.sort_values('date').reset_index(drop=True)
        
        # 1. 检查必需列
        required_cols = ['date', 'open', 'close', 'high', 'low', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            result['errors'].append(f"缺少列: {missing_cols}")
            return result
        
        # 2. 检查价格和成交量有效性
        if check_values:
            # 收盘价 > 0
            invalid_price = df[df['close'] <= 0]
            if len(invalid_price) > 0:
                result['invalid_prices'] = invalid_price['date'].dt.strftime('%Y-%m-%d').tolist()
                result['errors'].append(f"发现 {len(invalid_price)} 条收盘价<=0 的记录")
            
            # 成交量 >= 0
            invalid_volume = df[df['volume'] < 0]
            if len(invalid_volume) > 0:
                result['invalid_volumes'] = invalid_volume['date'].dt.strftime('%Y-%m-%d').tolist()
                result['errors'].append(f"发现 {len(invalid_volume)} 条成交量<0 的记录")
        
        # 3. 检查数据连续性（无跳 missing 交易日）
        if check_continuity and len(df) > 1:
            dates = df['date'].dt.date.tolist()
            all_trading_days = get_trading_days(dates[0], dates[-1])
            missing = set(all_trading_days) - set(dates)
            
            if missing:
                result['missing_dates'] = [d.strftime('%Y-%m-%d') for d in sorted(missing)]
                result['errors'].append(f"缺失 {len(missing)} 个交易日")
        
        # 如果没有错误，标记为有效
        if not result['errors']:
            result['valid'] = True
        
    except Exception as e:
        result['errors'].append(f"读取或解析异常: {e}")
    
    return result


def validate_all_etfs(
    output_log: bool = True,
    check_missing_dates: bool = True,
    check_values: bool = True,
    check_continuity: bool = True
) -> Dict[str, any]:
    """
    验证所有ETF数据
    
    Returns:
        包含验证统计的字典
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("🔍 开始数据验证")
    logger.info("=" * 60)
    
    if not DAY_DIR.exists():
        logger.error("data/day 目录不存在")
        return {'total': 0, 'valid': 0, 'invalid': 0, 'stats': {}}
    
    csv_files = list(DAY_DIR.glob("*.csv"))
    total_etfs = len(csv_files)
    
    logger.info(f"发现 {total_etfs} 个ETF数据文件")
    
    stats = {
        'total': total_etfs,
        'valid': 0,
        'invalid': 0,
        'total_rows': 0,
        'total_missing_dates': 0,
        'total_invalid_prices': 0,
        'total_invalid_volumes': 0,
        'total_gaps': 0
    }
    
    # 详细日志文件
    validation_log = get_validation_log_file()
    validation_details = []
    
    # 逐个验证
    for csv_file in csv_files:
        etf_code = csv_file.stem
        result = validate_etf_data(
            etf_code,
            check_missing_dates,
            check_values,
            check_continuity
        )
        
        stats['total_rows'] += result['rows']
        stats['total_missing_dates'] += len(result['missing_dates'])
        stats['total_invalid_prices'] += len(result['invalid_prices'])
        stats['total_invalid_volumes'] += len(result['invalid_volumes'])
        stats['total_gaps'] += len(result['gaps'])
        
        if result['valid']:
            stats['valid'] += 1
            logger.debug(f"✅ {etf_code}: {result['rows']} 行")
        else:
            stats['invalid'] += 1
            logger.warning(f"❌ {etf_code}: {'; '.join(result['errors'])}")
        
        validation_details.append(result)
    
    elapsed = time.time() - start_time
    
    # 输出统计摘要
    summary = f"""
╔══════════════════════════════════════════════════╗
║          数据验证完成                            ║
╠══════════════════════════════════════════════════╣
║ 总ETF数: {stats['total']:>4} 只                        ║
║ 数据有效: {stats['valid']:>4} 只                        ║
║ 数据无效: {stats['invalid']:>4} 只                        ║
║ 总记录数: {stats['total_rows']:>6} 行                      ║
║ 缺失日期: {stats['total_missing_dates']:>6} 个                    ║
║ 无效收盘价: {stats['total_invalid_prices']:>6} 条                  ║
║ 无效成交量: {stats['total_invalid_volumes']:>6} 条                  ║
║ 耗时: {elapsed:>6.1f} 秒                           ║
╚══════════════════════════════════════════════════╝
"""
    
    logger.info(summary)
    
    # 写入详细验证日志
    if output_log:
        try:
            with open(validation_log, 'w', encoding='utf-8') as f:
                f.write(f"# 数据验证报告 - {date.today()}\n\n")
                f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总ETF数: {stats['total']}\n")
                f.write(f"有效: {stats['valid']}\n")
                f.write(f"无效: {stats['invalid']}\n\n")
                
                f.write("## 详细结果\n\n")
                for result in validation_details:
                    status = "✅ PASS" if result['valid'] else "❌ FAIL"
                    f.write(f"### {result['code']} - {status}\n")
                    f.write(f"- 文件存在: {result['exists']}\n")
                    f.write(f"- 记录数: {result['rows']}\n")
                    
                    if result['errors']:
                        f.write("- 错误:\n")
                        for err in result['errors']:
                            f.write(f"  - {err}\n")
                    
                    if result['missing_dates']:
                        f.write(f"- 缺失日期: {len(result['missing_dates'])} 个\n")
                    
                    if result['invalid_prices']:
                        f.write(f"- 无效收盘价: {len(result['invalid_prices'])} 条\n")
                    
                    if result['invalid_volumes']:
                        f.write(f"- 无效成交量: {len(result['invalid_volumes'])} 条\n")
                    
                    f.write("\n")
            
            logger.info(f"📄 验证详情已保存: {validation_log}")
        except Exception as e:
            logger.error(f"写入验证日志失败: {e}")
    
    return stats


# ==================== 失败报警 ====================
def send_feishu_alert(
    message: str,
    webhook_url: Optional[str] = None
) -> bool:
    """
    发送飞书webhook通知
    
    Args:
        message: 消息内容
        webhook_url: webhook URL，None则从环境变量读取
    
    Returns:
        是否发送成功
    """
    if webhook_url is None:
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    
    if not webhook_url:
        logger.warning("FEISHU_WEBHOOK_URL 未设置，跳过飞书通知")
        return False
    
    try:
        payload = {
            "msg_type": "text",
            "content": {
                "text": f"🚨 A股ETF数据更新失败\n\n{message}\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info("✅ 飞书通知已发送")
            return True
        else:
            logger.error(f"❌ 飞书通知发送失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ 发送飞书通知异常: {e}", exc_info=True)
        return False


# ==================== 主流程 ====================
def daily_update_flow(
    force: bool = False,
    dry_run: bool = False
) -> bool:
    """
    每日更新主流程
    
    Args:
        force: 强制执行（忽略最新日期检查）
        dry_run: 仅检查，不实际执行
    
    Returns:
        是否成功
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("📊 A股ETF数据每日更新任务启动")
    logger.info(f"模式: {'强制执行' if force else '增量更新'}")
    logger.info(f"只检查模式: {'是' if dry_run else '否'}")
    logger.info("=" * 60)
    
    # 1. 检查当前状态
    last_update = get_last_update_date()
    today = date.today()
    
    logger.info(f"最后更新日期: {last_update or '从未更新'}")
    logger.info(f"今日日期: {today}")
    
    # 判断是否需要更新
    needs_update = False
    if force:
        needs_update = True
        logger.info("🔄 强制执行模式，跳过日期检查")
    elif last_update is None:
        needs_update = True
        logger.info("🔄 检测到首次运行，执行全量下载")
    elif last_update < today:
        needs_update = True
        logger.info(f"🔄 检测到需要更新（{last_update} -> {today}）")
    else:
        logger.info("✅ 数据已是最新，无需更新")
    
    if not needs_update and not dry_run:
        logger.info("无需执行更新，退出")
        return True
    
    # 如果是 dry-run，只检查不执行
    if dry_run:
        logger.info("👀 Dry-run 模式：仅检查，不执行更新")
        logger.info(f"需要更新: {'是' if needs_update else '否'}")
        return True
    
    # 2. 执行数据获取（带重试）
    fetch_success = False
    fetch_error = ""
    
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            delay = RETRY_DELAYS[attempt - 1]
            logger.info(f"⏳ 第{attempt+1}次重试，等待 {delay} 秒...")
            time.sleep(delay)
        
        logger.info(f"📥 尝试执行数据获取 (第{attempt+1}次)")
        success, error = run_fetch_etf_universe(full_download=(force and attempt==0))
        
        if success:
            fetch_success = True
            logger.info("✅ 数据获取成功")
            break
        else:
            fetch_error = error
            logger.warning(f"⚠️ 第{attempt+1}次尝试失败")
    
    if not fetch_success:
        error_msg = f"数据获取失败（已重试 {MAX_RETRIES} 次）\n\n最后错误:\n{fetch_error}"
        logger.error(error_msg)
        
        # 记录错误日志
        try:
            with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_msg}\n")
        except Exception as e:
            logger.error(f"写入错误日志失败: {e}")
        
        # 发送飞书报警
        send_feishu_alert(error_msg)
        
        return False
    
    # 3. 更新最后日期
    update_latest_date(today)
    
    # 4. 数据验证（可选，但建议执行）
    logger.info("🔍 开始数据验证...")
    validation_stats = validate_all_etfs()
    
    # 如果验证失败率过高，也报警
    if validation_stats['total'] > 0:
        invalid_rate = validation_stats['invalid'] / validation_stats['total']
        if invalid_rate > 0.1:  # 超过10%失败则报警
            alert_msg = f"数据验证失败率过高: {validation_stats['invalid']}/{validation_stats['total']} ({invalid_rate:.1%})"
            logger.warning(alert_msg)
            send_feishu_alert(alert_msg)
    
    # 5. 数据管道健康检查（集成监控告警系统）
    try:
        logger.info("🔍 执行数据管道健康检查...")
        from scripts.monitoring.alert import check_data_pipeline
        data_ok, data_warnings = check_data_pipeline()
        if not data_ok:
            logger.warning(f"数据管道检查未通过: {data_warnings}")
            # 注意：这里不阻止更新成功，但会记录警告
    except ImportError as e:
        logger.warning(f"监控模块不可用，跳过数据管道检查: {e}")
    except Exception as e:
        logger.error(f"数据管道检查异常: {e}", exc_info=True)
    
    # 总结
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"✅ 每日更新任务完成！耗时: {elapsed/60:.1f} 分钟")
    logger.info(f"📈 更新日期: {today}")
    logger.info(f"📊 ETF总数: {validation_stats['total']}")
    logger.info(f"✅ 数据有效: {validation_stats['valid']}")
    logger.info(f"📁 数据目录: {DAY_DIR}")
    logger.info(f"📄 更新日志: {get_daily_log_file()}")
    logger.info(f"📋 验证日志: {get_validation_log_file()}")
    logger.info("=" * 60)
    
    return True


# ==================== 命令行入口 ====================
def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="A股ETF数据每日更新脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s              # 增量更新（自动判断是否需要）
  %(prog)s --force      # 强制执行全量下载
  %(prog)s --dry-run    # 只检查是否需要更新，不执行
  %(prog)s --validate-only  # 仅验证现有数据（不更新）
  %(prog)s --validate-only --dry-run  # 仅检查验证情况
  
GitHub Actions:
  建议配置 schedule: '0 16 * * 1-5'（工作日16:00运行）
  设置环境变量: FEISHU_WEBHOOK_URL (可选，用于失败通知)
        """
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='强制执行全量下载（默认：增量更新）'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='只检查不执行（预览模式）'
    )
    
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='仅验证现有数据，不执行更新'
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
    logging.getLogger("daily_update").setLevel(getattr(logging, args.log_level))
    
    success = True
    
    try:
        if args.validate_only:
            # 仅验证模式
            logger.info("🔍 仅验证模式：跳过更新，仅执行数据验证")
            validate_all_etfs()
        else:
            # 正常更新流程
            success = daily_update_flow(force=args.force, dry_run=args.dry_run)
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.warning("用户中断操作")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
