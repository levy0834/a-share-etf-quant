"""
ETF 轮动策略模块

提供三种不同的ETF选股和仓位分配策略：
1. select_top_k - 基于动量的简单选股，等权分配
2. momentum_risk_parity - 基于动量的风险平价仓位管理
3. multi_factor - 多因子综合评分选股

每个策略函数接收包含ETF价格数据的DataFrame，返回信号字典和仓位字典。
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np


def compute_returns(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    计算每个ETF在过去 lookback 日的收益率

    Args:
        df: 多索引DataFrame，第一层是ETF代码，第二层是日期索引
           需要包含 'close' 或 'price' 列
        lookback: 回溯天数，默认20日

    Returns:
        Series: 索引为ETF代码，值为过去lookback日收益率
    """
    # 确定价格列名
    price_col = 'close' if 'close' in df.columns else 'price'

    # 按ETF分组计算收益率
    returns = {}
    for etf in df.index.get_level_values(0).unique():
        etf_data = df.loc[etf]
        if len(etf_data) >= lookback:
            current_price = etf_data.iloc[-1][price_col]
            past_price = etf_data.iloc[-lookback][price_col]
            ret = (current_price - past_price) / past_price
            returns[etf] = ret
        else:
            returns[etf] = np.nan

    return pd.Series(returns)


