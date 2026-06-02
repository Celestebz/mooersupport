"""
配件价格数据库模块
从 config.yml 读取配件价格信息
"""
import os
import yaml
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_config = None

def _load_config() -> Dict[str, Any]:
    """加载配置文件"""
    global _config
    if _config is None:
        config_path = os.path.join(os.getcwd(), "config.yml")
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                _config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config.yml: {e}")
            _config = {}
    return _config

def get_part_price(product_model: str, part_name: str) -> Optional[Dict[str, Any]]:
    """
    获取配件价格

    Args:
        product_model: 产品型号 (如 "GE150", "GE200")
        part_name: 配件名称 (如 "电源适配器", "脚踏开关")

    Returns:
        包含价格信息的字典，如 {"price": 50, "currency": "USD"}，未找到返回 None
    """
    config = _load_config()
    part_prices = config.get('part_prices', {})

    # 标准化产品型号（去除空格）
    normalized_model = product_model.strip()

    # 尝试精确匹配
    if normalized_model in part_prices:
        prices = part_prices[normalized_model]
        # 标准化配件名称
        normalized_part = part_name.strip()

        if normalized_part in prices:
            return {
                "price": prices[normalized_part],
                "currency": "USD",
                "product_model": normalized_model,
                "part_name": normalized_part
            }

    # 模糊匹配配件名称
    for model, prices in part_prices.items():
        if model.strip() == normalized_model:
            for stored_part, price in prices.items():
                # 简单的模糊匹配：检查是否包含对方
                if part_name.strip() in stored_part or stored_part in part_name.strip():
                    return {
                        "price": price,
                        "currency": "USD",
                        "product_model": model,
                        "part_name": stored_part
                    }

    return None

def set_part_price(product_model: str, part_name: str, price: float, currency: str = "USD") -> bool:
    """
    设置配件价格

    Args:
        product_model: 产品型号
        part_name: 配件名称
        price: 价格
        currency: 货币（默认 USD）

    Returns:
        是否成功
    """
    config = _load_config()

    if 'part_prices' not in config:
        config['part_prices'] = {}

    if product_model not in config['part_prices']:
        config['part_prices'][product_model] = {}

    config['part_prices'][product_model][part_name] = price

    # 保存回配置文件
    config_path = os.path.join(os.getcwd(), "config.yml")
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        global _config
        _config = config  # 更新缓存
        return True
    except Exception as e:
        logger.error(f"Failed to save config.yml: {e}")
        return False

def get_all_prices_for_model(product_model: str) -> Optional[Dict[str, float]]:
    """
    获取指定型号的所有配件价格

    Args:
        product_model: 产品型号

    Returns:
        配件价格字典，未找到返回 None
    """
    config = _load_config()
    part_prices = config.get('part_prices', {})
    normalized_model = product_model.strip()

    if normalized_model in part_prices:
        return part_prices[normalized_model]

    return None
