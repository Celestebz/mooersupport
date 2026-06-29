"""
配件价格数据库模块
优先从 SQLite 数据库读取，YAML 作为 fallback 和数据迁移源。
"""
import os
import yaml
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_config = None
_db = None


def _get_db():
    """延迟加载 DatabaseHandler（避免循环导入）"""
    global _db
    if _db is None:
        try:
            from database import DatabaseHandler
            _db = DatabaseHandler()
        except Exception as e:
            logger.warning(f"Cannot init DB handler, falling back to YAML: {e}")
    return _db


def _load_config() -> Dict[str, Any]:
    """加载 YAML 配置文件（仅用于 fallback 和数据迁移）"""
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


def _migrate_yaml_to_db():
    """将 YAML 中的价格数据迁移到 DB（一次性）"""
    config = _load_config()
    part_prices = config.get('part_prices', {})
    if not part_prices:
        return

    db = _get_db()
    if db is None:
        return

    migrated = 0
    for model, parts in part_prices.items():
        for part_name, price in parts.items():
            if db.upsert_part_price(model, part_name, float(price)):
                migrated += 1

    if migrated > 0:
        logger.info(f"Migrated {migrated} part prices from YAML to DB")


def get_part_price(product_model: str, part_name: str) -> Optional[Dict[str, Any]]:
    """
    获取配件价格（优先 DB，回退 YAML）

    Args:
        product_model: 产品型号 (如 "GE150", "GE200")
        part_name: 配件名称 (如 "power adapter", "screen")

    Returns:
        包含价格信息的字典，未找到返回 None
    """
    # 1. 尝试从 DB 查询
    db = _get_db()
    if db is not None:
        try:
            result = db.get_part_price(product_model, part_name)
            if result:
                return {
                    "price": result["price"],
                    "currency": result.get("currency", "USD"),
                    "product_model": result["product_model"],
                    "part_name": result["part_name"]
                }

            # 精确匹配失败，尝试模糊匹配
            all_prices = db.get_all_prices_for_model(product_model)
            if all_prices:
                normalized_part = part_name.strip().lower()
                for stored_part, price in all_prices.items():
                    if normalized_part in stored_part.lower() or stored_part.lower() in normalized_part:
                        return {
                            "price": price,
                            "currency": "USD",
                            "product_model": product_model.strip(),
                            "part_name": stored_part
                        }
        except Exception as e:
            logger.warning(f"DB query failed, falling back to YAML: {e}")

    # 2. Fallback: 从 YAML 查询
    config = _load_config()
    part_prices = config.get('part_prices', {})
    normalized_model = product_model.strip()

    if normalized_model in part_prices:
        prices = part_prices[normalized_model]
        normalized_part = part_name.strip()
        if normalized_part in prices:
            return {
                "price": prices[normalized_part],
                "currency": "USD",
                "product_model": normalized_model,
                "part_name": normalized_part
            }

    # 模糊匹配（YAML）
    for model, prices in part_prices.items():
        if model.strip() == normalized_model:
            for stored_part, price in prices.items():
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
    设置配件价格（写 DB，不复写 YAML）

    Args:
        product_model: 产品型号
        part_name: 配件名称
        price: 价格
        currency: 货币（默认 USD）

    Returns:
        是否成功
    """
    db = _get_db()
    if db is not None:
        try:
            return db.upsert_part_price(product_model, part_name, price, currency)
        except Exception as e:
            logger.error(f"Failed to write to DB: {e}")

    # Fallback: 写 YAML（旧行为）
    config = _load_config()
    if 'part_prices' not in config:
        config['part_prices'] = {}
    if product_model not in config['part_prices']:
        config['part_prices'][product_model] = {}
    config['part_prices'][product_model][part_name] = price

    config_path = os.path.join(os.getcwd(), "config.yml")
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        global _config
        _config = config
        return True
    except Exception as e:
        logger.error(f"Failed to save config.yml: {e}")
        return False


def get_all_prices_for_model(product_model: str) -> Optional[Dict[str, float]]:
    """
    获取指定型号的所有配件价格（优先 DB）

    Args:
        product_model: 产品型号

    Returns:
        配件价格字典，未找到返回 None
    """
    db = _get_db()
    if db is not None:
        try:
            result = db.get_all_prices_for_model(product_model)
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"DB query failed: {e}")

    # Fallback: YAML
    config = _load_config()
    part_prices = config.get('part_prices', {})
    normalized_model = product_model.strip()
    if normalized_model in part_prices:
        return part_prices[normalized_model]

    return None


def list_all_prices() -> list:
    """列出所有配件价格（仅 DB）"""
    db = _get_db()
    if db is not None:
        try:
            return db.list_all_part_prices()
        except Exception as e:
            logger.error(f"Failed to list prices from DB: {e}")
    return []


def add_price(product_model: str, part_name: str, price: float, currency: str = "USD") -> bool:
    """添加新配件价格（仅 DB）"""
    return set_part_price(product_model, part_name, price, currency)


def delete_price(price_id: int) -> bool:
    """删除配件价格（仅 DB）"""
    db = _get_db()
    if db is not None:
        try:
            return db.delete_part_price(price_id)
        except Exception as e:
            logger.error(f"Failed to delete price: {e}")
    return False


# ── 启动时自动迁移 YAML 数据到 DB ──
try:
    _migrate_yaml_to_db()
except Exception:
    pass
