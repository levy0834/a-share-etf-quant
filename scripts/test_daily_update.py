#!/usr/bin/env python3
"""
daily_update.py 单元测试

测试核心功能（无需实际下载数据）
"""

import sys
import os
from pathlib import Path
from datetime import date, datetime

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# 导入被测试的模块
import daily_update as du


def test_parse_date_string():
    """测试日期解析"""
    print("测试: parse_date_string")
    assert du.parse_date_string("2025-03-06") == date(2025, 3, 6)
    assert du.parse_date_string("2025/03/06") == date(2025, 3, 6)
    assert du.parse_date_string("20250306") == date(2025, 3, 6)
    assert du.parse_date_string("invalid") is None
    print("✅ 通过")


def test_get_trading_days():
    """测试交易日生成"""
    print("测试: get_trading_days")
    start = date(2025, 3, 1)  # 周六
    end = date(2025, 3, 7)    # 周五
    days = du.get_trading_days(start, end)
    # 3月1日(六)、2(日)、3(一)、4(二)、5(三)、6(四)、7(五)
    expected = [date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5),
                date(2025, 3, 6), date(2025, 3, 7)]
    assert days == expected
    print("✅ 通过")


def test_validate_etf_data_nonexistent():
    """测试无效文件"""
    print("测试: validate_etf_data (文件不存在)")
    result = du.validate_etf_data("999999")
    assert result['exists'] is False
    assert len(result['errors']) > 0
    print("✅ 通过")


def test_validate_etf_data_mock():
    """测试有效数据（创建临时文件）"""
    print("测试: validate_etf_data (有效数据)")
    import pandas as pd
    import tempfile
    import shutil

    # 创建临时目录
    tmpdir = tempfile.mkdtemp()
    try:
        # 创建临时DAY_DIR结构
        temp_day_dir = Path(tmpdir) / "day"
        temp_day_dir.mkdir()
        test_csv = temp_day_dir / "test_etf.csv"

        dates = pd.date_range('2025-01-02', periods=5, freq='B')
        df = pd.DataFrame({
            'date': dates,
            'open': [1.0] * 5,
            'close': [1.1] * 5,
            'high': [1.2] * 5,
            'low': [0.9] * 5,
            'volume': [100000] * 5
        })
        df.to_csv(test_csv, index=False)

        # 临时替换 DAY_DIR 和 DATA_DIR
        original_day_dir = du.DAY_DIR
        original_data_dir = du.DATA_DIR
        du.DAY_DIR = temp_day_dir
        du.DATA_DIR = tmpdir

        try:
            result = du.validate_etf_data("test_etf")
            assert result['exists'] is True, f"Expected exists=True, got {result['exists']}"
            assert result['valid'] is True, f"Expected valid=True, got {result['valid']}, errors: {result['errors']}"
            assert result['rows'] == 5, f"Expected rows=5, got {result['rows']}"
            print("✅ 通过")
        finally:
            du.DAY_DIR = original_day_dir
            du.DATA_DIR = original_data_dir
    finally:
        shutil.rmtree(tmpdir)


def test_send_feishu_alert_no_webhook():
    """测试飞书通知（无webhook配置）"""
    print("测试: send_feishu_alert (无webhook)")
    # 确保环境变量为空
    old_val = os.environ.get("FEISHU_WEBHOOK_URL")
    if "FEISHU_WEBHOOK_URL" in os.environ:
        del os.environ["FEISHU_WEBHOOK_URL"]

    try:
        result = du.send_feishu_alert("测试消息")
        assert result is False  # 应该失败并返回False
        print("✅ 通过")
    finally:
        if old_val:
            os.environ["FEISHU_WEBHOOK_URL"] = old_val


def test_get_daily_log_file():
    """测试日志文件路径生成"""
    print("测试: get_daily_log_file")
    logfile = du.get_daily_log_file()
    expected_name = f"daily_update_{date.today().strftime('%Y-%m-%d')}.log"
    assert logfile.name == expected_name
    assert logfile.parent == du.LOGS_DIR
    print("✅ 通过")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("daily_update.py 单元测试")
    print("=" * 60)

    tests = [
        test_parse_date_string,
        test_get_trading_days,
        test_validate_etf_data_nonexistent,
        test_validate_etf_data_mock,
        test_send_feishu_alert_no_webhook,
        test_get_daily_log_file,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ 异常: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"总计: {len(tests)} | 通过: {passed} | 失败: {failed}")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
