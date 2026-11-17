"""Dinheiro, taxas e datas — conversões na fronteira da API (docs/04-api.md §1).

Dinheiro trafega como string decimal com duas casas ("9336.00"), taxa como
fração decimal em string ("0.041667"). Nunca float, em nenhum ponto.
"""
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Optional

from pydantic import BeforeValidator

CENTAVO = Decimal("0.01")
_RE_DINHEIRO = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def dinheiro(v) -> Optional[str]:
    """Decimal -> '1234.50' (ROUND_HALF_UP, RN-10)."""
    if v is None:
        return None
    return str(Decimal(v).quantize(CENTAVO, rounding=ROUND_HALF_UP))


def taxa(v, casas: int = 6) -> Optional[str]:
    if v is None:
        return None
    return str(Decimal(v).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP))


def dias(v) -> Optional[str]:
    """Prazo em dias com uma casa: '27.0'."""
    return taxa(v, 1)


def data_iso(v: Optional[date]) -> Optional[str]:
    return v.isoformat() if v else None


def brl(v) -> str:
    """Decimal -> 'R$ 111.810,32' para mensagens."""
    s = f"{Decimal(v).quantize(CENTAVO, rounding=ROUND_HALF_UP):,.2f}"
    return "R$ " + s.replace(",", "_").replace(".", ",").replace("_", ".")


def br_decimal(v, casas: int = 2) -> str:
    """Decimal -> '4279,00' para o CSV do Excel brasileiro."""
    q = Decimal(v).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    return str(q).replace(".", ",")


def br_data(v: Optional[date]) -> str:
    return v.strftime("%d/%m/%Y") if v else ""


# --- entrada ---------------------------------------------------------------

def _parse_dinheiro(v):
    # número JSON é recusado de propósito: 9336.00 chega como 9336 e 0.1 chega torto
    if not isinstance(v, str):
        raise ValueError('dinheiro precisa vir como string decimal, ex.: "9336.00"')
    s = v.strip()
    if not _RE_DINHEIRO.match(s):
        raise ValueError('formato inválido: use ponto decimal e até 2 casas, ex.: "9336.00"')
    return Decimal(s)


def _parse_fracao(v):
    if not isinstance(v, str):
        raise ValueError('percentual precisa vir como fração em string, ex.: "0.0400"')
    try:
        d = Decimal(v.strip())
    except InvalidOperation:
        raise ValueError("fração decimal inválida") from None
    if not (Decimal(0) <= d < Decimal(1)):
        raise ValueError("fração precisa estar entre 0 e 1 (0.0400 = 4%)")
    if d.as_tuple().exponent < -4:
        raise ValueError("no máximo 4 casas (0.0400 = 4%)")
    return d


Dinheiro = Annotated[Decimal, BeforeValidator(_parse_dinheiro)]
Fracao = Annotated[Decimal, BeforeValidator(_parse_fracao)]
