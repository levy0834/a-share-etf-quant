"""
Claw Street API 客户端封装

提供与 Claw Street 交易平台 API 的交互功能，包括账户查询、持仓管理、
订单操作等。支持模拟模式和自动重试机制。
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from requests.exceptions import RequestException

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ClawStreetError(Exception):
    """Claw Street API 异常基类"""
    pass


class AuthenticationError(ClawStreetError):
    """认证失败异常"""
    pass


class ResourceNotFoundError(ClawStreetError):
    """资源不存在异常"""
    pass


class RateLimitError(ClawStreetError):
    """限流异常"""
    pass


class ClawStreetClient:
    """
    Claw Street API 客户端

    用于与 Claw Street 交易平台进行交互，支持账户查询、持仓管理、
    订单操作等功能。提供模拟模式和自动重试机制。

    Attributes:
        api_key (str): API 密钥
        base_url (str): API 基础 URL
        mock (bool): 是否使用模拟模式
        logger (logging.Logger): 日志记录器
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        mock: bool = False
    ) -> None:
        """
        初始化 Claw Street 客户端

        Args:
            api_key: API 密钥
            base_url: API 基础 URL，如果为 None 则从环境变量 CLAW_STREET_URL 获取，
                     否则使用默认值 https://api.clawstreet.com/v1
            mock: 是否使用模拟模式，True 时不发起真实请求
        """
        self.api_key = api_key
        self.mock = mock

        # 设置 base_url
        if base_url is None:
            self.base_url = os.getenv('CLAW_STREET_URL', 'https://api.clawstreet.com/v1')
        else:
            self.base_url = base_url.rstrip('/')

        # 设置日志
        self._setup_logging()

        # 配置 requests 会话和重试策略
        if not mock:
            self.session = self._create_session()
        else:
            self.session = None

        # 模拟数据存储
        self._mock_orders: Dict[str, Dict[str, Any]] = {}
        self._mock_account: Dict[str, float] = {
            'cash': 100000.0,
            'total_value': 100000.0,
            'available': 100000.0
        }
        self._mock_positions: Dict[str, Dict[str, Any]] = {
            '000001': {
                'quantity': 1000,
                'avg_price': 10.5,
                'market_value': 10500.0
            },
            '000002': {
                'quantity': 500,
                'avg_price': 20.0,
                'market_value': 10000.0
            }
        }

        self.logger.info(f"ClawStreetClient initialized (mock={mock})")

    def _setup_logging(self) -> None:
        """配置日志记录"""
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / 'claw_street_client.log'

        # 创建 logger
        self.logger = logging.getLogger('ClawStreetClient')
        self.logger.setLevel(logging.DEBUG)

        # 避免重复添加 handler
        if not self.logger.handlers:
            # 文件 handler
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)

            # 控制台 handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # 格式器
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def _create_session(self) -> requests.Session:
        """
        创建带有重试机制的 requests 会话

        Returns:
            requests.Session: 配置好的会话对象
        """
        session = requests.Session()

        # 设置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 设置默认请求头
        session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        })

        return session

    def _mask_sensitive_info(self, data: Any) -> Any:
        """
        脱敏敏感信息（如 API key）

        Args:
            data: 需要脱敏的数据

        Returns:
            脱敏后的数据
        """
        if isinstance(data, dict):
            masked = data.copy()
            if 'Authorization' in masked:
                masked['Authorization'] = 'Bearer ***MASKED***'
            if 'api_key' in masked:
                masked['api_key'] = '***MASKED***'
            return masked
        return data

    def _log_request(self, method: str, url: str, payload: Optional[Dict] = None) -> None:
        """
        记录请求日志

        Args:
            method: HTTP 方法
            url: 请求 URL
            payload: 请求参数
        """
        log_data = {
            'method': method,
            'url': url,
            'payload': self._mask_sensitive_info(payload) if payload else None
        }
        self.logger.debug(f"Request: {json.dumps(log_data, ensure_ascii=False, default=str)}")

    def _log_response(self, status_code: int, response: Optional[requests.Response] = None) -> None:
        """
        记录响应日志

        Args:
            status_code: HTTP 状态码
            response: 响应对象
        """
        if response is not None:
            try:
                resp_data = response.json()
            except:
                resp_data = response.text[:200]
        else:
            resp_data = None

        log_data = {
            'status_code': status_code,
            'response': self._mask_sensitive_info(resp_data)
        }
        self.logger.debug(f"Response: {json.dumps(log_data, ensure_ascii=False, default=str)}")

    def _record_failed_order(
        self,
        operation: str,
        params: Dict[str, Any],
        error: Exception
    ) -> None:
        """
        记录失败订单

        Args:
            operation: 操作类型（如 'place_order'）
            params: 操作参数
            error: 异常对象
        """
        orders_dir = Path('orders')
        orders_dir.mkdir(exist_ok=True)
        failed_file = orders_dir / 'failed.json'

        # 读取现有记录
        if failed_file.exists():
            with open(failed_file, 'r', encoding='utf-8') as f:
                failed_orders = json.load(f)
        else:
            failed_orders = []

        # 添加新记录
        failed_record = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'params': params,
            'error_type': type(error).__name__,
            'error_message': str(error)
        }
        failed_orders.append(failed_record)

        # 写入文件
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump(failed_orders, f, indent=2, ensure_ascii=False)

        self.logger.error(f"Failed order recorded: {operation} - {str(error)}")

    def _handle_http_error(self, response: requests.Response) -> None:
        """
        处理 HTTP 错误状态码

        Args:
            response: HTTP 响应对象

        Raises:
            对应的异常类型
        """
        status_code = response.status_code

        if status_code == 401:
            raise AuthenticationError(f"认证失败: {response.text}")
        elif status_code == 404:
            raise ResourceNotFoundError(f"资源不存在: {response.text}")
        elif status_code == 429:
            raise RateLimitError(f"请求限流: {response.text}")
        else:
            response.raise_for_status()

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求（带重试机制）

        Args:
            method: HTTP 方法
            endpoint: API 端点
            payload: 请求参数

        Returns:
            响应数据

        Raises:
            ClawStreetError: 当所有重试失败或遇到不可恢复错误时
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        for attempt in range(3):
            try:
                self._log_request(method, url, payload)

                if method.upper() == 'GET':
                    response = self.session.get(url, params=payload, timeout=10)
                else:
                    response = self.session.post(url, json=payload, timeout=10)

                self._log_response(response.status_code, response)

                # 检查 HTTP 状态码
                if response.status_code == 200:
                    return response.json()
                else:
                    self._handle_http_error(response)

            except RequestException as e:
                self.logger.warning(f"Request failed (attempt {attempt + 1}/3): {str(e)}")
                if attempt == 2:  # 最后一次尝试失败
                    raise ClawStreetError(f"请求失败: {str(e)}")
                time.sleep(2 ** attempt)  # 指数退避

        raise ClawStreetError("所有重试均已失败")

    def get_account(self) -> Dict[str, float]:
        """
        获取账户信息

        Returns:
            账户信息字典，包含:
            - cash: 可用现金余额
            - total_value: 总资产价值
            - available: 可用资金

        Raises:
            ClawStreetError: 当 API 请求失败时
        """
        if self.mock:
            self.logger.info("Mock mode: returning simulated account data")
            return self._mock_account.copy()

        try:
            data = self._request_with_retry('GET', '/account')
            return {
                'cash': float(data.get('cash', 0)),
                'total_value': float(data.get('total_value', 0)),
                'available': float(data.get('available', 0))
            }
        except Exception as e:
            self._record_failed_order('get_account', {}, e)
            raise

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        获取持仓信息

        Returns:
            持仓字典，格式为 {symbol: {quantity, avg_price, market_value}}

        Raises:
            ClawStreetError: 当 API 请求失败时
        """
        if self.mock:
            self.logger.info("Mock mode: returning simulated positions")
            return self._mock_positions.copy()

        try:
            data = self._request_with_retry('GET', '/positions')
            positions = {}

            for item in data.get('positions', []):
                symbol = item.get('symbol', '')
                positions[symbol] = {
                    'quantity': int(item.get('quantity', 0)),
                    'avg_price': float(item.get('avg_price', 0)),
                    'market_value': float(item.get('market_value', 0))
                }

            return positions
        except Exception as e:
            self._record_failed_order('get_positions', {}, e)
            raise

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = 'LIMIT',
        price: Optional[float] = None
    ) -> str:
        """
        下单

        Args:
            symbol: 股票代码
            side: 交易方向，'buy' 或 'sell'
            quantity: 交易数量
            order_type: 订单类型，默认为 'LIMIT'
            price: 限价单价格，市价单可为 None

        Returns:
            order_id: 订单 ID

        Raises:
            ValueError: 当参数无效时
            ClawStreetError: 当 API 请求失败时
        """
        # 参数验证
        if side not in ['buy', 'sell']:
            raise ValueError(f"无效的 side 参数: {side}，必须是 'buy' 或 'sell'")

        if quantity <= 0:
            raise ValueError(f"无效的 quantity 参数: {quantity}，必须大于 0")

        if order_type == 'LIMIT' and price is None:
            raise ValueError("限价单必须指定 price 参数")

        payload = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'order_type': order_type,
        }

        if price is not None:
            payload['price'] = price

        if self.mock:
            self.logger.info(f"Mock mode: placing order {payload}")
            order_id = f"mock_{int(time.time())}_{hash(str(payload)) % 10000:04d}"
            self._mock_orders[order_id] = {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'order_type': order_type,
                'price': price,
                'status': 'open',
                'filled_qty': 0,
                'timestamp': datetime.now().isoformat()
            }
            return order_id

        try:
            data = self._request_with_retry('POST', '/orders', payload)
            order_id = data.get('order_id', '')
            if not order_id:
                raise ClawStreetError("响应中缺少 order_id")
            return order_id
        except Exception as e:
            self._record_failed_order('place_order', payload, e)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单

        Args:
            order_id: 订单 ID

        Returns:
            是否成功取消

        Raises:
            ClawStreetError: 当 API 请求失败时
        """
        if not order_id:
            raise ValueError("order_id 不能为空")

        if self.mock:
            self.logger.info(f"Mock mode: cancelling order {order_id}")
            if order_id in self._mock_orders:
                self._mock_orders[order_id]['status'] = 'cancelled'
                return True
            return False

        try:
            response = self._request_with_retry('POST', f'/orders/{order_id}/cancel')
            # 假设成功返回 True
            return True
        except Exception as e:
            self._record_failed_order('cancel_order', {'order_id': order_id}, e)
            raise

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        获取订单状态

        Args:
            order_id: 订单 ID

        Returns:
            订单状态字典，包含:
            - status: 'open' | 'filled' | 'cancelled'
            - filled_qty: 已成交数量
            - 其他可能字段

        Raises:
            ValueError: 当 order_id 为空时
            ClawStreetError: 当 API 请求失败时
        """
        if not order_id:
            raise ValueError("order_id 不能为空")

        if self.mock:
            self.logger.info(f"Mock mode: getting order status for {order_id}")

            # 模拟状态流转（随机）
            import random
            if order_id in self._mock_orders:
                order = self._mock_orders[order_id]
                # 模拟部分成交
                if order['status'] == 'open' and order['filled_qty'] < order['quantity']:
                    fill_amount = random.randint(1, max(1, order['quantity'] - order['filled_qty']))
                    order['filled_qty'] += fill_amount
                    if order['filled_qty'] >= order['quantity']:
                        order['status'] = 'filled'

                return {
                    'order_id': order_id,
                    'status': order['status'],
                    'filled_qty': order['filled_qty'],
                    'quantity': order['quantity'],
                    'symbol': order['symbol'],
                    'side': order['side'],
                    'order_type': order['order_type'],
                    'price': order['price']
                }
            else:
                raise ResourceNotFoundError(f"订单不存在: {order_id}")

        try:
            return self._request_with_retry('GET', f'/orders/{order_id}')
        except Exception as e:
            self._record_failed_order('get_order_status', {'order_id': order_id}, e)
            raise


if __name__ == "__main__":
    # 使用示例

    # 示例 1: 使用模拟模式
    print("示例 1: 模拟模式")
    client = ClawStreetClient(api_key="demo_key", mock=True)

    # 查询账户
    account = client.get_account()
    print(f"账户信息: {account}")

    # 查询持仓
    positions = client.get_positions()
    print(f"持仓: {positions}")

    # 下单
    order_id = client.place_order(
        symbol="000001",
        side="buy",
        quantity=100,
        order_type="LIMIT",
        price=10.5
    )
    print(f"下单成功，订单 ID: {order_id}")

    # 查询订单状态
    status = client.get_order_status(order_id)
    print(f"订单状态: {status}")

    # 取消订单
    cancelled = client.cancel_order(order_id)
    print(f"取消订单: {cancelled}")

    print("\n" + "="*50 + "\n")

    # 示例 2: 真实 API 调用（需要设置环境变量 CLAW_STREET_URL 和有效的 API key）
    print("示例 2: 真实 API（注释掉以避免实际调用）")
    """
    import os
    api_key = os.getenv('SERVICE_ACCESS_CODE')  # 生产环境设置此环境变量
    if api_key:
        client = ClawStreetClient(api_key=api_key)
        try:
            account = client.get_account()
            print(f"账户信息: {account}")
            positions = client.get_positions()
            print(f"持仓: {positions}")
        except Exception as e:
            print(f"错误: {e}")
    else:
        print("未设置服务访问码环境变量")
    """