def compute_volatility(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """
    计算每个ETF在过去 lookback 日的收益率波动率（标准差）

    Args:
        df: 多索引DataFrame，第一层是ETF代码，第二层是日期索引
           需要包含 'close' 或 'price' 列
        lookback: 回溯天数，默认60日

    Returns:
        Series: 索引为ETF代码，值为波动率（日收益率标准差年化可选）
    """
    price_col = 'close' if 'close' in df.columns else 'price'
    volatilities = {}

    for etf in df.index.get_level_values(0).unique():
        etf_data = df.loc[etf]
        if len(etf_data) >= lookback + 1:
            # 获取最近 lookback 天的价格
            prices = etf_data[price_col].iloc[-lookback-1:].values
            # 计算日收益率
            daily_returns = np.diff(prices) / prices[:-1]
            # 计算标准差
            vol = np.std(daily_returns, ddof=1)
            volatilities[etf] = vol
        else:
            volatilities[etf] = np.nan

    return pd.Series(volatilities)


def select_top_k(
    df: pd.DataFrame,
    k: int = 5,
    lookback: int = 20
) -> Tuple[Dict[str, str], Dict[str, float]]:
    """
    基于过去 lookback 日收益率选择 top k 只ETF

    策略逻辑：
    - 计算每个ETF过去 lookback 日的收益率
    - 按收益率从高到低排序，取前 k 名
    - 信号：top k ETF → 'buy'，其余 → 'hold'
    - 仓位：等权分配，每只ETF分配 1.0/k

    Args:
        df: 多索引DataFrame，第一层是ETF代码，第二层是日期索引
        k: 选取的ETF数量，默认5
        lookback: 收益率计算的回溯天数，默认20

    Returns:
        Tuple[signal_dict, position_size_dict]:
            - signal_dict: {etf_code: 'buy'/'hold'}
            - position_size_dict: {etf_code: weight} (权重和为1.0)

    Example:
        >>> signals, positions = select_top_k(df, k=3, lookback=10)
        >>> signals
        {'ETF001': 'buy', 'ETF002': 'buy', 'ETF003': 'buy', 'ETF004': 'hold', ...}
        >>> positions
        {'ETF001': 0.333, 'ETF002': 0.333, 'ETF003': 0.333, 'ETF004': 0.0, ...}
    """
    # 计算收益率
    returns = compute_returns(df, lookback)

    # 去除NaN值
    valid_returns = returns.dropna()

    if len(valid_returns) == 0:
        # 没有有效数据，全部持有
        all_etfs = df.index.get_level_values(0).unique()
        return (
            {etf: 'hold' for etf in all_etfs},
            {etf: 0.0 for etf in all_etfs}
        )

    # 排序并选择前k个
    top_k_etfs = valid_returns.nlargest(min(k, len(valid_returns))).index.tolist()

    # 获取所有ETF
    all_etfs = df.index.get_level_values(0).unique()

    # 生成信号
    signal_dict = {}
    position_size_dict = {}
    weight = 1.0 / len(top_k_etfs) if len(top_k_etfs) > 0 else 0.0

    for etf in all_etfs:
        if etf in top_k_etfs:
            signal_dict[etf] = 'buy'
            position_size_dict[etf] = weight
        else:
            signal_dict[etf] = 'hold'
            position_size_dict[etf] = 0.0

    return signal_dict, position_size_dict


def momentum_risk_parity(
    df: pd.DataFrame,
    k: int = 5,
    volatility_lookback: int = 60
) -> Tuple[Dict[str, str], Dict[str, float]]:
    """
    动量策略 + 风险平价仓位分配

    策略逻辑：
    - 首先基于过去20日收益率选择 top k 的ETF
    - 计算每个ETF的近期波动率（波动率回溯期可配置）
    - 仓位权重 = (1/波动率) 归一化，使得权重和为1
    - 未入选的ETF仓位为0

    Args:
        df: 多索引DataFrame，第一层是ETF代码，第二层是日期索引
        k: 选取的ETF数量，默认5
        volatility_lookback: 波动率计算的回溯天数，默认60

    Returns:
        Tuple[signal_dict, position_size_dict]:
            - signal_dict: {etf_code: 'buy'/'hold'}
            - position_size_dict: {etf_code: weight} (权重和为1.0)

    Example:
        >>> signals, positions = momentum_risk_parity(df, k=5)
        >>> positions  # 权重与波动率成反比
        {'ETF001': 0.25, 'ETF002': 0.15, 'ETF003': 0.30, ...}
    """
    # 步骤1: 基于20日收益率选择top k
    momentum_returns = compute_returns(df, lookback=20)
    valid_momentum = momentum_returns.dropna()

    if len(valid_momentum) == 0:
        all_etfs = df.index.get_level_values(0).unique()
        return (
            {etf: 'hold' for etf in all_etfs},
            {etf: 0.0 for etf in all_etfs}
        )

    top_k_momentum = valid_momentum.nlargest(min(k, len(valid_momentum))).index.tolist()

    # 步骤2: 计算波动率
    volatilities = compute_volatility(df, volatility_lookback)

    # 步骤3: 计算风险平价权重
    # 只对入选的ETF计算权重
    inv_vol_weights = {}
    for etf in top_k_momentum:
        vol = volatilities.get(etf, np.nan)
        if pd.isna(vol) or vol == 0:
            inv_vol_weights[etf] = 0.0
        else:
            inv_vol_weights[etf] = 1.0 / vol

    # 归一化
    total_inv_vol = sum(inv_vol_weights.values())
    position_size_dict = {}
    if total_inv_vol > 0:
        for etf in top_k_momentum:
            position_size_dict[etf] = inv_vol_weights[etf] / total_inv_vol
    else:
        for etf in top_k_momentum:
            position_size_dict[etf] = 1.0 / len(top_k_momentum)

    # 步骤4: 生成完整信号和仓位字典
    all_etfs = df.index.get_level_values(0).unique()
    signal_dict = {}
    final_position_dict = {}

    for etf in all_etfs:
        if etf in top_k_momentum:
            signal_dict[etf] = 'buy'
            final_position_dict[etf] = position_size_dict[etf]
        else:
            signal_dict[etf] = 'hold'
            final_position_dict[etf] = 0.0

    return signal_dict, final_position_dict


def multi_factor(
    df: pd.DataFrame,
    k: int = 5,
    momentum_weight: float = 0.4,
    valuation_weight: float = 0.3,
    volume_weight: float = 0.3
) -> Tuple[Dict[str, str], Dict[str, float]]:
    """
    多因子综合评分选股策略

    因子构成（权重可调）：
    - 动量因子 (40%)：过去20日收益率
    - 估值因子 (30%)：PE倒数（PE越小越好，需从metadata获取或使用价格/收益）
    - 成交量突破 (30%)：当前成交量 / 过去20日平均成交量

    处理流程：
    1. 分别计算三个因子的原始值
    2. 对每个因子进行 min-max 标准化（归一化到[0,1]）
    3. 加权求和得到综合评分
    4. 选择综合评分最高的 k 只ETF
    5. 等权分配仓位

    Args:
        df: 多索引DataFrame，第一层是ETF代码，第二层是日期索引
            需要包含：'close'/'price', 'volume', 'pe'（或可计算）
        k: 选取的ETF数量，默认5
        momentum_weight: 动量因子权重，默认0.4
        valuation_weight: 估值因子权重，默认0.3
        volume_weight: 成交量突破因子权重，默认0.3

    Returns:
        Tuple[signal_dict, position_size_dict]:
            - signal_dict: {etf_code: 'buy'/'hold'}
            - position_size_dict: {etf_code: weight} (权重和为1.0)

    Example:
        >>> signals, positions = multi_factor(df, k=3)
        >>> positions  # 等权分配
        {'ETF001': 0.333, 'ETF002': 0.333, 'ETF003': 0.333}
    """
    # 验证权重和
    total_weight = momentum_weight + valuation_weight + volume_weight
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"因子权重之和必须为1.0，当前为{total_weight:.3f}")

    all_etfs = df.index.get_level_values(0).unique()
    factor_scores = {etf: {} for etf in all_etfs}

    # 因子1: 动量因子 (过去20日收益率)
    returns = compute_returns(df, lookback=20)
    for etf in all_etfs:
        factor_scores[etf]['momentum'] = returns.get(etf, np.nan)

    # 因子2: 估值因子 (PE倒数)
    # 尝试从DataFrame获取PE，如果没有则尝试计算（价格/收益）
    for etf in all_etfs:
        etf_data = df.loc[etf] if etf in df.index.get_level_values(0) else pd.DataFrame()
        if len(etf_data) > 0:
            if 'pe' in etf_data.columns:
                pe = etf_data.iloc[-1]['pe']
            elif 'earnings' in etf_data.columns:
                price = etf_data.iloc[-1]['close'] if 'close' in etf_data.columns else etf_data.iloc[-1]['price']
                earnings = etf_data.iloc[-1]['earnings']
                pe = price / earnings if earnings != 0 else np.nan
            else:
                pe = np.nan

            # PE倒数为估值因子，PE越小越好（倒数越大越好）
            factor_scores[etf]['valuation'] = 1.0 / pe if pd.notna(pe) and pe > 0 else np.nan
        else:
            factor_scores[etf]['valuation'] = np.nan

    # 因子3: 成交量突破 (当前成交量 / 过去20日平均成交量)
    for etf in all_etfs:
        etf_data = df.loc[etf] if etf in df.index.get_level_values(0) else pd.DataFrame()
        if len(etf_data) >= 20 and 'volume' in etf_data.columns:
            current_volume = etf_data.iloc[-1]['volume']
            avg_volume = etf_data['volume'].iloc[-20:].mean()
            factor_scores[etf]['volume'] = current_volume / avg_volume if avg_volume > 0 else np.nan
        else:
            factor_scores[etf]['volume'] = np.nan

    # Min-Max标准化
    normalized_scores = {etf: {} for etf in all_etfs}
    for factor in ['momentum', 'valuation', 'volume']:
        values = [factor_scores[etf][factor] for etf in all_etfs]
        valid_values = [v for v in values if pd.notna(v)]

        if len(valid_values) == 0:
            # 所有ETF该因子都无效，均匀赋值为0.5
            for etf in all_etfs:
                normalized_scores[etf][factor] = 0.5
            continue

        min_val = min(valid_values)
        max_val = max(valid_values)

        # 避免除以0
        if max_val == min_val:
            for etf in all_etfs:
                normalized_scores[etf][factor] = 0.5 if pd.notna(factor_scores[etf][factor]) else np.nan
        else:
            for etf in all_etfs:
                val = factor_scores[etf][factor]
                if pd.notna(val):
                    normalized_scores[etf][factor] = (val - min_val) / (max_val - min_val)
                else:
                    normalized_scores[etf][factor] = np.nan

    # 加权综合评分
    composite_scores = {}
    for etf in all_etfs:
        scores = normalized_scores[etf]
        # 只有所有因子都有有效值才计算总分
        if all(pd.notna(scores[f]) for f in ['momentum', 'valuation', 'volume']):
            total = (
                scores['momentum'] * momentum_weight +
                scores['valuation'] * valuation_weight +
                scores['volume'] * volume_weight
            )
            composite_scores[etf] = total
        else:
            composite_scores[etf] = np.nan

    # 选择top k
    valid_scores = {etf: score for etf, score in composite_scores.items() if pd.notna(score)}
    if len(valid_scores) == 0:
        return (
            {etf: 'hold' for etf in all_etfs},
            {etf: 0.0 for etf in all_etfs}
        )

    top_k_etfs = sorted(valid_scores.items(), key=lambda x: x[1], reverse=True)[:min(k, len(valid_scores))]
    top_k_codes = [etf for etf, _ in top_k_etfs]

    # 等权分配
    weight = 1.0 / len(top_k_codes)

    # 生成结果
    signal_dict = {}
    position_size_dict = {}

    for etf in all_etfs:
        if etf in top_k_codes:
            signal_dict[etf] = 'buy'
            position_size_dict[etf] = weight
        else:
            signal_dict[etf] = 'hold'
            position_size_dict[etf] = 0.0

    return signal_dict, position_size_dict


