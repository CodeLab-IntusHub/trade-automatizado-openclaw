# Aspira Trade — autenticação TradingView sem senha em env

## Decisão operacional

Usar sessão persistente de Chromium para a conta TradingView autorizada pelo owner.

Não usar login/senha em `.env` como rotina. Credenciais ficam no 1Password apenas para recuperação/relogin manual.

## Envs principais

```env
SETUP_NOTIFY_TRADINGVIEW_PROFILE_DIR=~/.openclaw/state/trade-automatizado-openclaw/tradingview-profile
SETUP_NOTIFY_TRADINGVIEW_REQUIRE_AUTH=true
SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE=true
SETUP_NOTIFY_ENTRY_ENABLED=false
```

`ENTRY_ENABLED=false` deve continuar até validação visual dos Pines/layouts.

## Fluxo seguro

1. Criar/usar perfil Chromium persistente no servidor.
2. Guardar a credencial do TradingView no 1Password.
3. Rodar login automático via `op run` somente para criar/renovar a sessão local.
4. Se TradingView pedir captcha/2FA/verificação manual, parar o automático e fazer login assistido.
5. Validar sessão com `workspace/tradingview_session.js check`.
6. Salvar/publicar Pines/layouts na conta logada.
7. Configurar `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_*` ou URLs/layouts por setup.
8. Rodar teste visual em canal de teste.
9. Só religar entrega automática após aprovação.

## Comandos

Healthcheck:

```bash
node workspace/tradingview_session.js check \
  --profile-dir ~/.openclaw/state/trade-automatizado-openclaw/tradingview-profile
```

Login automático via 1Password, sem salvar senha em arquivo:

```bash
op run --env-file ~/.openclaw/state/trade-automatizado-openclaw/tradingview-1password.env -- \
  node workspace/tradingview_session.js login-auto \
    --profile-dir ~/.openclaw/state/trade-automatizado-openclaw/tradingview-profile \
    --headless true \
    --timeout-ms 180000
```

O arquivo de env deve conter somente referências `op://`, seguindo `references/tradingview-1password.env.template`.

Login assistido, quando houver navegador interativo disponível no servidor:

```bash
node workspace/tradingview_session.js login \
  --profile-dir ~/.openclaw/state/trade-automatizado-openclaw/tradingview-profile \
  --headless false \
  --timeout-ms 300000
```

## Guardrail

Se `SETUP_NOTIFY_TRADINGVIEW_REQUIRE_AUTH=true`, o renderer falha quando o perfil não estiver autenticado.

Se `SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE=true`, o renderer falha quando o setup não tiver Pine configurado.

Isso evita renderizar fallback público e chamar de Pine real.
