"""O payload do sinal é o contrato que vai virar público.

`_structured_signal_call` monta o que sai do scanner para o grupo do Discord —
e o objetivo declarado é que qualquer bot passe a consumir isso. Dois problemas
só ficam caros **depois** que alguém consome:

1. **`context.scanner_state_path` emitia o caminho absoluto do operador.**
   Medido antes da correção: o valor era o caminho completo do arquivo de
   estado dentro do diretório pessoal do operador -- começando pela raiz de
   perfis do sistema, seguida do nome da conta.

   (O exemplo literal não entra aqui: o `validate` da CI recusa caminho
   absoluto de host commitado, e ele está certo -- documentar o vazamento
   reproduzindo o padrão seria cometê-lo no repositório.)

   Isso carrega o **nome de usuário da máquina** para dentro de uma mensagem
   que já vai para um grupo. É dado de diagnóstico e pertence ao log local.

2. **`raw_payload` era passagem direta do dicionário interno.** Uma chave
   arbitrária plantada na entrada atravessava inteira. Não é que hoje vaze
   segredo — é que nada impede: a segurança do campo dependia de ninguém nunca
   pôr nada sensível no dict interno, o que não é propriedade que alguém
   garanta. E congela os internos no contrato: toda mudança interna vira
   quebra para quem consome.

O produtor real (`ccxt_entry_scanner.py:1321`) monta 14 campos, e **todos já
saem como campos de primeira classe** no payload estruturado. `raw_payload`,
portanto, era duplicação com risco embutido.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Os 14 campos que o produtor real monta (`ccxt_entry_scanner.py:1321`).
# Mudar esta lista é mudar o contrato, e por isso ela mora num teste: a
# alteração exige uma decisão explícita, não um efeito colateral.
CAMPOS_DO_PRODUTOR = {
    "exchange", "symbol", "setup", "side", "timeframe", "reason",
    "entry_price", "stop_price", "take_profit", "targets",
    "leverage", "risk_profile", "created_at", "bar_at",
}


def _sinal(**extra):
    base = {
        "exchange": "binance", "symbol": "ETH/USDT", "setup": "grid", "side": "long",
        "timeframe": "1h", "reason": "teste", "entry_price": 100.0, "stop_price": 95.0,
        "take_profit": 110.0, "targets": [101.0, 102.0, 103.0, 104.0],
        "leverage": 3.0, "risk_profile": "moderate", "created_at": 1.0, "bar_at": "",
    }
    base.update(extra)
    return base


def test_nao_emite_o_caminho_de_estado_do_operador() -> None:
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal())
    assert "scanner_state_path" not in payload.get("context", {})


def test_nenhum_campo_carrega_caminho_local(monkeypatch) -> None:
    """Guard largo, de propósito: pega a reintrodução por qualquer campo novo,
    não só pelo que foi removido.

    A primeira versão comparava contra `Path.home()` e contra marcadores de
    raiz de perfil do sistema. Ela **passava com o vazamento reintroduzido** —
    confirmado
    por mutação: o valor depende de onde o teste roda e de quando o módulo foi
    importado (`STATE_PATH` é constante de módulo). Guard que depende do
    ambiente não é guard.

    Aqui o caminho é **injetado**: um sentinela reconhecível entra no lugar do
    `STATE_PATH`, e a asserção é que ele não aparece na saída. Determinístico e
    falsificável.
    """
    import json

    from workspace import ccxt_entry_scanner as scanner

    sentinela = Path("/caminho-local-que-nao-pode-vazar/estado.json")
    monkeypatch.setattr(scanner, "STATE_PATH", sentinela, raising=False)
    monkeypatch.setattr(scanner, "OUTBOX_PATH", sentinela, raising=False)

    texto = json.dumps(scanner._structured_signal_call(_sinal()), default=str)
    assert "caminho-local-que-nao-pode-vazar" not in texto, (
        f"o payload carrega um caminho da máquina do operador: {texto}"
    )


def test_chave_desconhecida_nao_atravessa() -> None:
    """O mecanismo do vazamento: o que entra no dict interno saía inteiro."""
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal(segredo_interno="nao-deveria-sair"))
    import json

    assert "nao-deveria-sair" not in json.dumps(payload, default=str)


def test_raw_payload_e_limitado_aos_campos_declarados() -> None:
    """Mantido para não quebrar quem já lê dele, mas com fronteira."""
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal(campo_novo_interno=1))
    assert set(payload["raw_payload"]) <= CAMPOS_DO_PRODUTOR
    assert "campo_novo_interno" not in payload["raw_payload"]


def test_a_lista_declarada_nao_tem_campo_fantasma() -> None:
    """Campo na allowlist que o produtor não emite é promessa que o contrato
    não cumpre — consumidor esperando e recebendo `None` para sempre."""
    from workspace.ccxt_entry_scanner import CAMPOS_PUBLICOS_DO_SINAL

    assert set(CAMPOS_PUBLICOS_DO_SINAL) <= CAMPOS_DO_PRODUTOR, (
        "a allowlist declara campo que o produtor real não monta: "
        f"{set(CAMPOS_PUBLICOS_DO_SINAL) - CAMPOS_DO_PRODUTOR}"
    )


def test_os_campos_de_primeira_classe_continuam_valendo() -> None:
    """A correção não pode estreitar o contrato útil: o que o consumidor de
    fato lê são os campos do topo, e eles seguem intactos."""
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal())
    assert payload["side"] == "LONG"
    assert payload["entry"] == 100.0
    assert payload["initial_stop"] == 95.0
    assert payload["venue"] == "binance"
    assert payload["timeframe"] == "1h"
    assert payload["leverage"] == 3.0
    assert len(payload["targets"]) == 4
    assert payload["context"]["take_profit"] == 110.0
