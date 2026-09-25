#!/usr/bin/env python3
"""Chat-first onboarding payload for trade-automatizado-openclaw."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


CREDENTIAL_GUIDANCE = {
    "must_show_to_user": True,
    "title": "Onde configurar chaves e segredos com segurança",
    "short_explanation": "Por segurança, não envie API keys, tokens, webhooks, OAuth, private keys, seeds ou secrets pelo chat. Configure tudo no env/secret manager seguro e depois me diga apenas se já está salvo.",
    "paths": {
        "llm_provider_keys": "secret manager > Chaves LLM",
        "service_api_keys": "secret manager > Chaves de Serviço",
        "anthropic_oauth": "secret manager > OAuth Token"
    },
    "recommended_secret_manager": "1Password (referencias op:// com `op run`) ou o gerenciador de segredos que o operador ja usa; a skill nao guarda credencial de ninguem.",
    "chat_allowed_answers": ["já está salvo", "não está salvo", "não sei"],
    "never_ask_for": ["API key", "token", "webhook", "OAuth token", "private key", "seed phrase", "secret value"],
    "user_message_template": "Essa skill precisa de {credential_name}. Por segurança, não cole a chave aqui. Configure em {section} no seu env/secret manager seguro e me diga apenas se já está salvo.",
}

WIZARD_PATH_CHOICE = {
    "field": "wizard_path",
    "reason": "Define o nível de detalhe do wizard antes das perguntas operacionais.",
    "question": "Como você quer seguir: 1) Caminho iniciante — passo a passo guiado e simples; ou 2) Caminho avançado — configuração completa com validações/dry-run quando aplicável?",
    "options": ["iniciante", "avancado"],
    "aliases": {"1": "iniciante", "guiado": "iniciante", "simples": "iniciante", "2": "avancado", "avançado": "avancado", "completo": "avancado"},
    "default": "iniciante",
}

WIZARD_PATHS = {
    "choice_required": True,
    "beginner": {
        "label": "Caminho iniciante",
        "description": "Passo a passo guiado, linguagem simples, defaults seguros e só as decisões essenciais.",
    },
    "advanced": {
        "label": "Caminho avançado",
        "description": "Configuração completa, parâmetros, validações/dry-run quando aplicável e rastreabilidade operacional.",
    },
    "can_switch_when_safe": True,
    "never_request_secrets_in_chat": True,
}


SUPPORTED_VENUES = {
    "main_dex": [
        {"id": "nado", "label": "Nado", "adapter": "builtin", "env": "DEX_ID=nado"},
        {"id": "hyperliquid", "label": "Hyperliquid", "adapter": "builtin_ccxt", "env": "DEX_ID=hyperliquid"},
    ],
    "main_cex": [
        {"id": "kraken", "label": "Kraken", "adapter": "builtin/ccxt", "env": "CEX_ID=kraken"},
        {"id": "binance", "label": "Binance", "adapter": "ccxt", "env": "CEX_ID=binance"},
        {"id": "bybit", "label": "Bybit", "adapter": "ccxt", "env": "CEX_ID=bybit"},
        {"id": "okx", "label": "OKX", "adapter": "ccxt", "env": "CEX_ID=okx"},
        {"id": "kucoin", "label": "KuCoin", "adapter": "ccxt", "env": "CEX_ID=kucoin"},
        {"id": "mexc", "label": "MEXC", "adapter": "ccxt", "env": "CEX_ID=mexc"},
        {"id": "bitget", "label": "Bitget", "adapter": "ccxt", "env": "CEX_ID=bitget"},
        {"id": "gateio", "label": "Gate.io", "adapter": "ccxt", "env": "CEX_ID=gateio"},
    ],
    "other_integrations_notice": "A skill integra Hyperliquid como DEX builtin via CCXT, outras CEXs suportadas pelo CCXT usando CEX_ID=<exchange_id> e outras DEXs com DEX_ID=<id> + DEX_ADAPTER_MODULE=pacote.modulo:Classe antes de live trade.",
}

ACCOUNT_ISOLATION_POLICY = {
    "subaccount_required_by_default": False,
    "subaccount_user_decides": True,
    "must_not_hardcode_subaccount_requirement": True,
    "wizard_rule": "Nao tratar subconta como requisito obrigatorio. Recomendar operar em subconta, vault ou conta isolada quando a corretora/DEX oferecer esse recurso; a decisao final e do usuario e nao deve ser hard-coded; se o usuario nao usar esse modelo, exigir no minimo API key/credencial dedicada sem saque e validar doctor/dry-run.",
    "short_wizard": "Nao perguntar nome de subconta no wizard curto.",
    "kraken": "Subconta Kraken e opcional, mas recomendada para isolamento quando a corretora/DEX oferecer esse recurso; use API key dedicada sem saque na conta/subconta correta. KRAKEN_REQUIRE_SUBACCOUNT=false por padrao; use true somente se o usuario escolher validacao estrita de subconta.",
    "nado": "NADO_SUBACCOUNT_NAME e config opcional; usar default operacional quando aplicavel e ajustar apenas se o usuario usa nome customizado ou se o diagnostico falhar.",
    "hyperliquid": "API wallet/agent wallet e recomendada para automacao; vault/subaccount e recomendado para isolamento quando a corretora/DEX oferecer esse recurso, mas nao e bloqueio obrigatorio por padrao.",
}

HYPERLIQUID_OFFICIAL_LINKS = {
    "app_mainnet": "https://app.hyperliquid.xyz/trade",
    "onboarding": "https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/how-to-start-trading",
    "api": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api",
    "api_wallets_and_nonces": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets",
    "ccxt": "https://docs.ccxt.com/#/exchanges/hyperliquid",
    "testnet_faucet_optional": "https://app.hyperliquid-testnet.xyz/drip",
}

HYPERLIQUID_MARKET_TYPE_REFERENCE = (
    "HYPERLIQUID_MARKET_TYPE=trade e o valor amigavel para usuario; a skill normaliza para CCXT swap/perps; "
    "na pratica e o mercado de trade long/short com collateral USDC. O valor tecnico swap tambem e aceito para troubleshooting CCXT."
)

DEX_MARKET_TYPE_REFERENCE = (
    "DEX_MARKET_TYPE=trade e o fallback amigavel para DEXs que usam CCXT/perps. "
    "No builtin Hyperliquid, DEX_MARKET_TYPE=trade ou HYPERLIQUID_MARKET_TYPE=trade normaliza para CCXT swap. "
    "Nado nao usa esse env; DEX custom so usa se o adapter implementar."
)

CEX_MARKET_TYPE_REFERENCE = (
    "CEX_MARKET_TYPE=trade e o valor amigavel para perps/long-short nas CEXs via CCXT; "
    "a skill normaliza para swap no CCXT. Para Kraken builtin, trade normaliza para futures. "
    "Use spot ou future somente quando o produto/venue exigir explicitamente."
)

VENUE_SETUP_GUIDES = {
    "nado": [
        "Definir DEX_ID=nado (nao ha DEX padrao).",
        "Conectar wallet na Nado e selecionar rede Ink; subconta/nome customizado nao e requisito do wizard e so deve ser ajustado se a venue/runtime exigir.",
        "Salvar NADO_OWNER_PRIVATE_KEY no secret/env seguro; opcionalmente salvar NADO_LINKED_SIGNER_PRIVATE_KEY.",
        "Salvar NADO_NETWORK como config nao sensivel; salvar NADO_SUBACCOUNT_NAME apenas quando precisar sobrescrever o default.",
        "Rodar venues, setup-check, doctor, symbols e dry-run antes de live.",
    ],
    "hyperliquid": [
        "Usar mainnet para operacao real: DEX_ID=hyperliquid; deixe a rede e o sandbox no settings.json (venues.dex.hyperliquid.sandbox), porque env definida vence o arquivo.",
        HYPERLIQUID_MARKET_TYPE_REFERENCE,
        DEX_MARKET_TYPE_REFERENCE,
        "Analisar links oficiais em hyperliquid_official_links antes de salvar credenciais ou liberar live.",
        "Conectar wallet em https://app.hyperliquid.xyz/trade, acionar Enable Trading e preparar collateral USDC conforme onboarding oficial.",
        "Criar API wallet/agent wallet dedicada; HYPERLIQUID_WALLET_ADDRESS deve ser o endereco real da conta/vault, nao o endereco da agent wallet.",
        "Salvar HYPERLIQUID_PRIVATE_KEY ou HYPERLIQUID_API_PRIVATE_KEY/HYPERLIQUID_AGENT_PRIVATE_KEY somente no Secret Manager; nunca colar private key no chat.",
        "Usar HYPERLIQUID_VAULT_ADDRESS apenas se o usuario escolher operar via vault; usar uma API wallet separada por bot/processo/subconta/vault para reduzir colisao de nonce.",
        "Rodar venues, symbols, setup-check/doctor e dry-run antes de live; ordem real exige sizing, margem/leverage, limite de perda e confirmacao explicita.",
    ],
    "binance": [
        "Definir CEX_ID=binance e CEX_MARKET_TYPE=trade para perps/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com leitura e trading, sem permissao de saque; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar BINANCE_API_KEY/BINANCE_API_SECRET ou CEX_API_KEY/CEX_API_SECRET no Secret Manager.",
        "Definir venues.cex.sandbox=true no settings.json se for testnet/sandbox; false apenas depois de validado.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "kraken": [
        "Definir CEX_ID=kraken (nao ha CEX padrao).",
        "Criar API key dedicada na Kraken Pro/Futures com leitura e trading, sem saque; subconta e recomendada para isolamento, mas nao obrigatoria.",
        "Salvar KRAKEN_API_KEY_ ou KRAKEN_API_KEY e KRAKEN_API_SECRET no Secret Manager.",
        "Definir KRAKEN_VENUE/CEX_MARKET_TYPE; sandbox fica em venues.cex.kraken.sandbox no settings.json (env definida vence o arquivo). KRAKEN_API_IS_SUBACCOUNT so se a key realmente for de subconta.",
        "Rodar cex-accounts, setup-check, doctor, symbols e dry-run antes de live.",
    ],
    "bybit": [
        "Definir CEX_ID=bybit e CEX_MARKET_TYPE=trade para contratos perp/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com permissao de leitura e trade, sem saque; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar BYBIT_API_KEY/BYBIT_API_SECRET ou CEX_API_KEY/CEX_API_SECRET no Secret Manager.",
        "Definir venues.cex.sandbox=true no settings.json para testnet quando aplicavel.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "okx": [
        "Definir CEX_ID=okx e CEX_MARKET_TYPE=trade para perps/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com leitura e trading, sem saque, e gerar a passphrase exigida pela OKX; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar OKX_API_KEY, OKX_API_SECRET e OKX_API_PASSWORD ou CEX_* equivalentes no Secret Manager.",
        "Definir venues.cex.sandbox=true no settings.json se for ambiente demo/sandbox.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "kucoin": [
        "Definir CEX_ID=kucoin e CEX_MARKET_TYPE=trade para perps/long-short; usar future ou spot somente se o produto exigir.",
        "Criar API key dedicada com leitura e trading, sem saque, e gerar a passphrase/password exigida pela KuCoin; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar KUCOIN_API_KEY, KUCOIN_API_SECRET e KUCOIN_API_PASSWORD ou CEX_* equivalentes no Secret Manager.",
        "Definir venues.cex.sandbox=true no settings.json apenas se estiver usando sandbox/testnet compativel.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "mexc": [
        "Definir CEX_ID=mexc e CEX_MARKET_TYPE=trade para perps/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com leitura e trading, sem saque; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar MEXC_API_KEY/MEXC_API_SECRET ou CEX_API_KEY/CEX_API_SECRET no Secret Manager.",
        "Definir venues.cex.sandbox no settings.json conforme o ambiente real da conta/API.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "bitget": [
        "Definir CEX_ID=bitget e CEX_MARKET_TYPE=trade para contratos perp/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com leitura e trading, sem saque, e gerar a passphrase/password exigida pela Bitget; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar BITGET_API_KEY, BITGET_API_SECRET e BITGET_API_PASSWORD ou CEX_* equivalentes no Secret Manager.",
        "Definir venues.cex.sandbox=true no settings.json apenas se estiver usando ambiente demo/sandbox compativel.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "gateio": [
        "Definir CEX_ID=gateio e CEX_MARKET_TYPE=trade para perps/long-short; a skill normaliza para CCXT swap.",
        "Criar API key dedicada com leitura e trading, sem saque; preferir subconta/conta isolada quando a corretora oferecer esse recurso.",
        "Salvar GATEIO_API_KEY/GATEIO_API_SECRET ou CEX_API_KEY/CEX_API_SECRET no Secret Manager.",
        "Definir venues.cex.sandbox no settings.json conforme o ambiente real da conta/API.",
        "Rodar venues, cex-accounts, symbols e dry-run antes de live.",
    ],
    "outras_cex_ccxt": [
        "Confirmar o exchange_id no CCXT.",
        "Definir CEX_ID=<exchange_id> e CEX_MARKET_TYPE=trade|future|spot (trade normaliza para CCXT swap); sandbox fica em venues.cex.sandbox no settings.json.",
        "Salvar CEX_API_KEY, CEX_API_SECRET e CEX_API_PASSWORD quando a corretora exigir.",
        "Validar se a exchange suporta mercados, saldo, posicoes, leverage, margin mode e ordens trigger pelo CCXT.",
        "Rodar venues, symbols e dry-run; se algum recurso critico faltar, nao seguir para live.",
    ],
    "outras_dex_adapter": [
        "Definir DEX_ID=<id>.",
        "Configurar DEX_ADAPTER_MODULE=pacote.modulo:Classe.",
        "Salvar segredos exigidos pelo adapter somente no Secret Manager.",
        "Definir DEX_CONFIG_JSON apenas com parametros nao sensiveis.",
        "Definir DEX_MARKET_TYPE=trade somente se o adapter customizado ler esse parametro; Nado nao usa esse env.",
        "Rodar venues, symbols e dry-run; sem adapter completo, nao executar live.",
    ],
}

VENUE_CREDENTIAL_REQUIREMENTS = {
    "nado": {
        "required_envs": ["DEX_ID=nado", "NADO_OWNER_PRIVATE_KEY"],
        "optional_envs": ["NADO_LINKED_SIGNER_PRIVATE_KEY"],
        "config_envs": ["NADO_NETWORK=mainnet|testnet", "NADO_SUBACCOUNT_NAME=default_1 (opcional, so para sobrescrever default/custom)"],
        "where_to_save": "secret manager > Chaves de Serviço para private keys; config nao sensivel para network e nome customizado quando necessario",
    },
    "hyperliquid": {
        "required_envs": ["DEX_ID=hyperliquid", "HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_PRIVATE_KEY"],
        "optional_envs": ["HYPERLIQUID_API_PRIVATE_KEY", "HYPERLIQUID_AGENT_PRIVATE_KEY", "HYPERLIQUID_VAULT_ADDRESS", "HYPERLIQUID_OPTIONS_JSON"],
        "config_envs": ["DEX_MARKET_TYPE=trade (fallback DEX amigavel)", "HYPERLIQUID_MARKET_TYPE=trade (alias especifico; normaliza para CCXT swap)", "HYPERLIQUID_SYMBOL_QUOTE=USDT"],
        "where_to_save": "private key da API wallet/agent wallet no Secret Manager; wallet/vault/network como config segura sem colar no chat",
        "account_address_rule": "HYPERLIQUID_WALLET_ADDRESS deve ser o endereco real da conta/subconta/vault consultada; nao usar o endereco da API wallet/agent wallet.",
        "live_guardrail": "Mainnet/live exige setup-check, doctor, dry-run, sizing, margem/leverage, limite de perda e confirmacao explicita antes de ordem real.",
    },
    "kraken": {
        "required_envs": ["CEX_ID=kraken", "KRAKEN_API_KEY_ ou KRAKEN_API_KEY", "KRAKEN_API_SECRET"],
        "optional_envs": ["KRAKEN_ALLOW_MAIN_ACCOUNT", "KRAKEN_API_IS_SUBACCOUNT=true apenas se a key for de subconta"],
        "config_envs": ["KRAKEN_VENUE=futures|spot", "CEX_MARKET_TYPE=trade|future|spot (Kraken: trade normaliza para futures; CEX CCXT: trade normaliza para swap)", "KRAKEN_REQUIRE_SUBACCOUNT=false por padrao"],
        "where_to_save": "secret manager > Chaves de Serviço para API key/secret",
    },
    "binance": {
        "required_envs": ["CEX_ID=binance", "BINANCE_API_KEY ou CEX_API_KEY", "BINANCE_API_SECRET ou CEX_API_SECRET"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|future|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "bybit": {
        "required_envs": ["CEX_ID=bybit", "BYBIT_API_KEY ou CEX_API_KEY", "BYBIT_API_SECRET ou CEX_API_SECRET"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "okx": {
        "required_envs": ["CEX_ID=okx", "OKX_API_KEY ou CEX_API_KEY", "OKX_API_SECRET ou CEX_API_SECRET", "OKX_API_PASSWORD ou CEX_API_PASSWORD"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|future|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "kucoin": {
        "required_envs": ["CEX_ID=kucoin", "KUCOIN_API_KEY ou CEX_API_KEY", "KUCOIN_API_SECRET ou CEX_API_SECRET", "KUCOIN_API_PASSWORD ou CEX_API_PASSWORD"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|future|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "mexc": {
        "required_envs": ["CEX_ID=mexc", "MEXC_API_KEY ou CEX_API_KEY", "MEXC_API_SECRET ou CEX_API_SECRET"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "bitget": {
        "required_envs": ["CEX_ID=bitget", "BITGET_API_KEY ou CEX_API_KEY", "BITGET_API_SECRET ou CEX_API_SECRET", "BITGET_API_PASSWORD ou CEX_API_PASSWORD"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "gateio": {
        "required_envs": ["CEX_ID=gateio", "GATEIO_API_KEY ou CEX_API_KEY", "GATEIO_API_SECRET ou CEX_API_SECRET"],
        "optional_envs": ["CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "outras_cex_ccxt": {
        "required_envs": ["CEX_ID=<exchange_id>", "CEX_API_KEY", "CEX_API_SECRET"],
        "optional_envs": ["CEX_API_PASSWORD", "CEX_OPTIONS_JSON"],
        "config_envs": ["CEX_MARKET_TYPE=trade|future|spot (trade normaliza para CCXT swap)"],
        "where_to_save": "secret manager > Chaves de Serviço",
    },
    "outras_dex_adapter": {
        "required_envs": ["DEX_ID=<id>", "DEX_ADAPTER_MODULE=pacote.modulo:Classe"],
        "optional_envs": ["DEX_CONFIG_JSON", "DEX_NETWORK=mainnet|testnet|devnet"],
        "config_envs": ["DEX_CONFIG_JSON sem segredos"],
        "where_to_save": "secrets exigidos pelo adapter em secret manager > Chaves de Serviço",
    },
}

# Entrega pelos canais do OpenClaw do operador (Telegram, WhatsApp, Discord...).
# A skill nao le token de bot; nao ha canal nem conta padrao.
DELIVERY_STATE = {
    "enabled": False,
    "stage": "teste",
    "channel": None,
    "target_saved": None,
    "account": None,
    "thread_id": None,
    "mention": "none",
    "path": "setup-live",
    "validation_required": ["setup-check", "doctor", "dry-run"],
}

DELIVERY_GUIDANCE = {
    "reference": "Docs/features/entrega-de-mensagens.md",
    "purpose": "Entregar os avisos pelos canais que o OpenClaw do operador ja tem configurados, sem token de bot na skill.",
    "required_config_envs": ["SETUP_NOTIFY_ENTRY_CHANNEL", "SETUP_NOTIFY_ENTRY_TARGET"],
    "optional_envs": [
        "SETUP_NOTIFY_ENTRY_ACCOUNT",
        "SETUP_NOTIFY_ENTRY_THREAD_ID",
        "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID",
        "SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT",
        "SETUP_NOTIFY_WHATSAPP_ENABLED",
        "SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET",
        "SETUP_NOTIFY_ENTRY_WHATSAPP_ACCOUNT",
    ],
    "optional_format_envs": [
        "SETUP_NOTIFY_BRAND",
        "SETUP_NOTIFY_TIMEZONE",
        "SETUP_NOTIFY_DISCORD_AUDIENCE",
        "SETUP_NOTIFY_DISCORD_BOX",
        "SETUP_NOTIFY_DISCORD_BOX_STYLE",
        "SETUP_NOTIFY_DISCORD_MENTION",
    ],
    "safe_defaults": {
        "stage": "teste",
        "mention": "none",
        "path": "setup-live",
    },
    "wizard_rules": [
        "Rodar depois da escolha inicial do wizard_path e antes de canal publico.",
        "O canal precisa estar configurado no OpenClaw do operador; a skill so chama `openclaw message send`.",
        "Nao ha canal padrao: perguntar qual canal do OpenClaw usar.",
        "Bot dedicado e uma conta dedicada no OpenClaw (SETUP_NOTIFY_ENTRY_ACCOUNT); vazio usa a conta padrao do OpenClaw.",
        "Topico de grupo do Telegram vai em SETUP_NOTIFY_ENTRY_THREAD_ID.",
        "Nunca pedir token ou segredo no chat; a skill nao le token de bot.",
        "Destino nao e segredo, mas deve comecar em canal/grupo de teste.",
        "Validar setup-check, doctor e rodar-setups-live --simular --max-iter 1 antes de live/publico.",
    ],
    "question_flow": [
        {
            "field": "delivery.enabled",
            "question": "Quer receber os avisos de entrada, alvo e stop num canal agora, deixar para depois ou nao usar?",
            "options": ["configurar_agora", "depois", "nao_usar"],
            "default": "depois",
        },
        {
            "field": "delivery.channel",
            "question": "Em qual canal do seu OpenClaw? (telegram, whatsapp, discord ou outro que ele tenha configurado)",
            "options": ["telegram", "whatsapp", "discord", "outro"],
        },
        {
            "field": "delivery.stage",
            "question": "Os avisos vao primeiro para um destino de teste ou direto para o publico?",
            "options": ["teste", "publico"],
            "default": "teste",
        },
        {
            "field": "delivery.target_saved",
            "question": "O destino (SETUP_NOTIFY_ENTRY_TARGET: chat, grupo ou canal) ja esta salvo?",
            "options": ["sim", "nao", "nao_sei"],
        },
        {
            "field": "delivery.account",
            "question": "Usar a conta padrao do seu OpenClaw ou um bot dedicado (uma conta dedicada configurada no OpenClaw)?",
            "options": ["conta_padrao", "bot_dedicado"],
            "default": "conta_padrao",
        },
        {
            "field": "delivery.thread_id",
            "question": "Se for grupo do Telegram com topicos: quer os avisos num topico especifico? (SETUP_NOTIFY_ENTRY_THREAD_ID)",
            "options": ["sim", "nao", "nao_se_aplica"],
            "default": "nao_se_aplica",
        },
        {
            "field": "delivery.mention",
            "question": "Deve mencionar alguem (ex.: @everyone no Discord)? Recomendo nao mencionar no primeiro teste.",
            "options": ["none", "@everyone", "custom"],
            "default": "none",
        },
    ],
}

VENUE_SELECTION_QUESTION = {
    "field": "venue_selection",
    "reason": "Define quais integrações, credenciais e passos de corretora/DEX serão necessários.",
    "question": "Quais venues você quer usar? Principais: DEX `nado` ou `hyperliquid`; CEX `kraken`, `binance`, `bybit`, `okx`, `kucoin`, `mexc`, `bitget` ou `gateio`. Também posso integrar outras CEXs via CCXT e outras DEXs por adapter. Responda, por exemplo: `DEX=nado CEX=kraken`, `CEX=binance` ou `DEX=hyperliquid CEX=bybit`.",
    "options": ["DEX=nado CEX=kraken", "DEX=hyperliquid CEX=bybit", "CEX=binance", "CEX=bybit", "CEX=okx", "CEX=kucoin", "CEX=mexc", "CEX=bitget", "CEX=gateio", "outra"],
    # Sem default: nao ha venue padrao, o operador escolhe.
}

DEFAULT_PAYLOAD = {
    "ok": True,
    "mode": "chat_first_onboarding",
    "skill": "trade-automatizado-openclaw",
    "introduction": "Vou configurar o trade automatizado em modo seguro: primeiro escolher DEX/CEX, depois diagnóstico/dry-run, sem trade. Live só depois de validação e confirmação explícita.",
    "reference": "references/onboarding-questionario.md",
    "credential_guidance": CREDENTIAL_GUIDANCE,
    "detailed_reference": "references/onboarding-detalhado.md",
    "delivery_reference": DELIVERY_GUIDANCE["reference"],
    "delivery_guidance": DELIVERY_GUIDANCE,
    "supported_venues": SUPPORTED_VENUES,
    "account_isolation_policy": ACCOUNT_ISOLATION_POLICY,
    "hyperliquid_official_links": HYPERLIQUID_OFFICIAL_LINKS,
    "hyperliquid_market_type_reference": HYPERLIQUID_MARKET_TYPE_REFERENCE,
    "dex_market_type_reference": DEX_MARKET_TYPE_REFERENCE,
    "cex_market_type_reference": CEX_MARKET_TYPE_REFERENCE,
    "venue_setup_guides": VENUE_SETUP_GUIDES,
    "venue_credential_requirements": VENUE_CREDENTIAL_REQUIREMENTS,
    "question_strategy": {
        "one_question_at_a_time": True,
        "explain_reason": True,
        "language": "pt-BR",
        "never_request_secrets_in_chat": True,
        "never_send_signup_links_in_short_wizard": True,
        "dry_run_before_live": True,
        "subaccount_required_by_default": False,
        "subaccount_user_decides": True,
        "must_not_hardcode_subaccount_requirement": True,
        "target_stop_mode_user_decides": True,
        "target_stop_mode_default": "desligado",
        "delivery_user_decides": True,
        "delivery_default_stage": "teste",
    },
    "wizard_paths": WIZARD_PATHS,
    "question_flow": [
        WIZARD_PATH_CHOICE,
        VENUE_SELECTION_QUESTION,
        {
            "field": "execution_mode",
            "reason": "Define quais credenciais e validações são necessárias.",
            "question": "Qual modo você quer configurar agora: `dex_only` na DEX escolhida, `cex_only` na CEX escolhida ou `hedged` usando as duas venues?",
            "options": ["dex_only", "cex_only", "hedged"],
        },
        {
            "field": "autonomy_mode",
            "reason": "Diz o que o agente pode fazer sozinho e o que protege voce em cada caso (ADR 0007).",
            "question": "Como o agente deve operar? `analise` (scanner, simulacao e dry-run; e o modo ate voce escolher outro), `real_com_aprovacao` (recomendado: cada comando de trade espera sua aprovacao pelo chat do OpenClaw) ou `real_autonomo` (opera sozinho; so as travas da exchange limitam a perda).",
            "options": ["analise", "real_com_aprovacao", "real_autonomo"],
            "default": "analise",
            "protections": {
                "analise": "nada a prender: nao abre ordem",
                "real_com_aprovacao": "tools.exec do OpenClaw em allowlist estreita, com aprovacao para os comandos de trade; mais key sem saque e capital isolado. security: full ou allowlist larga contornam a aprovacao.",
                "real_autonomo": "so a exchange: key sem saque e subconta com o capital que o bot pode perder",
            },
            "note": "AUTORIZAR_TRADE_REAL registra a decisao de operar real; nao e trava. O doctor avisa key com saque e OpenClaw sem aprovacao; BLOQUEAR_SAQUE=sim e BLOQUEAR_SEM_APROVACAO=sim transformam o aviso em bloqueio, se o operador quiser.",
            "reference": "Docs/decisions/0007-autonomia-do-agente.md",
        },
        {
            "field": "environment",
            "reason": "Separa teste, dry-run e preparação para live/mainnet.",
            "question": "Vai validar em testnet/sandbox, mainnet dry-run ou preparar mainnet live para depois?",
            "options": ["testnet", "sandbox", "mainnet_dry_run", "mainnet_live_later"],
        },
        {
            "field": "account_and_secrets_status",
            "reason": "Não faço cadastro nem recebo segredos no chat; só preciso saber se o acesso e as envs já estão prontos no env/secret manager seguro.",
            "question": "Você já tem conta/acesso nas venues escolhidas e as envs/secrets já estão salvas no env/secret manager seguro? sim, não ou não sei?",
            "options": ["yes", "no", "unknown"],
        },
        {
            "field": "sizing",
            "reason": "Live é bloqueado sem sizing explícito.",
            "question": "Qual sizing quer usar: margin-usd, notional, account-margin-slots ou dry-run sem sizing live?",
            "options": ["margin_usd", "notional", "account_margin_slots", "dry_run_only"],
        },
        {
            "field": "margin_mode",
            "reason": "Cross e isolated têm perfis de risco diferentes.",
            "question": "Prefere margem cross, isolated ou quer sugestão depois do diagnóstico?",
            "options": ["cross", "isolated", "suggest_after_diagnostics"],
        },
        {
            "field": "target_stop_mode",
            "reason": "Define se o setup só realiza parciais ou se também reposiciona o stop conforme os alvos são atingidos.",
            "question": "Quer o stop por alvo desligado, entrada-no-tp1 ou escada? Recomendo começar com desligado no primeiro live; entrada-no-tp1 move o stop para a entrada após TP1; escada move TP1->entrada, TP2->TP1, TP3->TP2.",
            "options": ["desligado", "entrada-no-tp1", "escada"],
            "default": "desligado",
            "env": "SETUP_LIVE_TARGET_STOP_MODE",
            "aliases": {
                "off": "desligado",
                "breakeven_on_tp1": "entrada-no-tp1",
                "ladder": "escada"
            },
            "native_stop_replacement": "managed_loop_only",
        },
        {
            "field": "delivery",
            "reason": "Define se e onde os avisos saem, pelos canais do OpenClaw do operador, sem token de bot na skill.",
            "question": "Quer receber os avisos num canal do seu OpenClaw (Telegram, WhatsApp, Discord...) agora, deixar para depois ou nao usar? Nao ha canal padrao, e nunca peco token.",
            "options": ["configurar_agora", "depois", "nao_usar"],
            "default": "depois",
            "reference": DELIVERY_GUIDANCE["reference"],
            "requires_config_envs": DELIVERY_GUIDANCE["required_config_envs"],
        },
        {
            "field": "next_safe_step",
            "reason": "Confirma validação segura antes de qualquer operação.",
            "question": "Posso rodar primeiro venues, setup-check e doctor sem exibir segredo e sem trade?",
            "options": ["venues+setup-check+doctor"],
        },
    ],
    "next_question": WIZARD_PATH_CHOICE,
    "state": {
        "wizard_path": None,
        "venue_selection": None,
        "dex_id": None,
        "cex_id": None,
        "dex_adapter_status": None,
        "cex_market_type": None,
        "execution_mode": None,
        "autonomy_mode": "analise",
        "environment": None,
        "account_and_secrets_status": None,
        "sizing": None,
        "margin_mode": None,
        "target_stop_mode": "desligado",
        "delivery": DELIVERY_STATE.copy(),
        "next_safe_step": "venues+setup-check+doctor",
        "questionnaire_completed": False,
    },
    "final_confirmation_template": "Plano: DEX {dex_id}, CEX {cex_id}, modo {execution_mode}, autonomia {autonomy_mode}, ambiente {environment}, contas/envs {account_and_secrets_status}, sizing {sizing}, margem {margin_mode}, stop por alvo {target_stop_mode}, entrega {delivery}. Próximo passo seguro: venues + setup-check + doctor, sem trade. Confirmo?",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Wizard curto trade-automatizado-openclaw")
    parser.add_argument("--json", action="store_true", help="Imprime payload de onboarding em JSON")
    args = parser.parse_args()
    # Sempre seguro para automação: se não for TTY, emite JSON.
    if args.json or not sys.stdin.isatty():
        print(json.dumps(DEFAULT_PAYLOAD, indent=2, ensure_ascii=False))
        return
    print(json.dumps(DEFAULT_PAYLOAD, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
