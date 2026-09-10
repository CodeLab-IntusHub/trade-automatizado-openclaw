"""
Crypto Trading Decision Engine - CCXT Version
Algoritmo de tomada de decisão multi-timeframe usando CCXT
Baseado no algoritmo do backbot adaptado para exchanges com alto volume

Exchanges suportadas: Binance, MEXC, Bybit, OKX, KuCoin, etc.
"""

import ccxt
import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class TimeframeIndicators:
    """Indicadores por timeframe"""
    timeframe: str
    close: float
    ema9: float
    ema21: float
    ema_diff: float
    ema_diff_pct: float
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    vwap: float
    volume_ratio: float  # Volume atual / SMA(20)
    volume_trend: str  # 'increasing', 'decreasing', 'flat'
    price_slope: float


@dataclass
class DecisionResult:
    """Resultado da tomada de decisão"""
    exchange: str
    symbol: str
    side: str  # 'long' or 'short'
    certainty: float  # 0-100
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_usd: float
    reward_usd: float
    rr_ratio: float
    indicators: Dict[str, float]


class CryptoDecisionEngine:
    """Motor de decisão usando CCXT"""

    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger('CryptoDecisionEngine')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        # Configurações de decisão
        self.certainty_threshold = config.get('CERTAINTY', 70)
        self.volume_order = config.get('VOLUME_ORDER', 100)
        self.max_percent_loss = self._parse_percent(config.get('MAX_PERCENT_LOSS', '1%'))
        self.max_percent_profit = self._parse_percent(config.get('MAX_PERCENT_PROFIT', '2%'))
        self.unique_trend = config.get('UNIQUE_TREND', '').upper()

        # Configurações de exchanges
        raw_exchanges = config.get('EXCHANGES', ['binance', 'mexc'])
        if isinstance(raw_exchanges, str):
            raw_exchanges = raw_exchanges.split(',')
        self.exchanges_config = [str(item).strip().lower() for item in raw_exchanges if str(item).strip()]
        self.symbols = config.get('SYMBOLS', ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'])
        self.timeframes = ['1m', '5m', '15m']

        # Inicializar exchanges
        self.exchanges = {}
        normalized_exchanges = []
        for exchange_id in self.exchanges_config:
            try:
                normalized_id = exchange_id
                if exchange_id in {'nado', 'nado-dex', 'nado_dex'}:
                    self.logger.warning("Exchange nado nao e fonte CCXT; usando apenas venues CCXT para sinais.")
                    continue
                if exchange_id in {'kraken', 'kraken-futures', 'kraken_futures', 'krakenfutures'}:
                    normalized_id = 'krakenfutures'
                    self.exchanges[normalized_id] = ccxt.krakenfutures({
                        'enableRateLimit': True,
                    })
                elif exchange_id == 'kraken-spot':
                    normalized_id = 'kraken'
                    self.exchanges[normalized_id] = ccxt.kraken({
                        'enableRateLimit': True,
                    })
                elif exchange_id == 'binance':
                    self.exchanges[normalized_id] = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'future'}
                    })
                elif exchange_id == 'mexc':
                    self.exchanges[normalized_id] = ccxt.mexc({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'swap'}
                    })
                elif exchange_id == 'bybit':
                    self.exchanges[normalized_id] = ccxt.bybit({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'linear'}
                    })
                elif exchange_id == 'okx':
                    self.exchanges[normalized_id] = ccxt.okx({
                        'enableRateLimit': True
                    })
                elif exchange_id == 'kucoin':
                    self.exchanges[normalized_id] = ccxt.kucoin({
                        'enableRateLimit': True
                    })
                else:
                    exchange_cls = getattr(ccxt, exchange_id, None)
                    if exchange_cls is None:
                        self.logger.warning(f"Exchange {exchange_id} não existe no CCXT instalado")
                        continue
                    market_type = str(self.config.get('CEX_MARKET_TYPE', self.config.get('CEX_DEFAULT_TYPE', 'swap'))).lower()
                    self.exchanges[normalized_id] = exchange_cls({
                        'enableRateLimit': True,
                        'options': {'defaultType': market_type},
                    })

                normalized_exchanges.append(normalized_id)
                self.logger.info(f"✅ Exchange {normalized_id} inicializada")

            except Exception as e:
                self.logger.error(f"❌ Erro ao inicializar {exchange_id}: {e}")
        self.exchanges_config = normalized_exchanges

    def _parse_percent(self, value: str) -> float:
        """Converte '1%' para 0.01"""
        if isinstance(value, str):
            return float(value.replace('%', '')) / 100
        return float(value)

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """Calcula EMA exponencial"""
        ema = []
        multiplier = 2 / (period + 1)

        for i, price in enumerate(prices):
            if i < period:
                ema.append(np.mean(prices[:i+1]))
            else:
                ema.append((price - ema[-1]) * multiplier + ema[-1])

        return ema

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calcula RSI"""
        if len(prices) < period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi)

    def _calculate_macd(self, prices: List[float], fast: int = 12,
                      slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """Calcula MACD"""
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)

        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
        macd_signal = self._calculate_ema(macd_line, signal)
        macd_histogram = [m - s for m, s in zip(macd_line, macd_signal)]

        return macd_line[-1], macd_signal[-1], macd_histogram[-1]

    def _calculate_bollinger(self, prices: List[float], period: int = 20,
                           std_dev: int = 2) -> Tuple[float, float, float]:
        """Calcula Bollinger Bands"""
        if len(prices) < period:
            return prices[-1], prices[-1], prices[-1]

        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])

        upper = sma + (std_dev * std)
        middle = sma
        lower = sma - (std_dev * std)

        return upper, middle, lower

    def _calculate_vwap(self, df: pd.DataFrame) -> float:
        """Calcula VWAP (Volume Weighted Average Price)"""
        if len(df) < 1:
            return df['close'].iloc[-1]

        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).sum() / df['volume'].sum()

        return float(vwap)

    def _calculate_indicators(self, df: pd.DataFrame,
                          timeframe: str) -> TimeframeIndicators:
        """Calcula todos os indicadores para um timeframe"""
        if df is None or len(df) < 30:
            return None

        closes = df['close'].tolist()
        volumes = df['volume'].tolist()

        # EMA
        ema9 = self._calculate_ema(closes, 9)[-1]
        ema21 = self._calculate_ema(closes, 21)[-1]
        ema_diff = ema9 - ema21
        ema_diff_pct = (ema_diff / ema21 * 100) if ema21 != 0 else 0

        # RSI
        rsi = self._calculate_rsi(closes, 14)

        # MACD
        macd, macd_signal, macd_histogram = self._calculate_macd(closes)

        # Bollinger
        bb_upper, bb_middle, bb_lower = self._calculate_bollinger(closes)

        # VWAP
        vwap = self._calculate_vwap(df)

        # Volume ratio
        volume_sma20 = np.mean(volumes[-20:])
        volume_ratio = volumes[-1] / volume_sma20 if volume_sma20 > 0 else 1

        # Volume trend
        recent_volumes = volumes[-5:]
        if recent_volumes[-1] > recent_volumes[-5]:
            volume_trend = 'increasing'
        elif recent_volumes[-1] < recent_volumes[-5]:
            volume_trend = 'decreasing'
        else:
            volume_trend = 'flat'

        # Price slope
        recent_closes = closes[-5:]
        slope = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0]

        return TimeframeIndicators(
            timeframe=timeframe,
            close=closes[-1],
            ema9=ema9,
            ema21=ema21,
            ema_diff=ema_diff,
            ema_diff_pct=ema_diff_pct,
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            bollinger_upper=bb_upper,
            bollinger_middle=bb_middle,
            bollinger_lower=bb_lower,
            vwap=vwap,
            volume_ratio=volume_ratio,
            volume_trend=volume_trend,
            price_slope=slope
        )

    def _fetch_ohlcv(self, exchange_id: str, symbol: str,
                     timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Busca dados OHLCV via CCXT"""
        if exchange_id not in self.exchanges:
            self.logger.error(f"Exchange {exchange_id} não inicializada")
            return None

        exchange = self.exchanges[exchange_id]

        try:
            # Converter timeframe CCXT
            ccxt_timeframe = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m'
            }.get(timeframe, timeframe)

            # Buscar candles
            ohlcv = exchange.fetch_ohlcv(
                symbol,
                timeframe=ccxt_timeframe,
                limit=limit
            )

            # Converter para DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')

            self.logger.info(f"📊 {exchange_id} {symbol} {timeframe}: {len(df)} candles")

            return df

        except Exception as e:
            self.logger.error(f"❌ Erro ao buscar dados {exchange_id} {symbol}: {e}")
            return None

    def score_side(self, tf1m: TimeframeIndicators, tf5m: TimeframeIndicators,
                 tf15m: TimeframeIndicators, is_long: bool) -> int:
        """
        Calcula score para LONG ou SHORT baseado em 9 fatores.
        Retorna score de 0-9 (será convertido para % depois).
        """
        score = 0
        total_factors = 9

        # Fator 1: EMA 15m - Tendência de longo prazo
        if is_long:
            if tf15m.ema9 > tf15m.ema21:
                score += 1
        else:
            if tf15m.ema9 < tf15m.ema21:
                score += 1

        # Fator 2: EMA 5m - Tendência de médio prazo
        if is_long:
            if tf5m.ema9 > tf5m.ema21:
                score += 1
        else:
            if tf5m.ema9 < tf5m.ema21:
                score += 1

        # Fator 3: RSI 5m - Momentum
        if is_long:
            if tf5m.rsi > 55:  # Compra em tendência
                score += 1
        else:
            if tf5m.rsi < 45:  # Venda em tendência
                score += 1

        # Fator 4: MACD 5m - Cruzamento
        if is_long:
            if tf5m.macd > tf5m.macd_signal:
                score += 1
        else:
            if tf5m.macd < tf5m.macd_signal:
                score += 1

        # Fator 5: Bollinger 1m - Posição relativa
        if is_long:
            if tf1m.close > tf1m.bollinger_middle:
                score += 1
        else:
            if tf1m.close < tf1m.bollinger_middle:
                score += 1

        # Fator 6: VWAP 1m - Média ponderada por volume
        if is_long:
            if tf1m.close > tf1m.vwap:
                score += 1
        else:
            if tf1m.close < tf1m.vwap:
                score += 1

        # Fator 7: Volume 1m - Confirmação
        if tf1m.volume_trend == 'increasing':
            score += 1

        # Fator 8: Price Slope 1m - Inclinação
        if is_long:
            if tf1m.price_slope > 0:
                score += 1
        else:
            if tf1m.price_slope < 0:
                score += 1

        # Fator 9: STACK 5m - Confluência completa
        if is_long:
            # LONG: RSI > 55, MACD > Signal, EMA9 > EMA21
            stack = (tf5m.rsi > 55 and
                     tf5m.macd > tf5m.macd_signal and
                     tf5m.ema9 > tf5m.ema21)
        else:
            # SHORT: RSI < 45, MACD < Signal, EMA9 < EMA21
            stack = (tf5m.rsi < 45 and
                     tf5m.macd < tf5m.macd_signal and
                     tf5m.ema9 < tf5m.ema21)

        if stack:
            score += 1

        return score

    def calculate_entry_price(self, mark_price: float, is_long: bool) -> float:
        """Calcula preço de entrada com pequeno slippage"""
        slippage_pct = 0.001  # 0.1% de slippage

        if is_long:
            entry = mark_price * (1 - slippage_pct)  # Compra ligeiramente abaixo
        else:
            entry = mark_price * (1 + slippage_pct)  # Venda ligeiramente acima

        return round(entry, 6)

    def calculate_stop_loss(self, entry: float, is_long: bool,
                        quantity: float, maker_fee: float, taker_fee: float) -> float:
        """Calcula stop loss com fees"""
        fee_open = entry * quantity * maker_fee
        fee_close = entry * quantity * taker_fee
        total_fee = fee_open + fee_close

        # Loss em USD = Volume * MAX_PERCENT_LOSS
        loss_usd = (entry * quantity) * self.max_percent_loss

        # Fee adicional no loss
        fee_total_loss = (fee_open + (fee_open * self.max_percent_loss)) / quantity

        if is_long:
            stop = entry - (entry * self.max_percent_loss) - fee_total_loss
        else:
            stop = entry + (entry * self.max_percent_loss) + fee_total_loss

        return round(stop, 6)

    def calculate_take_profit(self, entry: float, is_long: bool,
                           quantity: float, maker_fee: float, taker_fee: float) -> float:
        """Calcula take profit com fees"""
        fee_open = entry * quantity * maker_fee
        fee_close = entry * quantity * taker_fee
        total_fee = fee_open + fee_close

        # Profit em USD = Volume * MAX_PERCENT_PROFIT
        profit_usd = (entry * quantity) * self.max_percent_profit

        # Fee adicional no profit
        fee_total_profit = (fee_open + (fee_open * self.max_percent_profit)) / quantity

        if is_long:
            target = entry + (entry * self.max_percent_profit) + fee_total_profit
        else:
            target = entry - (entry * self.max_percent_profit) - fee_total_profit

        return round(target, 6)

    def evaluate_trade_opportunity(self, exchange_id: str, symbol: str,
                                 mark_price: float, maker_fee: float,
                                 taker_fee: float) -> Optional[DecisionResult]:
        """
        Avalia oportunidade de trade para um par em uma exchange.
        Retorna None se não houver oportunidade válida.
        """
        try:
            # Buscar dados dos 3 timeframes
            tf1m_df = self._fetch_ohlcv(exchange_id, symbol, '1m', limit=50)
            tf5m_df = self._fetch_ohlcv(exchange_id, symbol, '5m', limit=50)
            tf15m_df = self._fetch_ohlcv(exchange_id, symbol, '15m', limit=50)

            # Verificar se temos dados suficientes
            if tf1m_df is None or tf5m_df is None or tf15m_df is None:
                self.logger.warning(f"{exchange_id} {symbol}: Dados insuficientes")
                return None

            # Calcular indicadores para cada timeframe
            tf1m = self._calculate_indicators(tf1m_df, '1m')
            tf5m = self._calculate_indicators(tf5m_df, '5m')
            tf15m = self._calculate_indicators(tf15m_df, '15m')

            # Calcular scores para LONG e SHORT
            long_score = self.score_side(tf1m, tf5m, tf15m, is_long=True)
            short_score = self.score_side(tf1m, tf5m, tf15m, is_long=False)

            # Converter scores para porcentagem
            long_pct = int((long_score / 9) * 100)
            short_pct = int((short_score / 9) * 100)

            # Decidir lado
            is_long = long_score > short_score
            certainty = max(long_pct, short_pct)

            # Verificar se atingiu threshold
            if certainty < self.certainty_threshold:
                self.logger.debug(f"{exchange_id} {symbol}: Certainty {certainty}% < threshold {self.certainty_threshold}%")
                return None

            # Verificar UNIQUE_TREND
            if self.unique_trend:
                if self.unique_trend == 'LONG' and not is_long:
                    self.logger.debug(f"{exchange_id} {symbol}: Ignored by UNIQUE_TREND=LONG")
                    return None
                if self.unique_trend == 'SHORT' and is_long:
                    self.logger.debug(f"{exchange_id} {symbol}: Ignored by UNIQUE_TREND=SHORT")
                    return None

            # Calcular entry, stop, target, size
            entry = self.calculate_entry_price(mark_price, is_long)
            quantity = self.volume_order / entry
            stop = self.calculate_stop_loss(entry, is_long, quantity, maker_fee, taker_fee)
            target = self.calculate_take_profit(entry, is_long, quantity, maker_fee, taker_fee)

            # Calcular risk/reward
            if is_long:
                risk_usd = (entry - stop) * quantity
                reward_usd = (target - entry) * quantity
            else:
                risk_usd = (stop - entry) * quantity
                reward_usd = (entry - target) * quantity

            # Ratio R/R
            rr_ratio = reward_usd / risk_usd if risk_usd > 0 else 0

            side = 'long' if is_long else 'short'

            self.logger.info(f"✅ {exchange_id.upper()} {symbol} {side.upper()} @ ${entry:.6f}")
            self.logger.info(f"   Certainty: {certainty}% | Score: LONG={long_pct}% SHORT={short_pct}%")
            self.logger.info(f"   Stop: ${stop:.6f} | Target: ${target:.6f}")
            self.logger.info(f"   Risk: ${risk_usd:.2f} | Reward: ${reward_usd:.2f} | R:R: {rr_ratio:.2f}")

            return DecisionResult(
                exchange=exchange_id,
                symbol=symbol,
                side=side,
                certainty=certainty,
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                position_size=quantity,
                risk_usd=risk_usd,
                reward_usd=reward_usd,
                rr_ratio=rr_ratio,
                indicators={
                    'long_score': long_pct,
                    'short_score': short_pct,
                    'tf1m_rsi': tf1m.rsi,
                    'tf5m_rsi': tf5m.rsi,
                    'tf15m_rsi': tf15m.rsi,
                    'tf5m_macd': tf5m.macd,
                    'tf5m_ema_diff': tf5m.ema_diff_pct,
                    'tf15m_ema_diff': tf15m.ema_diff_pct
                }
            )

        except Exception as e:
            self.logger.error(f"❌ Erro ao avaliar {exchange_id} {symbol}: {e}")
            return None

    def evaluate_all_pairs(self) -> List[DecisionResult]:
        """
        Avalia todos os pares em todas as exchanges configuradas.
        Retorna oportunidades válidas ordenadas por certeza.
        """
        opportunities = []

        for exchange_id in self.exchanges_config:
            if exchange_id not in self.exchanges:
                continue

            exchange = self.exchanges[exchange_id]
            if self.config.get("MAKER_FEE") is not None and self.config.get("TAKER_FEE") is not None:
                maker_fee = self.config["MAKER_FEE"]
                taker_fee = self.config["TAKER_FEE"]
                if self.config.get("USE_TAKER_FOR_ENTRY"):
                    maker_fee = taker_fee
            else:
                maker_fee = exchange.fees.get("maker", 0.001) / 1000
                taker_fee = exchange.fees.get("taker", 0.001) / 1000

            for symbol in self.symbols:
                try:
                    # Buscar preço atual
                    ticker = exchange.fetch_ticker(symbol)
                    mark_price = ticker['last']

                    # Avaliar oportunidade
                    result = self.evaluate_trade_opportunity(
                        exchange_id=exchange_id,
                        symbol=symbol,
                        mark_price=mark_price,
                        maker_fee=maker_fee,
                        taker_fee=taker_fee
                    )

                    if result:
                        opportunities.append(result)

                except Exception as e:
                    self.logger.error(f"❌ Erro ao processar {exchange_id} {symbol}: {e}")
                    continue

        # Ordenar por certeza (maior primeiro)
        opportunities.sort(key=lambda x: (x.certainty, x.rr_ratio), reverse=True)

        # Limitar top N oportunidades
        max_opportunities = self.config.get('MAX_OPPORTUNITIES', 10)
        top_opportunities = opportunities[:max_opportunities]

        self.logger.info(f"📊 Total oportunidades encontradas: {len(opportunities)}")
        self.logger.info(f"🎯 Top {len(top_opportunities)} oportunidades selecionadas")

        return top_opportunities


