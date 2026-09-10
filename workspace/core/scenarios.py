from __future__ import annotations

from dataclasses import dataclass

NADO_REJECTED = "nado_rejected"
KRAKEN_SELF_FILL_RISK = "kraken_self_fill_risk"
KRAKEN_POSITION_PARSE_ERROR = "kraken_position_parse_error"
DRIFT_HIGH = "drift_high"
ROLLBACK_EXECUTED = "rollback_executed"
PARTIAL_UNWIND_RISK = "partial_unwind_risk"
STOP_GLOBAL_TRIGGERED = "stop_global_triggered"
FUNDING_ADVERSE = "funding_adverse"
LEG2_FAILURE = "leg2_failure"
PRICE_SHOCK_UP = "price_shock_up"
PRICE_SHOCK_DOWN = "price_shock_down"
EXISTING_POSITION_RISK = "existing_position_risk"


def scenario_tag(code: str) -> str:
    return f"[{code}]"


def scenario_message(code: str, message: str) -> str:
    return f"{scenario_tag(code)} {message}"


@dataclass(frozen=True)
class ScenarioMatrixRow:
    scenario: str
    risco: str
    acao_esperada: str
    ordem_real_permitida: bool
    fluxo: str
    response_label: str