# ==================== 测试代码 ====================

def _create_sample_data() -> pd.DataFrame:
    """
    创建测试用的模拟数据

    Returns:
        DataFrame: 多索引DataFrame (etf, date)，包含价格、成交量、PE
    """
    np.random.seed(42)
    etfs = ['ETF001', 'ETF002', 'ETF003', 'ETF004', 'ETF005', 'ETF006', 'ETF007']
    dates = pd.date_range(end=pd.Timestamp.today(), periods=100, freq='D')

    data = []
    for etf in etfs:
        # 为每个ETF生成不同的趋势和波动率
        trend = np.random.uniform(-0.002, 0.003)
        volatility = np.random.uniform(0.01, 0.03)

        prices = [100.0]
        for i in range(1, len(dates)):
            ret = trend + np.random.normal(0, volatility)
            prices.append(prices[-1] * (1 + ret))

        # 成交量（与价格波动相关）
        volumes = np.random.randint(100000, 1000000, len(dates))

        # PE估值
        base_pe = np.random.uniform(10, 30)
        pes = base_pe + np.random.normal(0, 2, len(dates))

        for i, date in enumerate(dates):
            data.append({
                'etf': etf,
                'date': date,
                'close': prices[i],
                'volume': volumes[i],
                'pe': max(pes[i], 1)  # PE至少为1
            })

    df = pd.DataFrame(data)
    df.set_index(['etf', 'date'], inplace=True)
    return df


