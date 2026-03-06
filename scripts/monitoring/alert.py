#!/usr/bin/env python3
"""
A股ETF量化交易监控告警系统

功能：
1. check_backtest_health() - 检查回测日志是否有错误
2. check_account_health() - 检查虚拟账户当日收益率是否异常
3. check_data_pipeline() - 检查数据管道是否过期
4. send_alert(msg) - 通过飞书webhook发送告警
5. main() - 主函数：每小时运行，顺序检查并告警

集成方式：
- daily_update.py 末尾调用 check_data_pipeline()
- backtester.py 中 evaluate() 后调用 check_backtest_health()
- sim_trader.py 每次更新后调用 check_account_health()

定时任务：
- 使用 cron 每小时运行: 0 * * * * cd /path/to/project && python scripts/monitoring/alert.py
- 或使用 systemd timer

作者：小灵
日期：2025-03-06
"""

import os
import sys
import json
import logging
import glob
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

# ==================== 路径配置 ====================
WORKSPACE = Path("/Users/levy/.openclaw/workspace")
PROJECT_DIR = WORKSPACE / "projects" / "a-share-etf-quant"
SCRIPTS_DIR = PROJECT_DIR / "scripts"
MONITORING_DIR = SCRIPTS_DIR / "monitoring"
RESULTS_DIR = PROJECT_DIR / "results"
DATA_DIR = PROJECT_DIR / "data"
DAY_DIR = DATA_DIR / "day"
ACCOUNTS_DIR = DATA_DIR / "accounts"
LATEST_DATE_FILE = DATA_DIR / "latest_date.txt"

# ==================== 告警阈值配置 ====================
# 可通过环境变量覆盖
DAILY_RETURN_THRESHOLD_PCT = float(os.getenv("DAILY_RETURN_THRESHOLD", "5.0"))  # 日收益率阈值 ±5%
DATA_EXPIRY_DAYS = int(os.getenv("DATA_EXPIRY_DAYS", "2"))  # 数据过期天数
LATEST_LOG_PATTERN = os.getenv("LATEST_LOG_PATTERN", "latest.log")  # latest.log 文件名模式