# Exemplo de uso
if __name__ == '__main__':
    import time

    # Configuração de exemplo
    config = {
        # Configurações de decisão
        'CERTAINTY': 70,
        'VOLUME_ORDER': 100,
        'MAX_PERCENT_LOSS': '1%',
        'MAX_PERCENT_PROFIT': '2%',
        'UNIQUE_TREND': '',  # '', 'LONG', ou 'SHORT'
        'MAX_OPPORTUNITIES': 10,

        # Exchanges (alta liquidez)
        'EXCHANGES': ['binance'],
        # Símbolos (pares com volume)
        'SYMBOLS': [
            'BTC/USDT',
            'ETH/USDT',
            'SOL/USDT',
            'BNB/USDT',
            'XRP/USDT',
            'AVAX/USDT',
            'ARB/USDT',
            'OP/USDT',
        ]
    }

    print("🚀 Inicializando Crypto Decision Engine...")
    time.sleep(1)

    # Criar engine
    engine = CryptoDecisionEngine(config)

    print("📊 Avaliando oportunidades de trading...")
    print()

    # Avaliar oportunidades
    opportunities = engine.evaluate_all_pairs()

    # Exibir resultados
    print("="*80)
    print(f"{'EXCHANGE':<12} {'SYMBOL':<12} {'SIDE':<8} {'ENTRY':<12} {'CERTAINTY':<12} {'R:R':<8}")
    print("="*80)

    for i, opp in enumerate(opportunities, 1):
        print(f"{opp.exchange.upper():<12} {opp.symbol:<12} {opp.side.upper():<8} "
              f"${opp.entry_price:<10.4f} {opp.certainty:>12}% {opp.rr_ratio:>8.2f}x")
        print(f"{'':<12} {'':<12} {'':<8} Stop: ${opp.stop_loss:.4f} | "
              f"TP: ${opp.take_profit:.4f} | Risk: ${opp.risk_usd:.2f}")
        if i < len(opportunities):
            print()

    print("="*80)
    print(f"Total: {len(opportunities)} oportunidades encontradas")
    print()

    # Exibir top 3 com mais detalhes
    print("🎯 TOP 3 OPORTUNIDADES:")
    print("="*80)

    for i, opp in enumerate(opportunities[:3], 1):
        print(f"\n#{i} {opp.exchange.upper()} - {opp.symbol} ({opp.side.upper()})")
        print(f"   💰 Entry: ${opp.entry_price:.6f}")
        print(f"   🎯 Take Profit: ${opp.take_profit:.6f} (+${opp.reward_usd:.2f})")
        print(f"   🛡️ Stop Loss: ${opp.stop_loss:.6f} (-${opp.risk_usd:.2f})")
        print(f"   📊 Certainty: {opp.certainty}%")
        print(f"   ⚖️  Risk/Reward: {opp.rr_ratio:.2f}x")
        print(f"   📏  Size: {opp.position_size:.6f}")
        print(f"   📈 Indicadores:")
        print(f"      RSI 1m: {opp.indicators['tf1m_rsi']:.1f}")
        print(f"      RSI 5m: {opp.indicators['tf5m_rsi']:.1f}")
        print(f"      RSI 15m: {opp.indicators['tf15m_rsi']:.1f}")
        print(f"      MACD 5m: {opp.indicators['tf5m_macd']:.6f}")
        print(f"      EMA Diff 5m: {opp.indicators['tf5m_ema_diff']:.2f}%")
