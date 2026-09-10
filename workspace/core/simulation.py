from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .scenarios import (
    DRIFT_HIGH,
    FUNDING_ADVERSE,
    KRAKEN_SELF_FILL_RISK,
    LEG2_FAILURE,
    NADO_REJECTED,
    PARTIAL_UNWIND_RISK,
    PRICE_SHOCK_DOWN,
    PRICE_SHOCK_UP,
    STOP_GLOBAL_TRIGGERED,
    ScenarioMatrixRow,
)

PRICE_SHOCK_PCT = 0.08
FUNDING_ALERT_RATE = 0.0005  # 0.05% / 8h
FUNDING_INTERVALS_PER_DAY = 3


@dataclass(frozen=True)
class LeverageProfile:
    name: str
    leverage: float


@dataclass(frozen=True)
class SimulationSummary:
    symbol: str
    setup: str
    profile: str
    scenario: str
    risco: str
    acao_esperada: str
    ordem_real_permitida: bool
    fluxo: str
    response_label: str


PROFILE_MAP = {
    "1x": LeverageProfile(name="1x", leverage=1.0),
    "2x": LeverageProfile(name="2x", leverage=2.0),
    "3x": LeverageProfile(name="3x", leverage=3.0),
}

RISK_ORDER = {"baixo": 0, "medio": 1, "alto": 2}


def parse_profiles(raw: str | None) -> List[LeverageProfile]:
    if not raw:
        return [PROFILE_MAP["1x"], PROFILE_MAP["2x"], PROFILE_MAP["3x"]]
    profiles: List[LeverageProfile] = []
    for chunk in raw.split(","):
        key = chunk.strip().lower()
        if not key:
            continue
        profile = PROFILE_MAP.get(key)
        if profile is None:
            raise ValueError(f"perfil invalido: {chunk}")
        profiles.append(profile)
    if not profiles:
        raise ValueError("nenhum perfil informado")
    return profiles


def build_scenario_matrix(
    *,
    setup: str,
    profile: LeverageProfile,
    funding_rate: float | None,
    has_self_fill_risk: bool,
    drift_bps: int,
    max_pair_loss_pct: float,
) -> List[ScenarioMatrixRow]:
    if setup not in {"delta", "funding"}:
        raise ValueError(f"setup invalido: {setup}")

    funding_rate = abs(funding_rate or 0.0)
    funding_daily_pct = funding_rate * FUNDING_INTERVALS_PER_DAY * profile.leverage
    shock_loss_pct = PRICE_SHOCK_PCT * profile.leverage * (0.12 if setup == "delta" else 0.16)
    shock_risk = _risk_from_loss(shock_loss_pct, max_pair_loss_pct)
    shock_allows_live = shock_risk != "alto"
    shock_flow = "unwind" if shock_risk == "alto" else "rebalance"
    shock_action = (
        "acionar stop global e desmontar"
        if shock_risk == "alto"
        else "rebalancear rapido e manter tamanho pequeno"
        if shock_risk == "medio"
        else "monitorar e rebalancear se o delta escapar"
    )

    funding_risk, funding_live, funding_action = _funding_policy(
        setup=setup,
        profile=profile,
        funding_rate=funding_rate,
        funding_daily_pct=funding_daily_pct,
    )

    drift_stress_bps = int(drift_bps * (1.4 + 0.4 * (profile.leverage - 1)))
    drift_risk = "alto" if profile.leverage >= 3 else "medio" if drift_stress_bps > drift_bps else "baixo"
    drift_live = profile.leverage < 3
    drift_action = (
        "rebalance imediato; se persistir, unwind"
        if drift_risk == "alto"
        else "rebalance imediato"
        if drift_risk == "medio"
        else "seguir monitorando"
    )

    self_fill_risk = "alto" if has_self_fill_risk else "baixo"
    self_fill_live = not has_self_fill_risk
    self_fill_action = (
        "bloquear a abertura e limpar ordens conflitantes"
        if has_self_fill_risk
        else "seguir com preflight antes da ordem"
    )

    stop_risk = "alto" if shock_loss_pct >= max_pair_loss_pct else "medio"
    stop_action = (
        "unwind total e revisar o setup"
        if stop_risk == "alto"
        else "reduzir tamanho e manter stop armado"
    )

    return [
        ScenarioMatrixRow(
            scenario=f"alta brusca (+{PRICE_SHOCK_PCT * 100:.0f}%)",
            risco=shock_risk,
            acao_esperada=shock_action,
            ordem_real_permitida=shock_allows_live,
            fluxo=shock_flow,
            response_label=PRICE_SHOCK_UP,
        ),
        ScenarioMatrixRow(
            scenario=f"queda brusca (-{PRICE_SHOCK_PCT * 100:.0f}%)",
            risco=shock_risk,
            acao_esperada=shock_action,
            ordem_real_permitida=shock_allows_live,
            fluxo=shock_flow,
            response_label=PRICE_SHOCK_DOWN,
        ),
        ScenarioMatrixRow(
            scenario="funding adverso",
            risco=funding_risk,
            acao_esperada=funding_action,
            ordem_real_permitida=funding_live,
            fluxo="rebalance" if funding_live else "bloqueio",
            response_label=FUNDING_ADVERSE,
        ),
        ScenarioMatrixRow(
            scenario=f"drift acima do threshold ({drift_stress_bps} bps)",
            risco=drift_risk,
            acao_esperada=drift_action,
            ordem_real_permitida=drift_live,
            fluxo="rebalance" if drift_live else "unwind",
            response_label=DRIFT_HIGH,
        ),
        ScenarioMatrixRow(
            scenario="falha da perna 2",
            risco="alto",
            acao_esperada="rollback imediato da perna 1",
            ordem_real_permitida=False,
            fluxo="rollback",
            response_label=LEG2_FAILURE,
        ),
        ScenarioMatrixRow(
            scenario="selfFill na Kraken",
            risco=self_fill_risk,
            acao_esperada=self_fill_action,
            ordem_real_permitida=self_fill_live,
            fluxo="rollback" if has_self_fill_risk else "bloqueio",
            response_label=KRAKEN_SELF_FILL_RISK,
        ),
        ScenarioMatrixRow(
            scenario="rejeicao da Nado",
            risco="alto" if profile.leverage >= 3 else "medio",
            acao_esperada="abortar a entrada e revisar saldo/subconta",
            ordem_real_permitida=False,
            fluxo="bloqueio",
            response_label=NADO_REJECTED,
        ),
        ScenarioMatrixRow(
            scenario="stop global",
            risco=stop_risk,
            acao_esperada=stop_action,
            ordem_real_permitida=stop_risk != "alto",
            fluxo="unwind",
            response_label=STOP_GLOBAL_TRIGGERED,
        ),
        ScenarioMatrixRow(
            scenario="unwind parcial",
            risco="alto",
            acao_esperada="fechar residual e conferir exposicao manualmente",
            ordem_real_permitida=False,
            fluxo="unwind",
            response_label=PARTIAL_UNWIND_RISK,
        ),
    ]


