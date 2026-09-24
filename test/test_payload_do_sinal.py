"""O payload do sinal é o contrato que vai virar público.

`_structured_signal_call` monta o registro estruturado de cada sinal, gravado
no outbox local (`trading-signal-outbox.jsonl`) — e o objetivo declarado é que
qualquer bot passe a consumir isso. (A mensagem do Discord é outra coisa: o
texto renderizado, sem este payload.) Dois problemas
só ficam caros **depois** que alguém consome:

1. **`context.scanner_state_path` emitia o caminho absoluto do operador.**
   Medido antes da correção: o valor era o caminho completo do arquivo de
   estado dentro do diretório pessoal do operador -- começando pela raiz de
   perfis do sistema, seguida do nome da conta.

   (O exemplo literal não entra aqui: o `validate` da CI recusa caminho
   absoluto de host commitado, e ele está certo -- documentar o vazamento
   reproduzindo o padrão seria cometê-lo no repositório.)

   Isso carrega o **nome de usuário da máquina** para o registro que qualquer
   leitor do outbox recebe — e que o ecossistema receberia. É dado de
   diagnóstico e pertence ao log local.

2. **`raw_payload` era passagem direta do dicionário interno.** Uma chave
   arbitrária plantada na entrada atravessava inteira. Não é que hoje vaze
   segredo — é que nada impede: a segurança do campo dependia de ninguém nunca
   pôr nada sensível no dict interno, o que não é propriedade que alguém
   garanta. E congela os internos no contrato: toda mudança interna vira
   quebra para quem consome.

O produtor real (`ccxt_entry_scanner.py:1321`) monta 14 campos, e **todos já
saem como campos de primeira classe** no payload estruturado. `raw_payload`,
portanto, era duplicação com risco embutido.

Em 24/09/2026 o autor confirmou que **nada lê o outbox**, e os campos de
convivência saíram: `schema` passou a ter o nome atual, e `schema_canonico` e
`raw_payload` deixaram de existir. Sem `raw_payload` não sobra passagem direta
nenhuma — todo campo é montado explicitamente —, e a fronteira passou a ser o
**próprio contrato**: o conjunto exato de chaves está declarado neste arquivo,
e um campo novo quebra a suíte até o contrato ser atualizado de propósito.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# O contrato do registro estruturado: o conjunto **exato** de chaves.
#
# Mora no teste, e nao no codigo, de proposito: se a lista vivesse no modulo,
# acrescentar um campo seria so acrescentar na lista, e o teste concordaria. Aqui
# um campo novo quebra a suite ate alguem decidir que ele entra no contrato --
# e atualizar `Docs/features/contrato-do-sinal.md` junto.
CAMPOS_DO_CONTRATO = {
    "schema", "idempotency_key", "source", "called_at", "bar_at",
    "asset_text", "setup_text", "setup_slug", "pair", "symbol", "venue",
    "side", "timeframe", "entry", "initial_stop", "targets", "thesis",
    "leverage", "risk_profile", "context",
}
CAMPOS_DO_CONTEXTO = {"exchange", "raw_symbol", "take_profit", "margin_mode"}


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


def test_contrato_tem_exatamente_os_campos_declarados() -> None:
    """Nem campo a mais nem a menos -- no topo e no `context`.

    Igualdade, e nao subconjunto: um campo a menos quebra quem consome, e um
    campo a mais e o caminho pelo qual o dict interno voltaria a vazar.
    """
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal())
    assert set(payload) == CAMPOS_DO_CONTRATO, (
        f"a mais: {set(payload) - CAMPOS_DO_CONTRATO} | "
        f"a menos: {CAMPOS_DO_CONTRATO - set(payload)}"
    )
    assert set(payload["context"]) == CAMPOS_DO_CONTEXTO


def test_schema_e_o_nome_atual_e_nao_ha_campo_de_legado() -> None:
    """Fechado em 24/09/2026: nada le o outbox, entao a convivencia nao
    protegia ninguem e so deixava dois nomes para a mesma coisa."""
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(_sinal())
    assert payload["schema"] == "intuscripto.trading.signal_call.v1"
    assert "schema_canonico" not in payload
    assert "raw_payload" not in payload


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