def test_select_top_k():
    """测试 select_top_k 策略"""
    print("=" * 60)
    print("测试 select_top_k 策略")
    print("=" * 60)

    df = _create_sample_data()
    signals, positions = select_top_k(df, k=3, lookback=20)

    print("\n信号字典 (前5个):")
    for etf, signal in list(signals.items())[:5]:
        print(f"  {etf}: {signal}")

    print("\n仓位字典 (前5个):")
    for etf, pos in list(positions.items())[:5]:
        print(f"  {etf}: {pos:.3f}")

    print(f"\n总仓位: {sum(positions.values()):.3f}")

    # 验证
    buy_count = sum(1 for s in signals.values() if s == 'buy')
    print(f"买入信号数量: {buy_count} (期望: 3或更少)")
    assert buy_count <= 3, "买入数量不应超过k"

    print("✅ select_top_k 测试通过")


def test_momentum_risk_parity():
    """测试 momentum_risk_parity 策略"""
    print("\n" + "=" * 60)
    print("测试 momentum_risk_parity 策略")
    print("=" * 60)

    df = _create_sample_data()
    signals, positions = momentum_risk_parity(df, k=4, volatility_lookback=40)

    print("\n信号字典 (前5个):")
    for etf, signal in list(signals.items())[:5]:
        print(f"  {etf}: {signal}")

    print("\n仓位字典 (前5个):")
    for etf, pos in list(positions.items())[:5]:
        print(f"  {etf}: {pos:.3f}")

    print(f"\n总仓位: {sum(positions.values()):.3f}")

    # 验证权重和为1
    total_weight = sum(positions.values())
    assert abs(total_weight - 1.0) < 1e-6, f"仓位权重之和应为1.0，实际为{total_weight:.6f}"

    buy_count = sum(1 for s in signals.values() if s == 'buy')
    print(f"买入信号数量: {buy_count} (期望: 4)")
    assert buy_count <= 4, "买入数量不应超过k"

    print("✅ momentum_risk_parity 测试通过")


def test_multi_factor():
    """测试 multi_factor 策略"""
    print("\n" + "=" * 60)
    print("测试 multi_factor 策略")
    print("=" * 60)

    df = _create_sample_data()
    signals, positions = multi_factor(df, k=3)

    print("\n信号字典 (前5个):")
    for etf, signal in list(signals.items())[:5]:
        print(f"  {etf}: {signal}")

    print("\n仓位字典 (前5个):")
    for etf, pos in list(positions.items())[:5]:
        print(f"  {etf}: {pos:.3f}")

    print(f"\n总仓位: {sum(positions.values()):.3f}")

    # 验证
    buy_count = sum(1 for s in signals.values() if s == 'buy')
    print(f"买入信号数量: {buy_count} (期望: 3)")
    assert buy_count <= 3, "买入数量不应超过k"

    total_weight = sum(positions.values())
    assert abs(total_weight - 1.0) < 1e-6, f"仓位权重之和应为1.0，实际为{total_weight:.6f}"

    print("✅ multi_factor 测试通过")


def run_all_tests():
    """运行所有测试"""
    test_select_top_k()
    test_momentum_risk_parity()
    test_multi_factor()
    print("\n" + "=" * 60)
    print("所有策略测试通过！ ✅")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