def summarize_simulation(
    *,
    symbol: str,
    setup: str,
    profile: LeverageProfile,
    rows: Iterable[ScenarioMatrixRow],
) -> SimulationSummary:
    rows = list(rows)
    summary_rows = [
        row
        for row in rows
        if row.response_label not in {LEG2_FAILURE, NADO_REJECTED, PARTIAL_UNWIND_RISK}
    ]
    worst = max(summary_rows or rows, key=_scenario_priority)
    return SimulationSummary(
        symbol=symbol,
        setup=setup,
        profile=profile.name,
        scenario=worst.scenario,
        risco=worst.risco,
        acao_esperada=worst.acao_esperada,
        ordem_real_permitida=worst.ordem_real_permitida,
        fluxo=worst.fluxo,
        response_label=worst.response_label,
    )


def _risk_from_loss(loss_pct: float, max_pair_loss_pct: float) -> str:
    if loss_pct >= max_pair_loss_pct:
        return "alto"
    if loss_pct >= max_pair_loss_pct * 0.6:
        return "medio"
    return "baixo"


def _funding_policy(
    *,
    setup: str,
    profile: LeverageProfile,
    funding_rate: float,
    funding_daily_pct: float,
) -> tuple[str, bool, str]:
    if setup == "funding" and funding_rate >= FUNDING_ALERT_RATE:
        return (
            "alto",
            False,
            "nao abrir enquanto o funding continuar caro",
        )
    if funding_daily_pct >= 0.006:
        return (
            "alto",
            False,
            "reduzir alavancagem ou esperar funding aliviar",
        )
    if funding_rate >= FUNDING_ALERT_RATE or (profile.leverage >= 2 and funding_daily_pct >= 0.003):
        return (
            "medio",
            setup != "funding",
            "operar menor e revisar funding antes de manter overnight",
        )
    return (
        "baixo",
        True,
        "seguir com monitoramento de funding",
    )


def _scenario_priority(row: ScenarioMatrixRow) -> tuple[int, int, int]:
    return (
        RISK_ORDER[row.risco],
        0 if row.ordem_real_permitida else 1,
        1 if row.fluxo == "unwind" else 0,
    )
