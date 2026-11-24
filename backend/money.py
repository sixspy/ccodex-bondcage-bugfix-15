"""分位舍入单一口径（甲路径唯一实现点，见 docs/分位舍入命运纪要_2026-11-24.md）。

约定分位：分（2 位小数），舍入法 ROUND_HALF_UP。
一切金额写入名册前必须经 to_fen 统一；精度侧只有写入侧这一侧。
绕过本模块落库金额即「分位舍入偏航」，须拒写。
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException

FEN_QUANT = Decimal("0.01")
# 仅吸收 REAL 存储的浮点表示误差，不构成第二精度侧
EPSILON = 1e-6


def to_fen(value) -> float:
    """统一到分（2 位，HALF_UP）。写入名册前唯一合法舍入入口。"""
    return float(Decimal(str(value)).quantize(FEN_QUANT, rounding=ROUND_HALF_UP))


def is_fen_aligned(value) -> bool:
    """存量值是否已落在分位上（对账检出历史漂移用）。"""
    return abs(float(value) - to_fen(value)) < 1e-9


def require_fen_amount(value, label: str = "金额") -> float:
    """统一到分；统一到分后为零（零改）即拒写，由调用方原子回滚草稿。"""
    fen = to_fen(value)
    if fen <= 0:
        raise HTTPException(400, f"{label}统一到分位后为零，零改拒写")
    return fen
