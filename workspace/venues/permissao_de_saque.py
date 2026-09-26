"""A API key da CEX pode sacar? (ADR 0007, ROADMAP 1.7)

A trava que vale contra um agente com shell esta na exchange: key sem
permissao de saque. Algumas venues expoem a permissao da propria key pela API;
nelas o `doctor` confere. Nas outras, diz que nao conseguiu verificar.

`interpretar` e puro (so le a resposta); `consultar` faz a chamada pelo CCXT.
Resposta que nao da para ler vira `ERRO`, nunca `SEM_SAQUE`: duvida nao e
seguranca.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SEM_SAQUE = "sem_saque"
PODE_SACAR = "pode_sacar"
NAO_VERIFICAVEL = "nao_verificavel"
ERRO = "erro"

# Metodo implicito do CCXT que devolve as permissoes da propria key.
_CONSULTAS = {
    "binance": "sapi_get_account_apirestrictions",  # GET /sapi/v1/account/apiRestrictions
    "bybit": "private_get_v5_user_query_api",  # GET /v5/user/query-api
    "okx": "private_get_account_config",  # GET /api/v5/account/config
}
TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class Veredicto:
    venue: str
    estado: str
    detalhe: str


def _pode_sacar_binance(resposta: Any) -> bool | None:
    valor = resposta.get("enableWithdrawals") if isinstance(resposta, dict) else None
    return valor if isinstance(valor, bool) else None


def _pode_sacar_bybit(resposta: Any) -> bool | None:
    resultado = resposta.get("result") if isinstance(resposta, dict) else None
    permissoes = resultado.get("permissions") if isinstance(resultado, dict) else None
    if not isinstance(permissoes, dict):
        return None
    carteira = permissoes.get("Wallet") or []
    return "Withdraw" in carteira if isinstance(carteira, list) else None


def _pode_sacar_okx(resposta: Any) -> bool | None:
    dados = resposta.get("data") if isinstance(resposta, dict) else None
    if not isinstance(dados, list) or not dados or not isinstance(dados[0], dict):
        return None
    perm = dados[0].get("perm")
    if not isinstance(perm, str):
        return None
    return "withdraw" in {p.strip().lower() for p in perm.split(",")}


_LEITORES = {"binance": _pode_sacar_binance, "bybit": _pode_sacar_bybit, "okx": _pode_sacar_okx}


def _nao_verificavel(venue: str) -> Veredicto:
    return Veredicto(
        venue,
        NAO_VERIFICAVEL,
        f"a {venue} nao expoe pela API a permissao da propria key: confira no painel da venue que a key nao tem saque",
    )


def interpretar(venue: str, resposta: Any) -> Veredicto:
    leitor = _LEITORES.get(venue)
    if leitor is None:
        return _nao_verificavel(venue)
    pode = leitor(resposta)
    if pode is None:
        return Veredicto(venue, ERRO, f"resposta da {venue} sem o campo de permissao esperado: confira no painel")
    if pode:
        return Veredicto(venue, PODE_SACAR, f"a API key da {venue} tem permissao de saque: gere uma key sem saque")
    return Veredicto(venue, SEM_SAQUE, f"a API key da {venue} nao tem permissao de saque")


def _cliente(venue: str, config: dict[str, Any]) -> Any:
    import ccxt

    return getattr(ccxt, venue)(config)


def consultar(venue: str, credenciais: dict[str, str], *, sandbox: bool) -> Veredicto:
    metodo = _CONSULTAS.get(venue)
    if metodo is None:
        return _nao_verificavel(venue)
    config: dict[str, Any] = {
        "apiKey": credenciais.get("api_key", ""),
        "secret": credenciais.get("api_secret", ""),
        "timeout": TIMEOUT_MS,
        "enableRateLimit": True,
    }
    if credenciais.get("api_password"):
        config["password"] = credenciais["api_password"]
    try:
        cliente = _cliente(venue, config)
        if sandbox:
            cliente.set_sandbox_mode(True)
        resposta = getattr(cliente, metodo)()
    except Exception as exc:  # noqa: BLE001 -- rede, auth, venue fora: nao verificado
        # So o tipo: a mensagem de erro pode ecoar parametros da requisicao.
        return Veredicto(venue, ERRO, f"consulta a {venue} falhou ({type(exc).__name__}): confira no painel")
    return interpretar(venue, resposta)


# --- DEX --------------------------------------------------------------------
# Sem rede: a pergunta e *qual* chave o operador configurou.

_HYPERLIQUID = {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}
_NADO = {"nado", "nado-dex", "nado_dex"}


def _endereco_da_chave(chave: str) -> str:
    import ccxt

    return str(ccxt.hyperliquid().eth_get_address_from_private_key(chave)).lower()


def verificar_dex(dex_id: str) -> Veredicto | None:
    """`None` quando nao ha chave configurada para verificar."""
    from workspace.venues.config import _first_env, dex_env_names

    nomes = dex_env_names(dex_id)
    if dex_id in _HYPERLIQUID:
        chave = _first_env(*nomes["private_key"])
        conta = _first_env(*nomes["wallet_address"]).lower()
        if not chave or not conta:
            return None
        try:
            endereco = _endereco_da_chave(chave)
        except Exception as exc:  # noqa: BLE001 -- chave malformada: so o tipo, nunca o valor
            return Veredicto(dex_id, ERRO, f"nao deu para derivar o endereco da chave ({type(exc).__name__})")
        if endereco == conta:
            return Veredicto(
                dex_id,
                PODE_SACAR,
                "a chave da Hyperliquid e a da conta principal, que saca: use uma API wallet (agent), que nao saca",
            )
        return Veredicto(dex_id, SEM_SAQUE, "a chave da Hyperliquid e de uma API wallet (agent), que nao saca")
    if dex_id in _NADO:
        if not _first_env(*nomes["owner_private_key"]):
            return None
        if _first_env(*nomes["linked_signer_private_key"]):
            return Veredicto(
                dex_id,
                NAO_VERIFICAVEL,
                "a Nado assina com o linked signer; a documentacao nao diz se ele saca (saque e um execute, "
                "e o WithdrawCollateralV2 aceita destinatario)",
            )
        return Veredicto(
            dex_id,
            PODE_SACAR,
            "sem linked signer, a skill assina com a owner key da Nado, que saca: configure NADO_LINKED_SIGNER_PRIVATE_KEY",
        )
    return Veredicto(dex_id, NAO_VERIFICAVEL, f"a DEX {dex_id} (adapter) nao informa a permissao da chave: confira na venue")
