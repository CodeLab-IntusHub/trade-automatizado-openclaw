"""O modo de stop por alvo, lido do estado de uma posicao aberta.

`_target_stop_mode_from_state` devolvia `off` para qualquer valor que nao
casasse com o vocabulario, sem dizer nada. `off` nao deixa a posicao sem stop
-- o stop inicial continua onde foi colocado --, mas desliga o **trailing**:
com `breakeven_on_tp1` ou `ladder`, o stop deveria subir depois que um alvo e
atingido, e passa a nao subir.

Ou seja: o operador pediu que o stop fosse melhorado e ele silenciosamente
nao e. Nao e exposicao nua, e sim a perda de uma melhoria pedida -- e ela se
perde exatamente onde nao da para perceber, dentro do loop de uma posicao ja
aberta.

Como o valor e normalizado na entrada do comando (`cli.py:7860`, que levanta),
isso nao acontece dentro de uma mesma versao. Acontece **entre versoes** --
o arquivo de estado sobrevive ao upgrade, entao um alias removido ou renomeado
apaga o trailing de toda posicao aberta -- e com estado editado a mao, que e
coisa que operador faz.

Levantar aqui seria pior: o loop gerencia varias posicoes, e derruba-lo por
causa do estado de uma so deixaria as outras sem gestao. Ele segue com `off`
para aquela posicao, que e a acao conservadora, mas diz que fez isso.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.cli import (  # noqa: E402
    TARGET_STOP_MODE_LADDER,
    TARGET_STOP_MODE_OFF,
    _target_stop_mode_from_state,
)


class _Estado:
    """Minimo que a funcao consome, com os campos de identificacao reais.

    `setup_key` e `symbol` sao os nomes em `ManagedSetupState`
    (`core/live_setups.py:42`). Um fake com nomes inventados passaria no teste
    e falharia contra o objeto de verdade.
    """

    def __init__(self, modo, setup_key="setup-x", symbol="ETH/USDT"):
        self.metadata = {"target_stop_mode": modo} if modo is not None else {}
        self.setup_key = setup_key
        self.symbol = symbol


def test_modo_valido_atravessa() -> None:
    assert _target_stop_mode_from_state(_Estado("ladder")) == TARGET_STOP_MODE_LADDER
    assert _target_stop_mode_from_state(_Estado("escada")) == TARGET_STOP_MODE_LADDER


def test_ausente_e_off_sem_avisar() -> None:
    """Estado sem o campo e o caso normal de quem nunca ligou o trailing --
    avisar aqui seria ruido em toda iteracao do loop."""
    assert _target_stop_mode_from_state(_Estado(None)) == TARGET_STOP_MODE_OFF


def test_valor_irreconhecivel_avisa_antes_de_desligar(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert _target_stop_mode_from_state(_Estado("ladder-v2")) == TARGET_STOP_MODE_OFF
    mensagem = "\n".join(r.getMessage() for r in caplog.records)
    assert "ladder-v2" in mensagem, mensagem
    assert "target_stop_mode" in mensagem, mensagem


def test_aviso_nomeia_a_posicao(caplog) -> None:
    """Sao varias posicoes no mesmo loop: um aviso que nao diz qual delas
    obriga o operador a abrir todos os arquivos de estado."""
    with caplog.at_level(logging.WARNING):
        _target_stop_mode_from_state(_Estado("ladder-v2", setup_key="grid", symbol="BTC/USDT"))
    mensagem = "\n".join(r.getMessage() for r in caplog.records)
    assert "BTC/USDT" in mensagem and "grid" in mensagem, mensagem


def test_continua_devolvendo_off_e_nao_levanta() -> None:
    """O loop gerencia varias posicoes; derruba-lo por causa de uma so
    deixaria as outras sem gestao."""
    assert _target_stop_mode_from_state(_Estado("qualquer-coisa")) == TARGET_STOP_MODE_OFF
