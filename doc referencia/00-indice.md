# Doc Referencia

Referencia do isolamento de conta para trade: linked signer e subconta na Nado,
subconta opcional na Kraken Futures. A configuracao geral de setups e venues
esta em `settings.json` — ver
[Configuracao de setups](../Docs/features/configuracao-de-setups.md) e
[Sandbox por venue](../Docs/features/sandbox-por-venue.md).

- [01-modelo-subconta-only.md](01-modelo-subconta-only.md) — o que isola o trade em cada venue
- [03-env-e-credenciais.md](03-env-e-credenciais.md) — variaveis de credencial e de isolamento
- [04-validacao-operacional.md](04-validacao-operacional.md) — checklist antes do primeiro trade

Arquivo historico (nao prescreve configuracao atual):
- [historico/02-migracao-do-estado-atual.md](historico/02-migracao-do-estado-atual.md) — migracao de 22/04/2026 para o modelo subconta-only

Arquivos raiz relacionados:
- [README.md](../README.md)
- [INSTALL.md](../INSTALL.md)
- [SKILL.md](../SKILL.md)

Convencoes:
- datas absolutas para snapshots
- segredos nunca aparecem aqui
- na Nado, sem linked signer configurado o trade assina com a owner key; com linked signer configurado e invalido, bloqueia, e usar a owner key exige confirmacao explicita
- na Kraken, subconta e recomendada e opcional; o usuario decide se liga a validacao estrita