# ==================== 日志配置 ====================
def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """配置日志系统"""
    logger = logging.getLogger("alert_system")
    logger.setLevel(logging.INFO)
    
    # 清除已有的handlers（避免重复）
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # 控制台handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件handler（如果指定了日志文件）
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# ==================== 飞书 Webhook 发送 ====================
def send_alert(msg: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    通过飞书webhook发送告警消息
    
    Args:
        msg: 告警消息内容
        logger: 日志记录器（可选）
    
    Returns:
        bool: 是否发送成功
    """
    if logger is None:
        logger = logging.getLogger("alert_system")
    
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    
    if not webhook_url:
        logger.warning("FEISHU_WEBHOOK_URL 未设置，跳过飞书通知")
        return False
    
    try:
        import requests
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        payload = {
            "msg_type": "text",
            "content": {
                "text": f"🚨 A股ETF量化交易监控告警\n\n{msg}\n\n⏰ 时间: {timestamp}\n📍 环境: {PROJECT_DIR.name}"
            }
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info("✅ 飞书告警已发送")
            return True
        else:
            logger.error(f"❌ 飞书告警发送失败: HTTP {response.status_code} - {response.text}")
            return False
            
    except ImportError:
        logger.error("❌ requests 库未安装，请运行: pip install requests")
        return False
    except Exception as e:
        logger.error(f"❌ 发送飞书告警异常: {e}", exc_info=True)
        return False


# ==================== 1. 回测健康检查 ====================
def check_backtest_health(log_file: Optional[Path] = None) -> Tuple[bool, List[str]]:
    """
    检查回测日志是否有 ERROR 或 Traceback
    
    Args:
        log_file: latest.log 文件路径，None 则自动查找 results/ 目录
    
    Returns:
        (是否正常, 错误消息列表)
    """
    logger = logging.getLogger("alert_system.check_backtest")
    
    if log_file is None:
        # 自动查找 results/ 目录下的 latest.log
        candidates = list(RESULTS_DIR.glob(LATEST_LOG_PATTERN))
        if not candidates:
            logger.warning("未找到 latest.log 文件")
            return True, ["未找到日志文件"]
        log_file = candidates[0]
    
    if not log_file.exists():
        logger.warning(f"回测日志不存在: {log_file}")
        return True, [f"日志文件不存在: {log_file}"]
    
    try:
        content = log_file.read_text(encoding='utf-8', errors='ignore')
        
        # 检查关键错误关键词
        error_keywords = ['ERROR', 'CRITICAL', 'FATAL', 'Traceback', 'Exception', 'failed', 'Failed']
        errors = []
        
        for line_num, line in enumerate(content.splitlines(), 1):
            line_lower = line.lower()
            if any(keyword.lower() in line_lower for keyword in error_keywords):
                # 获取上下文（前后5行）
                lines = content.splitlines()
                start = max(0, line_num - 6)
                end = min(len(lines), line_num + 4)
                context = '\n'.join(lines[start:end])
                errors.append(f"第 {line_num} 行: {line.strip()}\n上下文:\n{context}")
        
        if errors:
            logger.error(f"发现 {len(errors)} 个错误/异常")
            return False, errors
        else:
            logger.info("✅ 回测日志检查通过，无错误")
            return True, []
            
    except Exception as e:
        logger.error(f"读取回测日志异常: {e}", exc_info=True)
        return False, [f"读取日志异常: {e}"]


# ==================== 2. 账户健康检查 ====================
def check_account_health(
    state_file: Optional[Path] = None,
    initial_capital: float = 1000000.0
) -> Tuple[bool, List[str]]:
    """
    检查虚拟账户当日收益率是否异常（>5% 或 <-5%）
    
    逻辑：
    1. 读取账户状态文件 (accounts/states/YYYY-MM-DD.json)
    2. 计算当日收益率 = (当前总资产 - 昨日总资产) / 昨日总资产
    3. 如果收益率超过阈值，标记为异常
    
    Args:
        state_file: 指定状态文件路径，None 则自动查找最新状态
        initial_capital: 初始资金（用于首次运行）
    
    Returns:
        (是否正常, 警告消息列表)
    """
    logger = logging.getLogger("alert_system.check_account")
    
    # 自动查找最新状态文件
    if state_file is None:
        if not ACCOUNTS_DIR.exists():
            logger.warning("账户数据目录不存在")
            return True, ["账户数据目录不存在"]
        
        state_files = sorted(ACCOUNTS_DIR.glob("states/20*.json"), key=lambda p: p.name, reverse=True)
        if not state_files:
            logger.warning("未找到账户状态文件")
            return True, ["未找到账户状态文件"]
        state_file = state_files[0]
    
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        current_date_str = state.get('date', state_file.stem)
        total_value = float(state.get('total_value', 0))
        cash = float(state.get('cash', 0))
        positions = state.get('positions', {})
        
        # 计算持仓市值
        position_value = 0.0
        for pos in positions.values():
            position_value += float(pos.get('market_value', 0))
        
        # 验证数据一致性
        if abs(total_value - (cash + position_value)) > 0.01:
            logger.warning(f"账户状态数据不一致: total_value={total_value}, cash+pos={cash+position_value}")
        
        # 查找昨日状态
        current_date = datetime.strptime(current_date_str, '%Y-%m-%d').date()
        yesterday = current_date - timedelta(days=1)
        
        # 尝试查找昨日的状态文件（跳过周末）
        for days_back in range(1, 7):  # 最多往前找6天（覆盖周末）
            check_date = current_date - timedelta(days=days_back)
            check_file = ACCOUNTS_DIR / "states" / f"{check_date.strftime('%Y-%m-%d')}.json"
            if check_file.exists():
                with open(check_file, 'r', encoding='utf-8') as f:
                    prev_state = json.load(f)
                prev_total_value = float(prev_state.get('total_value', initial_capital))
                break
        else:
            # 未找到前一日状态，使用初始资金作为基准
            prev_total_value = initial_capital
            logger.info(f"未找到前一日状态，使用初始资金作为基准: {initial_capital}")
        
        # 计算当日收益率
        if prev_total_value > 0:
            daily_return_pct = (total_value - prev_total_value) / prev_total_value * 100
        else:
            daily_return_pct = 0.0
        
        logger.info(f"账户收益率检查: {current_date_str}, 总资产={total_value:.2f}, 前一日={prev_total_value:.2f}, 收益率={daily_return_pct:.2f}%")
        
        # 检查是否超过阈值
        warnings = []
        if abs(daily_return_pct) >= DAILY_RETURN_THRESHOLD_PCT:
            direction = "上涨" if daily_return_pct > 0 else "下跌"
            warnings.append(
                f"⚠️ 账户当日{direction} {abs(daily_return_pct):.2f}% (阈值: ±{DAILY_RETURN_THRESHOLD_PCT:.1f}%)\n"
                f"   日期: {current_date_str}\n"
                f"   总资产: {total_value:,.2f} 元\n"
                f"   前一日: {prev_total_value:,.2f} 元\n"
                f"   现金: {cash:,.2f} 元\n"
                f"   持仓市值: {position_value:,.2f} 元"
            )
            logger.warning(f"账户收益率异常: {daily_return_pct:.2f}%")
            return False, warnings
        else:
            logger.info("✅ 账户收益率正常")
            return True, []
            
    except json.JSONDecodeError as e:
        error_msg = f"账户状态文件格式错误: {e}"
        logger.error(error_msg, exc_info=True)
        return False, [error_msg]
    except Exception as e:
        error_msg = f"检查账户健康状态异常: {e}"
        logger.error(error_msg, exc_info=True)
        return False, [error_msg]


# ==================== 3. 数据管道检查 ====================
def check_data_pipeline(
    check_date: Optional[date] = None,
    data_dir: Path = DAY_DIR
) -> Tuple[bool, List[str]]:
    """
    检查数据管道是否过期（最新日期是否超过指定天数未更新）
    
    逻辑：
    1. 读取 latest_date.txt 或扫描 data/day/*.csv 获取最新日期
    2. 如果最新日期距离今天超过 DATA_EXPIRY_DAYS 天，则告警
    
    Args:
        check_date: 检查基准日期（默认今天）
        data_dir: 数据目录路径
    
    Returns:
        (是否正常, 警告消息列表)
    """
    logger = logging.getLogger("alert_system.check_data")
    
    if check_date is None:
        check_date = date.today()
    
    # 获取最新数据日期
    latest_date = None
    
    # 方法1: 读取 latest_date.txt
    if LATEST_DATE_FILE.exists():
        try:
            content = LATEST_DATE_FILE.read_text().strip()
            latest_date = datetime.strptime(content, '%Y-%m-%d').date()
            logger.debug(f"从 latest_date.txt 读取最新日期: {latest_date}")
        except Exception as e:
            logger.warning(f"读取 latest_date.txt 失败: {e}")
    
    # 方法2: 扫描CSV文件
    if latest_date is None and data_dir.exists():
        max_date = None
        csv_files = list(data_dir.glob("*.csv"))
        
        if csv_files:
            logger.debug(f"扫描 {len(csv_files)} 个CSV文件获取最新日期...")
            
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file, parse_dates=['date'])
                    if len(df) > 0:
                        file_max = df['date'].max().date()
                        if max_date is None or file_max > max_date:
                            max_date = file_max
                except Exception as e:
                    logger.debug(f"读取 {csv_file.name} 跳过: {e}")
            
            if max_date:
                latest_date = max_date
    
    if latest_date is None:
        warning_msg = "无法确定数据最新日期（无数据文件或 latest_date.txt）"
        logger.warning(warning_msg)
        return False, [warning_msg]
    
    # 计算天数差
    days_diff = (check_date - latest_date).days
    
    logger.info(f"数据管道检查: 最新数据={latest_date}, 检查日期={check_date}, 间隔={days_diff}天")
    
    if days_diff > DATA_EXPIRY_DAYS:
        warning_msg = (
            f"⚠️ 数据已过期 {days_diff} 天（阈值: {DATA_EXPIRY_DAYS} 天）\n"
            f"   最新数据日期: {latest_date}\n"
            f"   检查日期: {check_date}\n"
            f"   数据目录: {data_dir}\n"
            f"   建议: 立即运行 daily_update.py 更新数据"
        )
        logger.warning(warning_msg)
        return False, [warning_msg]
    else:
        logger.info(f"✅ 数据已更新（间隔 {days_diff} 天，正常）")
        return True, []


# ==================== 主检查流程 ====================
def run_all_checks() -> Dict[str, Any]:
    """
    运行所有检查
    
    Returns:
        包含所有检查结果的字典
    """
    logger = logging.getLogger("alert_system")
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'checks': {}
    }
    
    logger.info("=" * 60)
    logger.info("🔍 开始监控检查")
    logger.info("=" * 60)
    
    # 1. 检查数据管道（最先检查，因为其他检查可能依赖数据）
    logger.info("\n[1/3] 数据管道检查...")
    data_ok, data_warnings = check_data_pipeline()
    results['checks']['data_pipeline'] = {
        'ok': data_ok,
        'warnings': data_warnings
    }
    
    # 2. 检查回测健康（如果有最新日志）
    logger.info("\n[2/3] 回测健康检查...")
    backtest_ok, backtest_errors = check_backtest_health()
    results['checks']['backtest_health'] = {
        'ok': backtest_ok,
        'errors': backtest_errors
    }
    
    # 3. 检查账户健康（如果有账户状态）
    logger.info("\n[3/3] 账户健康检查...")
    account_ok, account_warnings = check_account_health()
    results['checks']['account_health'] = {
        'ok': account_ok,
        'warnings': account_warnings
    }
    
    # 汇总
    total_checks = len(results['checks'])
    failed_checks = sum(1 for check in results['checks'].values() if not check['ok'])
    
    results['summary'] = {
        'total': total_checks,
        'failed': failed_checks,
        'all_passed': failed_checks == 0
    }
    
    logger.info("\n" + "=" * 60)
    if failed_checks == 0:
        logger.info("✅ 所有检查通过")
    else:
        logger.warning(f"⚠️ {failed_checks}/{total_checks} 项检查失败")
    logger.info("=" * 60)
    
    return results


# ==================== 命令行入口 ====================
def main():
    """主函数 - 用于定时任务或手动运行"""
    # 配置日志文件
    log_file = MONITORING_DIR / "alert_system.log"
    logger = setup_logging(log_file)
    
    try:
        # 运行所有检查
        results = run_all_checks()
        
        # 如果有失败的检查，发送告警
        if not results['summary']['all_passed']:
            alert_messages = []
            
            for check_name, check_result in results['checks'].items():
                if not check_result['ok']:
                    check_label = {
                        'data_pipeline': '数据管道',
                        'backtest_health': '回测健康',
                        'account_health': '账户健康'
                    }.get(check_name, check_name)
                    
                    # 收集所有消息
                    if 'errors' in check_result:
                        for err in check_result['errors']:
                            alert_messages.append(f"【{check_label}】{err}")
                    if 'warnings' in check_result:
                        for warn in check_result['warnings']:
                            alert_messages.append(f"【{check_label}】{warn}")
            
            if alert_messages:
                alert_msg = "\n\n".join(alert_messages)
                send_alert(alert_msg, logger)
                logger.error("检测到异常，已发送告警")
                sys.exit(1)
        else:
            logger.info("所有系统正常，无需告警")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.warning("监控任务被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"监控任务执行异常: {e}", exc_info=True)
        send_alert(f"监控系统自身异常: {e}", logger)
        sys.exit(1)


if __name__ == "__main__":
    main()
