"""
Nado Trader - Script de Trading

Importa a integração com a Nado DEX e executa o fluxo de exemplo.

Uso:
    python main.py

Configuração (.env):
    NADO_OWNER_PRIVATE_KEY=0x...
    NADO_PRIVATE_KEY=0x...  # alias legado
    PRIVATE_KEY=0x...       # alias generico legado opcional
    NADO_LINKED_SIGNER_PRIVATE_KEY=0x...
    NADO_NETWORK=testnet   # ou mainnet
    TRADE_AUTOMATIZADO_CONFIRM_LIVE=true  # alias legado: DELTA_NEUTRAL_CONFIRM_LIVE=true
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

# Este modulo e executado tanto como `workspace.nado.example` quanto direto de
# dentro da propria pasta (o `from nado_integration import` abaixo depende
# disso). A raiz do repo entra no path para que o vocabulario de booleano venha
# de `workspace.config` nos dois modos, em vez de uma copia local.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from workspace.config import coerce_bool  # noqa: E402
from nado_integration import NadoTrader, BTC_PERP, logger  # noqa: E402

# ─── Configuração de logging ─────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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


def _load_nado_owner_private_key() -> str | None:
    return (
        _clean_literal_env(os.environ.get("NADO_OWNER_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("NADO_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("PRIVATE_KEY"))
    )


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
    live_confirmed = _env_bool("TRADE_AUTOMATIZADO_CONFIRM_LIVE", False) or _env_bool("DELTA_NEUTRAL_CONFIRM_LIVE", False)

    if not owner_private_key:
        logger.error("❌ Configure NADO_OWNER_PRIVATE_KEY no env/secret manager")
        return
    if require_linked_signer and not linked_signer_private_key:
        logger.error("❌ Configure NADO_LINKED_SIGNER_PRIVATE_KEY para operar live na subconta")
        return

    # ─── Inicializar o trader ─────────────────────────────────
    trader = NadoTrader(
        owner_private_key,
        network,
        subaccount_name=subaccount_name,
        linked_signer_private_key=linked_signer_private_key,
        require_linked_signer=require_linked_signer,
    )

    # ─── 1. Listar produtos disponíveis ──────────────────────
    logger.info("\n" + "=" * 50)
    logger.info(" PASSO 1: Listando produtos")
    logger.info("=" * 50)
    trader.get_all_products()

    # ─── 2. Consultar preço de mercado ───────────────────────
    logger.info("\n" + "=" * 50)
    logger.info(" PASSO 2: Preço do BTC-PERP")
    logger.info("=" * 50)
    btc_price = trader.get_market_price(BTC_PERP)

    # ─── 3. Ver orderbook ────────────────────────────────────
    logger.info("\n" + "=" * 50)
    logger.info(" PASSO 3: Orderbook BTC-PERP")
    logger.info("=" * 50)
    trader.get_orderbook(BTC_PERP, depth=5)

    # ─── 4. Info da subconta ─────────────────────────────────
    logger.info("\n" + "=" * 50)
    logger.info(" PASSO 4: Info da subconta")
    logger.info("=" * 50)
    trader.get_subaccount_info()

    # ─── 5. Inspeção do SDK (debug) ──────────────────────────
    # trader.inspect_sdk()

    # ─── 6. Ordem limitada ───────────────────────────────────
    # ⚠️  DESCOMENTE PARA EXECUTAR

    # logger.info("\n" + "=" * 50)
    # logger.info(" PASSO 6: Ordem Limit de compra")
    # logger.info("=" * 50)
    # buy_price = btc_price["mid_price"] * 0.95
    # trader.place_limit_order(
    #     product_id=BTC_PERP,
    #     price=68000,
    #     quantity=0.002,  # min_size BTC-PERP = $100 notional
    #     is_buy=False,
    # )

    # ─── 7. Ver ordens abertas ───────────────────────────────
    # trader.get_open_orders(BTC_PERP)
    # trader.cancel_all_orders(BTC_PERP)

    # ─── Exemplo: Grid Trading ───────────────────────────────
    # ⚠️  DESCOMENTE PARA EXECUTAR
    #
    # trader.grid_trading(
    #     product_id=BTC_PERP,
    #     lower_price=btc_price["mid_price"] * 0.97,
    #     upper_price=btc_price["mid_price"] * 1.03,
    #     num_grids=6,
    #     total_quantity=0.006,  # 0.002/ordem, acima do min_size $100
    # )

    # ─── Exemplo: Stop Loss e Take Profit ─────────────────────
    # ⚠️  DESCOMENTE PARA EXECUTAR (requer posição aberta)
    #
    # trader.place_stop_loss(
    #     product_id=BTC_PERP,
    #     quantity=0.002,
    #     trigger_price=71000,
    #     is_long=False,
    #     slippage_pct=0.01,
    # )
    # trader.place_take_profit(
    #     product_id=BTC_PERP,
    #     quantity=0.002,
    #     trigger_price=66000,
    #     is_long=False,
    #     slippage_pct=0.01,
    # )

    # ─── Exemplo: Ordem limit + SL + TP (bracket) ──────────────
    # Abre ordem limit e coloca SL/TP vinculados (ativam quando preencher)
    if live_confirmed:
        trader.place_limit_order_with_tp_sl(
            product_id=BTC_PERP,
            price=70000,
            quantity=0.002,
            stop_loss=67000,
            take_profit=73000,
            is_buy=True,
        )
    else:
        logger.warning("Ordem de exemplo bloqueada: defina TRADE_AUTOMATIZADO_CONFIRM_LIVE=true apenas na execução live aprovada (alias legado: DELTA_NEUTRAL_CONFIRM_LIVE=true).")

    # ─── Exemplo: Ordem market + SL + TP (bracket) ─────────────
    # trader.place_market_order_with_tp_sl(
    #     product_id=BTC_PERP, quantity=0.002,
    #     stop_loss=btc_price["mid_price"] * 0.95,
    #     take_profit=btc_price["mid_price"] * 1.05,
    #     is_buy=True,
    # )

    # ─── Exemplo: Ordem a mercado ─────────────────────────────
    # trader.place_market_order(product_id=BTC_PERP, quantity=0.002, is_buy=True)

    logger.info("\n✅ Script finalizado com sucesso!")
    logger.info("💡 Descomente as seções de trading para executar ordens.")


if __name__ == "__main__":
    main()
