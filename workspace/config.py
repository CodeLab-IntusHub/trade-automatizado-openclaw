"""Fonte única de configuração: uma precedência, um vocabulário, uma coerção.

Hoje a configuração é lida por ~35 helpers espalhados, com vocabulários de
booleano que só definem o lado verdadeiro — então qualquer valor desconhecido
(um typo como `ture`) resolve para falso em silêncio. Em `CEX_SANDBOX` isso
significa dinheiro real. Este módulo existe para que essa classe de defeito
deixe de ter onde acontecer.

Precedência, do mais forte para o mais fraco:

    variável de ambiente → settings.local.json → settings.json → default

O ambiente continua vencendo, então a migração é retrocompatível: quem já
configura por env não muda nada. `settings.local.json` é gitignored e serve à
máquina do operador; `settings.json` é versionado e carrega o que é comum ao
time.

**Segredo nunca entra no arquivo.** O settings guarda apenas o *nome* da
variável de ambiente que o contém; o valor vem do ambiente ou do secret
manager. Um segredo literal no arquivo é recusado.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "BOOL_FALSE_VALUES",
    "BOOL_TRUE_VALUES",
    "ConfigError",
    "ConfigOrigin",
    "Settings",
    "load_settings",
]

# Os dois lados são explícitos de propósito. A versão anterior testava só a
# pertinência ao conjunto verdadeiro, então "não reconheci" e "falso" eram
# indistinguíveis -- e o valor perigoso era justamente o default silencioso.
BOOL_TRUE_VALUES = frozenset({"1", "true", "yes", "sim", "on", "y", "s"})
BOOL_FALSE_VALUES = frozenset({"0", "false", "no", "nao", "não", "off", "n"})

_VERSIONED_FILE = "settings.json"
_LOCAL_FILE = "settings.local.json"

SKILL_ID = "trade-automatizado-openclaw"
# Onde procurar o settings do operador, em ordem. A skill e reinstalada por
# cima do proprio diretorio, entao config do operador guardada dentro da arvore
# se perde nessa hora. A env file ja vive fora (`~/.config/openclaw/`, ver
# `workspace/run.py`), e o settings local segue a mesma convencao; o arquivo
# dentro da arvore continua valendo como fallback.
_LOCAL_DIR_ENV = "DELTA_NEUTRAL_SETTINGS_DIR"

_MISSING = object()


class ConfigError(RuntimeError):
    """Configuração ausente, ambígua ou ilegível.

    Sempre nomeia a chave e, quando cabe, os valores aceitos — um erro de
    config que não diz o que corrigir custa mais que o valor errado.
    """


@dataclass(frozen=True)
class ConfigOrigin:
    """De onde um valor veio. Sem isso, "por que esse valor?" vira arqueologia."""

    layer: str  # "env" | "settings.local.json" | "settings.json" | "default"
    key: str    # nome da env ou caminho pontilhado


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path.name} inválido: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{path.name} precisa conter um objeto JSON no topo")
    return payload


def _dig(data: Mapping[str, Any], dotted: str) -> Any:
    """Busca por caminho pontilhado, tolerando chaves com ponto no nome.

    Uma chave de setup pode conter ponto (`rsi-2.5x`), e quebrar o caminho só
    pelo separador faria o valor configurado sumir -- com `default`, em
    silêncio. Por isso a busca tenta primeiro o prefixo mais longo que exista
    literalmente neste nível, e só então desce.
    """
    if not isinstance(data, Mapping):
        return _MISSING
    if dotted in data:
        return data[dotted]

    parts = dotted.split(".")
    # Do prefixo mais longo para o mais curto: a chave literal vence a
    # interpretação como caminho, que é o que torna `rsi-2.5x` endereçável.
    for size in range(len(parts) - 1, 0, -1):
        head = ".".join(parts[:size])
        if head in data:
            found = _dig(data[head], ".".join(parts[size:]))
            if found is not _MISSING:
                return found
    return _MISSING


def _as_env_names(env: str | Sequence[str] | None) -> tuple[str, ...]:
    if env is None:
        return ()
    if isinstance(env, str):
        return (env,)
    return tuple(env)


class Settings:
    """Configuração resolvida, com precedência e coerção únicas."""

    def __init__(
        self,
        *,
        versioned: Mapping[str, Any],
        local: Mapping[str, Any],
        env: Mapping[str, str],
    ) -> None:
        self._versioned = dict(versioned)
        self._local = dict(local)
        self._env = dict(env)

    # -- resolução ---------------------------------------------------------

    def _resolve(self, dotted: str, env: str | Sequence[str] | None) -> tuple[Any, ConfigOrigin]:
        for name in _as_env_names(env):
            raw = self._env.get(name)
            # Valor vazio conta como não definido: um env exportado como "" é
            # quase sempre acidente de script, não uma escolha.
            if raw is not None and raw.strip() != "":
                # Sem corte em `#`: os leitores antigos cortavam comentário
                # ANTES de remover aspas, então nem aspas protegiam, e isso
                # corrompia passphrase injetada corretamente pelo secret
                # manager. Comentário é coisa de parser de arquivo .env.
                return raw.strip(), ConfigOrigin("env", name)

        for layer, data in ((_LOCAL_FILE, self._local), (_VERSIONED_FILE, self._versioned)):
            found = _dig(data, dotted)
            # `null` declara "sem valor aqui", nao o valor `None`: e como o
            # operador anula uma chave local para cair na do time. Stringificar
            # isso devolvia a literal "None" como id de exchange.
            if found is not _MISSING and found is not None:
                return found, ConfigOrigin(layer, dotted)

        return _MISSING, ConfigOrigin("default", dotted)

    def origin(self, dotted: str, *, env: str | Sequence[str] | None = None) -> ConfigOrigin:
        return self._resolve(dotted, env)[1]

    def _require(self, dotted: str, env: str | Sequence[str] | None, default: Any) -> Any:
        value, _origin = self._resolve(dotted, env)
        if value is not _MISSING:
            return value
        if default is not _MISSING:
            return default
        names = " / ".join(_as_env_names(env)) or "(sem env)"
        raise ConfigError(
            f"configuração obrigatória ausente: '{dotted}' (env: {names}). "
            f"Defina no ambiente, em {_LOCAL_FILE} ou em {_VERSIONED_FILE}."
        )

    # -- tipos -------------------------------------------------------------

    def get_str(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> str:
        value = self._require(dotted, env, default)
        if isinstance(value, str):
            return value
        if isinstance(value, (Mapping, list, tuple)):
            raise ConfigError(
                f"valor inválido para '{dotted}': esperava texto, veio {type(value).__name__}. "
                "Use get_json/get_list para estrutura."
            )
        return str(value)

    def get_bool(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> bool:
        value = self._require(dotted, env, default)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in BOOL_TRUE_VALUES:
            return True
        if text in BOOL_FALSE_VALUES:
            return False
        raise ConfigError(
            f"valor booleano inválido para '{dotted}': {value!r}. "
            f"Use um de {sorted(BOOL_TRUE_VALUES)} ou {sorted(BOOL_FALSE_VALUES)}. "
            "Valor não reconhecido não é tratado como falso — em portões como "
            "sandbox, falso significa dinheiro real."
        )

    def get_int(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> int:
        value = self._require(dotted, env, default)
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ConfigError(self._type_error(dotted, env, value, "inteiro")) from exc

    def get_float(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> float:
        value = self._require(dotted, env, default)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ConfigError(self._type_error(dotted, env, value, "número")) from exc

    def get_list(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> list[str]:
        value = self._require(dotted, env, default)
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    def get_json(self, dotted: str, *, env: str | Sequence[str] | None = None, default: Any = _MISSING) -> Any:
        value = self._require(dotted, env, default)
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigError(self._type_error(dotted, env, value, "JSON")) from exc

    def _type_error(self, dotted: str, env: str | Sequence[str] | None, value: Any, kind: str) -> str:
        origin = self.origin(dotted, env=env)
        onde = origin.key if origin.layer == "env" else f"{origin.layer}:{dotted}"
        return f"valor inválido para '{dotted}' em {onde}: {value!r} não é {kind}"

    # -- segredos ----------------------------------------------------------

    def secret(self, dotted: str) -> str:
        """Resolve um segredo pelo *nome* da env declarado no settings.

        O arquivo guarda `{"env": ["KRAKEN_API_KEY", "CEX_API_KEY"]}`; o valor
        vem do ambiente. Segredo literal no arquivo é recusado — settings.json
        é versionado, e um segredo que entra ali vaza para sempre no histórico.
        """
        declared, origin = self._resolve(dotted, None)
        if declared is _MISSING:
            raise ConfigError(f"segredo não declarado: '{dotted}'")
        names: Iterable[str]
        if isinstance(declared, Mapping) and "env" in declared:
            raw_names = declared["env"]
            if isinstance(raw_names, str):
                names = (raw_names,)
            elif isinstance(raw_names, (list, tuple)) and raw_names:
                names = tuple(str(item) for item in raw_names)
            else:
                # Sem isto um `{"env": 123}` estourava `TypeError` cru, que
                # escapa de quem captura ConfigError.
                raise ConfigError(
                    f"segredo '{dotted}': 'env' precisa ser o nome de uma variável ou uma "
                    f"lista não vazia de nomes; veio {raw_names!r}"
                )
        else:
            raise ConfigError(
                f"segredo '{dotted}' em {origin.layer} precisa declarar apenas o NOME da "
                'variável de ambiente, no formato {"env": ["NOME_DA_VAR"]}. '
                "Valor literal de segredo não pode entrar no arquivo de settings."
            )
        for name in names:
            value = self._env.get(name)
            if value and value.strip():
                # Sem `.strip()` no retorno: passphrase pode ter espaço
                # significativo, e cortá-lo reproduz -- em outra forma -- o
                # mesmo defeito de mutilar segredo que este módulo existe para
                # acabar. O `.strip()` acima serve só para decidir se está
                # definida.
                return value
        raise ConfigError(
            f"segredo '{dotted}' não encontrado no ambiente. Defina uma destas: {', '.join(names)}"
        )


def load_settings(
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Carrega `settings.json` e `settings.local.json` da raiz do repositório.

    Arquivo ausente não é erro — a configuração por ambiente continua
    funcionando sozinha, que é o que torna esta migração reversível.
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    return Settings(
        # O versionado e sempre o do repositorio: ele pertence ao time.
        versioned=_read_json_file(base / _VERSIONED_FILE),
        local=_read_json_file(_local_settings_path(base)),
        env=dict(os.environ if env is None else env),
    )


def _local_settings_path(base: Path) -> Path:
    """Primeiro caminho existente para o settings do operador.

    Se nenhum existir, devolve o do repositorio -- arquivo ausente nao e erro,
    entao o valor de retorno so precisa ser um caminho plausivel.
    """
    candidates = []
    override = os.environ.get(_LOCAL_DIR_ENV)
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path.home() / ".config" / "openclaw" / SKILL_ID)
    candidates.append(base)
    for directory in candidates:
        candidate = directory / _LOCAL_FILE
        if candidate.exists():
            return candidate
    return base / _LOCAL_FILE
