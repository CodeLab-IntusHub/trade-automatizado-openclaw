"""
Auto Trade Nado - Tomada de decisão + execução na Nado DEX

Usa o CryptoDecisionEngine (decision.py) para avaliar oportunidades em exchanges
(Binance, Bybit, etc.) e, quando houver oportunidade válida em um ativo listado
na Nado, abre a ordem na Nado com SL e TP via nado_integration.

Uso:
    python auto_trade_nado.py

Configuração (.env):
    NADO_OWNER_PRIVATE_KEY=0x...
    NADO_PRIVATE_KEY=0x...  # alias legado
    PRIVATE_KEY=0x...       # alias generico legado opcional
    NADO_LINKED_SIGNER_PRIVATE_KEY=0x...
    NADO_NETWORK=testnet
    TRADE_AUTOMATIZADO_CONFIRM_LIVE=true  # alias legado: DELTA_NEUTRAL_CONFIRM_LIVE=true

Variáveis opcionais para o motor de decisão (podem ficar no .env ou no config abaixo):
    CERTAINTY=70  # também aceita 0.70
    VOLUME_ORDER=100
    MAX_OPPORTUNITIES=3
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

from ..config import coerce_bool
from .decision import CryptoDecisionEngine, DecisionResult
from .nado_integration import NadoTrader, get_nado_fees, logger

# Mapeamento símbolo→product_id é obtido dinamicamente via trader.get_symbol_to_product_map()
# (IDs variam entre testnet/mainnet; evita ARB→HYPE, OP→ZEC por IDs hardcoded errados)

# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_decision_config(symbols: list) -> dict:
    """Config do motor de decisão (env + defaults). symbols vem da lista de produtos da Nado."""
    fee_tier = os.environ.get("NADO_FEE_TIER", "entry").strip().lower()
    maker_fee, taker_fee = get_nado_fees(fee_tier)
    use_market = os.environ.get("ORDER_TYPE", "market").strip().lower() == "market"
    # Market orders: taker em abertura e fechamento (SL/TP); limit: maker abertura, taker fechamento
    use_taker_for_entry = use_market
    return {
        "CERTAINTY": _load_certainty_env(),
        "VOLUME_ORDER": float(os.environ.get("VOLUME_ORDER", "100")),
        "SLIPPAGE_BPS": int(os.environ.get("SLIPPAGE_BPS", "100")),
        "AUTO_DEPOSIT_ENABLED": os.environ.get("AUTO_DEPOSIT_ENABLED", "false").lower() == "true",
        "AUTO_DEPOSIT_MIN_BALANCE": float(os.environ.get("AUTO_DEPOSIT_MIN_BALANCE", "100")),
        "AUTO_DEPOSIT_AMOUNT": float(os.environ.get("AUTO_DEPOSIT_AMOUNT", "200")),
        "AUTO_WITHDRAW_ENABLED": os.environ.get("AUTO_WITHDRAW_ENABLED", "false").lower() == "true",
        "AUTO_WITHDRAW_MIN_BALANCE": float(os.environ.get("AUTO_WITHDRAW_MIN_BALANCE", "50")),
        "AUTO_WITHDRAW_LEAVE_ON_NADO": float(os.environ.get("AUTO_WITHDRAW_LEAVE_ON_NADO", "100")),
        "MAX_PERCENT_LOSS": os.environ.get("MAX_PERCENT_LOSS", "1%"),
        "MAX_PERCENT_PROFIT": os.environ.get("MAX_PERCENT_PROFIT", "2%"),
        "UNIQUE_TREND": _load_unique_trend_env(),
        "MAX_OPPORTUNITIES": int(os.environ.get("MAX_OPPORTUNITIES", "10")),
        "EXCHANGES": _parse_list(os.environ.get("EXCHANGES", "binance")),
        "SYMBOLS": symbols,
        "MAKER_FEE": maker_fee,
        "TAKER_FEE": taker_fee,
        "USE_TAKER_FOR_ENTRY": use_taker_for_entry,
    }


def _parse_list(s: str) -> list:
    if not s or not s.strip():
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _env_bool(name: str, default: bool) -> bool:
    """Portao booleano com o vocabulario compartilhado (`workspace.config`).

    A copia anterior era `raw.lower() in {"1","true","yes","sim"}` -- todo o
    resto virava `False`. Aqui isso importa especialmente:
    `NADO_REQUIRE_LINKED_SIGNER` vale `True` por padrao, entao um valor nao
    reconhecido **desligava** a verificacao de linked signer. E `on`, `s` e `y`
    -- validos no vocabulario que o `sandbox` usa -- faziam exatamente isso.
    """
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    return coerce_bool(raw, name)


def _clean_literal_env(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.split("#", 1)[0].strip()
    return cleaned or None


def _load_certainty_env(name: str = "CERTAINTY", default: int = 70) -> int:
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    cleaned = raw.rstrip("%")
    value = float(cleaned)
    if value <= 1:
        value *= 100
    return int(round(value))


def _load_unique_trend_env(name: str = "UNIQUE_TREND") -> str:
    raw = (_clean_literal_env(os.environ.get(name)) or "").upper()
    if raw in {"LONG", "SHORT"}:
        return raw
    return ""


def _load_nado_owner_private_key() -> str | None:
    return (
        _clean_literal_env(os.environ.get("NADO_OWNER_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("NADO_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("PRIVATE_KEY"))
    )


def _live_confirmed() -> bool:
    return _env_bool("TRADE_AUTOMATIZADO_CONFIRM_LIVE", False) or _env_bool("DELTA_NEUTRAL_CONFIRM_LIVE", False)


def nado_product_for_opportunity(opp: DecisionResult, symbol_to_product: dict) -> Optional[int]:
    """Retorna o product_id Nado para a oportunidade, ou None se não existir."""
    return symbol_to_product.get(opp.symbol)


def open_opportunity_on_nado(
    trader: NadoTrader,
    opp: DecisionResult,
    symbol_to_product: dict,
    *,
    volume_order_usd: float,
    use_market: bool = True,
    slippage_bps: int = 50,
    slippage_pct_sl_tp: float = 0.01,
) -> bool:
    """
    Abre na Nado a posição correspondente à oportunidade (com SL e TP).

    Usa o preço da Nado para calcular quantidade (volume_order_usd) e para escalar
    SL/TP, evitando tamanho errado quando a exchange de decisão tem preço diferente.

    use_market: True = ordem a mercado (entrada imediata), False = ordem limit no entry escalado.
    Retorna True se a ordem foi enviada com sucesso.
    """
    product_id = nado_product_for_opportunity(opp, symbol_to_product)
    if product_id is None:
        logger.warning("⚠️ Símbolo %s não tem produto PERP na Nado, ignorando.", opp.symbol)
        return False

    nado_mid = trader.get_market_mid_price(product_id)
    if nado_mid <= 0:
        logger.warning("⚠️ Preço mid da Nado inválido para produto %s.", product_id)
        return False

    # Tamanho pela Nado: notional ≈ volume_order_usd
    quantity = volume_order_usd / nado_mid
    quantity = trader.round_quantity_to_increment(product_id, quantity)
    if quantity <= 0:
        logger.warning(
            "⚠️ Quantidade arredondada para o size_increment da Nado é 0 (notional=%.0f USD), ignorando.",
            volume_order_usd,
        )
        return False

    # Escalar SL/TP do preço da decisão para o preço da Nado (mesmo % de risco/recompensa)
    if opp.entry_price and opp.entry_price > 0:
        scale = nado_mid / opp.entry_price
        stop_loss = opp.stop_loss * scale
        take_profit = opp.take_profit * scale
        entry_price = opp.entry_price * scale if not use_market else nado_mid
    else:
        stop_loss = opp.stop_loss
        take_profit = opp.take_profit
        entry_price = nado_mid

    is_buy = opp.side == "long"

    if use_market:
        logger.info(
            "⚡ Abrindo na Nado (market): %s %s | qty=%s (~%.0f USD) | SL=%.2f TP=%.2f",
            opp.symbol,
            opp.side.upper(),
            quantity,
            quantity * nado_mid,
            stop_loss,
            take_profit,
        )
        res = trader.place_market_order_with_tp_sl(
            product_id=product_id,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            is_buy=is_buy,
            slippage_bps=slippage_bps,
            slippage_pct=slippage_pct_sl_tp,
        )
    else:
        logger.info(
            "📋 Abrindo na Nado (limit): %s %s @ %.2f | qty=%s | SL=%.2f TP=%.2f",
            opp.symbol,
            opp.side.upper(),
            entry_price,
            quantity,
            stop_loss,
            take_profit,
        )
        res = trader.place_limit_order_with_tp_sl(
            product_id=product_id,
            price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            is_buy=is_buy,
            slippage_pct=slippage_pct_sl_tp,
        )

    return res is not None


def main():
    load_dotenv()
    owner_private_key = _load_nado_owner_private_key()
    linked_signer_private_key = _clean_literal_env(os.environ.get("NADO_LINKED_SIGNER_PRIVATE_KEY"))
    network = (
        _clean_literal_env(os.environ.get("NADO_NETWORK"))
        or _clean_literal_env(os.environ.get("NETWORK"))
        or "testnet"
    )
    subaccount_name = _clean_literal_env(os.environ.get("NADO_SUBACCOUNT_NAME")) or "default_1"
    require_linked_signer = _env_bool("NADO_REQUIRE_LINKED_SIGNER", True)

    if not owner_private_key:
        logger.error("❌ Configure NADO_OWNER_PRIVATE_KEY no env/secret manager")
        return
    if require_linked_signer and not linked_signer_private_key:
        logger.error("❌ Configure NADO_LINKED_SIGNER_PRIVATE_KEY para operar live na subconta")
        return
    if not _live_confirmed():
        logger.error("❌ Auto trade direto bloqueado: defina TRADE_AUTOMATIZADO_CONFIRM_LIVE=true apenas na execução live aprovada (alias legado: DELTA_NEUTRAL_CONFIRM_LIVE=true)")
        return

    # ─── Conecta na Nado e obtém lista de pares para buscar oportunidades ───
    trader = NadoTrader(
        owner_private_key,
        network,
        subaccount_name=subaccount_name,
        linked_signer_private_key=linked_signer_private_key,
        require_linked_signer=require_linked_signer,
    )
    symbol_to_product = trader.get_symbol_to_product_map()
    if not symbol_to_product:
        logger.warning("⚠️ Não foi possível obter produtos da Nado. Abortando.")
        return

    nado_symbols = sorted(symbol_to_product.keys())
    logger.info("📋 Buscando oportunidades nos %d pares da Nado: %s",
                len(nado_symbols), nado_symbols)

    # ─── Motor de decisão usa a lista da Nado (sem lista manual) ────────────
    config = get_decision_config(symbols=nado_symbols)
    logger.info("📊 Inicializando motor de decisão (CERTAINTY=%s, VOLUME=%s)...",
                config["CERTAINTY"], config["VOLUME_ORDER"])
    engine = CryptoDecisionEngine(config)

    logger.info("🔍 Avaliando oportunidades em %s...", config["EXCHANGES"])
    opportunities = engine.evaluate_all_pairs()

    if not opportunities:
        logger.info("Nenhuma oportunidade acima do threshold. Nada a executar na Nado.")
        return

    # Oportunidades já vêm apenas dos pares da Nado (e que existem na Binance)
    nado_opportunities = opportunities

    # ─── Depósito automático (se configurado) ───────────────────────────────
    if config.get("AUTO_DEPOSIT_ENABLED"):
        trader.auto_deposit_if_needed(
            min_balance=config["AUTO_DEPOSIT_MIN_BALANCE"],
            deposit_amount=config["AUTO_DEPOSIT_AMOUNT"],
        )

    # Por padrão executa apenas a melhor oportunidade (maior certeza já vem primeiro)
    use_market = os.environ.get("ORDER_TYPE", "market").strip().lower() == "market"
    max_trades = int(os.environ.get("MAX_TRADES_PER_RUN", "1"))

    executed = 0
    volume_order_usd = config["VOLUME_ORDER"]
    for opp in nado_opportunities[:max_trades]:
        logger.info("🎯 Tentando executar: %s %s (certainty=%s%%)", opp.symbol, opp.side, opp.certainty)
        if open_opportunity_on_nado(
            trader,
            opp,
            symbol_to_product,
            volume_order_usd=volume_order_usd,
            use_market=use_market,
            slippage_bps=config.get("SLIPPAGE_BPS", 100),
        ):
            executed += 1
            logger.info("✅ Ordem enviada para %s %s.", opp.symbol, opp.side)
        else:
            logger.warning("Falha ao enviar ordem para %s %s.", opp.symbol, opp.side)

    if executed:
        logger.info("✅ Script finalizado. %s ordem(ns) enviada(s) na Nado.", executed)

    # ─── Saque automático (se configurado) ──────────────────────────────────
    if config.get("AUTO_WITHDRAW_ENABLED"):
        trader.auto_withdraw_if_needed(
            min_balance=config["AUTO_WITHDRAW_MIN_BALANCE"],
            leave_on_nado=config["AUTO_WITHDRAW_LEAVE_ON_NADO"],
        )

    if not executed:
        logger.info("Nenhuma ordem executada nesta run.")


if __name__ == "__main__":
    main()
