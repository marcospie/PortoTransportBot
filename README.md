# Porto Transport Bot

Bot de Telegram (e WhatsApp) para consultar transportes publicos do Porto em tempo real.

> English version: [README.en.md](README.en.md)

## Funcionalidades

- **Autocarros STCP** - Tempos de chegada em tempo real para todas as paragens
- **Metro do Porto** - Horarios por estacao e por linha (GTFS + frequencias conhecidas)
- **MetroBus (BRT)** - Linhas, paragens e frequencias do MetroBus
- **Comboios CP** - Estacoes e linhas suburbanas da CP
- **Planeador de trajetos** - Sugestoes de rota entre dois pontos (`/route`)
- **Paragens perto de mim** - Partilha a tua localizacao e ve o que passa por perto
- **Favoritos** - Guarda as tuas paragens e estacoes mais usadas
- **Perfil de commuter** - Guarda casa/trabalho e consulta o teu trajeto habitual num toque
- **Calculador de zonas Andante** - Descobre quantas zonas precisas entre dois pontos
- **Alertas de servico** - Interrupcoes e avisos das operadoras
- **Acessibilidade** - Elevadores, rampas e estado de manutencao por estacao
- **Meteorologia** - Previsao para o Porto, util antes de sair
- **Eventos no Porto** - Eventos e como chegar la de transportes publicos
- **Guia turistico** - Pontos de interesse e bilhetes recomendados
- **Modo inline** - Escreve `@NomeDoBot paragem` em qualquer conversa
- **Bilingue** - Portugues e Ingles, automatico pelo idioma do cliente Telegram
- **Configuracoes** - Raios de busca, numero de resultados, idioma e notificacoes
- **Interface interativa** - Botoes e menus inline para navegacao facil

## Comandos do Bot

Lista completa dos comandos registados em `bot/main.py`:

| Comando | Descricao |
|---------|-----------|
| `/start` | Menu principal |
| `/help` | Ajuda |
| `/bus` | Menu de autocarros STCP |
| `/metro` | Menu do Metro do Porto |
| `/stop BCM2` | Tempos reais de uma paragem STCP por codigo |
| `/station Trindade` | Horarios de uma estacao de metro |
| `/route` | Planear um trajeto |
| `/favorites` | Gerir favoritos |
| `/fav` | Adicionar/consultar favorito rapido |
| `/settings` | Configuracoes (raios, resultados, idioma, notificacoes) |
| `/metrobus` | MetroBus (BRT) |
| `/comboios` | Comboios CP |
| `/estacao Campanha` | Estacao de comboios CP |
| `/zonas` | Calculador de zonas Andante |
| `/tourist` | Guia turistico |
| `/commuter` | Perfil de commuter (casa/trabalho) |
| `/alertas` | Alertas de servico |
| `/acessibilidade` | Acessibilidade das estacoes |
| `/meteo` | Meteorologia no Porto |
| `/eventos` | Eventos no Porto |

Tambem podes enviar texto livre - o bot tenta encontrar paragens ou estacoes que
correspondam - ou partilhar a tua localizacao para ver transportes perto de ti.

## Como usar

### 1. Criar o bot no Telegram

1. Fala com o [@BotFather](https://t.me/BotFather) no Telegram
2. Envia `/newbot` e segue as instrucoes
3. Copia o token gerado

### 2. Configurar

```bash
cp .env.example .env
# Edita .env e cola o teu token
```

### 3. Executar

**Sem Docker:**

```bash
pip install -r requirements.txt
python run.py
```

**Com Docker:**

```bash
# O container corre como UID 10001, por isso da-lhe permissao na pasta data/
sudo chown -R 10001:10001 ./data
docker compose up -d bot
```

## Variaveis de ambiente

Lista **completa** de todas as variaveis lidas pelo codigo.

### Bot de Telegram

| Variavel | Obrigatoria | Default | Lida em | Para que serve |
|----------|-------------|---------|---------|----------------|
| `TELEGRAM_BOT_TOKEN` | **Sim** | *(vazio)* | `bot/config.py` | Token do @BotFather. Sem ele o `run.py` imprime um erro e termina. |
| `DATABASE_URL` | Nao, mas **fortemente recomendada** | *(vazio)* | `bot/database.py` | DSN PostgreSQL (`postgresql://user:pass@host:5432/db`). **Sem ela os dados dos utilizadores sao guardados em ficheiros JSON e PERDEM-SE em cada restart** - ver [Persistencia de dados](#persistencia-de-dados). |

### Servico de WhatsApp (opcional)

| Variavel | Obrigatoria | Default | Lida em | Para que serve |
|----------|-------------|---------|---------|----------------|
| `WHATSAPP_TOKEN` | Sim (para WhatsApp) | *(vazio)* | `whatsapp/app.py` | Access token permanente da Meta, para chamadas Graph API de saida. |
| `WHATSAPP_PHONE_ID` | Sim (para WhatsApp) | *(vazio)* | `whatsapp/app.py` | Phone number ID da Meta. |
| `WHATSAPP_VERIFY_TOKEN` | Sim (para WhatsApp) | `porto-transport-bot` | `whatsapp/app.py` | Segredo partilhado, ecoado no handshake `GET /webhook`. |
| `WHATSAPP_APP_SECRET` | **Sim em producao** | *(vazio)* | `whatsapp/app.py` | App Secret da Meta. Autentica cada `POST /webhook` com HMAC-SHA256 sobre o corpo cru, comparado com `X-Hub-Signature-256`. **Se estiver vazia o webhook responde 403 a todos os POST** (fail-closed): sem isto, qualquer pessoa que descubra o URL pode injetar mensagens falsas. |
| `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS` | Nao | *(vazio)* | `whatsapp/app.py` | Escape hatch **so para desenvolvimento** (`true`/`1`/`yes`/`on`). So tem efeito quando `WHATSAPP_APP_SECRET` esta vazia. **Nunca definir em producao.** |
| `WHATSAPP_PORT` | Nao | `8080` | `whatsapp/app.py` | Porta do servidor de desenvolvimento; tambem usada pelo `docker-compose.yml`. |

### Fornecidas pela plataforma

| Variavel | Quem define | Para que serve |
|----------|-------------|----------------|
| `PORT` | Heroku / plataformas Procfile | Porta em que o processo `web:` (gunicorn) tem de escutar. Ja usada no `Procfile`. |

> O `.env.example` deste repositorio ainda nao inclui `WHATSAPP_APP_SECRET` nem
> `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS`. Usa a tabela acima como referencia.

## Persistencia de dados

**Leitura obrigatoria antes de fazer deploy.**

O `bot/database.py` funciona de duas maneiras:

1. **Com `DATABASE_URL`** - usa PostgreSQL (via `asyncpg`), cria o schema sozinho
   (`users`, `favorites`, `user_settings`, `commuter_profiles`) e os dados sobrevivem
   a restarts e redeploys.
2. **Sem `DATABASE_URL`** - fallback para ficheiros JSON em `data/`
   (`data/favorites/`, `data/settings/`, `data/commuter/`, `data/users/`).

O fallback JSON e conveniente em local, mas **Railway, Heroku e containers Docker sem
volume tem sistema de ficheiros efemero**: em cada redeploy, restart ou crash, tudo o
que esta em `data/` desaparece. Isso significa perder **os favoritos, as configuracoes
e os perfis de commuter de todos os utilizadores**.

Ao arrancar sem `DATABASE_URL` o bot escreve um aviso `WARNING` bem visivel nos logs a
explicar exatamente isto.

### Opcao recomendada: PostgreSQL

1. Cria uma base de dados PostgreSQL (Railway, Neon, Supabase, Heroku Postgres, ...)
2. Define `DATABASE_URL` no servico do bot
3. Reinicia o bot

Nao e preciso correr migracoes a mao: o `init_db()` executa `CREATE TABLE IF NOT EXISTS`
e as migracoes `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` no arranque.

### Como verificar que a persistencia esta a funcionar

1. Nos logs de arranque **nao** deve aparecer o aviso `DATABASE_URL is NOT set`.
   Em vez disso deve aparecer `PostgreSQL database initialised (pool ready)`.
2. No Telegram, adiciona um favorito com `/favorites` (ou o botao de estrela).
3. Faz um redeploy/restart do servico.
4. Envia `/favorites` outra vez: o favorito tem de continuar la.
5. Opcionalmente, confirma na base de dados:
   ```sql
   SELECT count(*) FROM favorites;
   SELECT count(*) FROM user_settings;
   SELECT count(*) FROM commuter_profiles;
   ```

### Migrar favoritos que ja existem em JSON

Se ja tinhas utilizadores em modo JSON e acabaste de configurar o PostgreSQL, ha um
helper que importa os ficheiros existentes:

```python
import asyncio
from bot.database import init_db, migrate_from_json, close_db

async def main():
    await init_db()             # precisa de DATABASE_URL definida
    await migrate_from_json()   # le data/favorites/*.json
    await close_db()

asyncio.run(main())
```

## Deploy

### Railway

1. Cria um novo projeto no [Railway](https://railway.app) e liga o teu repositorio GitHub
2. **Adiciona o PostgreSQL**: `New` -> `Database` -> `Add PostgreSQL`
3. Nas `Variables` do servico do bot define:
   - `TELEGRAM_BOT_TOKEN` = o token do @BotFather
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencia o servico Postgres)
4. Deploy automatico a cada commit (CD ativado por defeito)
5. Confirma nos logs que aparece `PostgreSQL database initialised (pool ready)`

O `railway.toml` usa `restartPolicyType = "ALWAYS"`. Isto e importante: com o antigo
`on_failure` + `restartPolicyMaxRetries = 10` o bot ficava **permanentemente em baixo**
depois de 10 crashes (por exemplo durante uma falha prolongada da API do Telegram) ate
alguem fazer um redeploy manual.

**Se mesmo assim preferires o modo JSON**, tens de montar um volume persistente. Volumes
**nao** podem ser declarados no `railway.toml` (o schema config-as-code so tem opcoes de
build/deploy), por isso configura-o no dashboard: servico -> `Settings` -> `Volumes` ->
`Add Volume`, com mount path `/app/data`. O PostgreSQL continua a ser a opcao mais segura.

### Heroku e outras plataformas com Procfile

O `Procfile` declara dois processos:

```
worker: python run.py                       # bot de Telegram (long polling)
web:    gunicorn ... whatsapp.app:app       # servico de WhatsApp
```

```bash
heroku create
heroku addons:create heroku-postgresql:essential-0   # define DATABASE_URL automaticamente
heroku config:set TELEGRAM_BOT_TOKEN=xxxxx
git push heroku main
heroku ps:scale worker=1        # bot de Telegram
# heroku ps:scale web=1         # apenas se quiseres tambem o WhatsApp
```

O addon `heroku-postgresql` define `DATABASE_URL` por ti - sem ele o filesystem do dyno
e efemero e os dados desaparecem a cada restart (que no Heroku acontece pelo menos uma
vez por dia).

### Docker / docker-compose

```bash
sudo chown -R 10001:10001 ./data    # o container corre como UID 10001
docker compose up -d                # bot + whatsapp
docker compose up -d bot            # apenas o bot de Telegram
docker compose ps                   # mostra o estado dos healthchecks
```

Notas sobre a imagem:

- Corre como utilizador **nao-root** (`appuser`, UID/GID 10001)
- O `.dockerignore` mantem `.git/`, `tests/` e o `data/` local fora da imagem
- Tem um `HEALTHCHECK` que verifica que o package importa e que `/app/data` e escrivel
  pelo `appuser` (deteta um volume montado com o owner errado, que silenciosamente
  quebraria o armazenamento JSON)
- O servico `whatsapp` tem um healthcheck HTTP proprio contra `/health`
- Ambos os servicos usam `restart: unless-stopped`

## Servico de WhatsApp

Alternativa em WhatsApp, servida pelo Flask app em `whatsapp/app.py`
(ver tambem [whatsapp/README.md](whatsapp/README.md)).

### 1. Credenciais da Meta

1. Cria uma [Meta Business Account](https://business.facebook.com/)
2. Cria uma app WhatsApp Business no [Meta Developer Portal](https://developers.facebook.com/)
3. Na seccao WhatsApp copia o **access token permanente** e o **Phone number ID**
4. Em `App Settings` -> `Basic` copia o **App Secret**

### 2. Variaveis de ambiente

```bash
WHATSAPP_TOKEN=<access token permanente>
WHATSAPP_PHONE_ID=<phone number id>
WHATSAPP_VERIFY_TOKEN=<string aleatoria a tua escolha>
WHATSAPP_APP_SECRET=<app secret da Meta>   # obrigatorio: sem isto o webhook devolve 403
```

`WHATSAPP_APP_SECRET` nao e opcional em producao. Cada `POST /webhook` e autenticado com
HMAC-SHA256 sobre o corpo cru do pedido contra o header `X-Hub-Signature-256` da Meta. Se
a variavel estiver vazia o servico **falha fechado** (403 em todos os POST), porque sem
essa verificacao qualquer pessoa que descubra o URL do webhook consegue injetar mensagens
falsas e fazer o bot enviar WhatsApps para numeros arbitrarios.

### 3. Correr em producao

Usa sempre um servidor WSGI a serio - o servidor de desenvolvimento do Flask e
single-threaded e faria a Meta reenviar os webhooks, gerando respostas duplicadas:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 whatsapp.app:app
```

E exatamente isto que o processo `web:` do `Procfile` e o servico `whatsapp` do
`docker-compose.yml` executam. Em local, para testes rapidos:

```bash
python -m whatsapp.app
```

### 4. Configurar o webhook

1. O servico tem de estar acessivel por HTTPS num dominio publico
   (a Meta nao aceita HTTP nem `localhost`; em local usa `ngrok http 8080`)
2. No Meta Developer Portal: `WhatsApp` -> `Configuration` -> `Webhook` -> `Edit`
   - **Callback URL**: `https://o-teu-dominio/webhook`
   - **Verify token**: o mesmo valor de `WHATSAPP_VERIFY_TOKEN`
3. Clica em `Verify and save` (a Meta faz um `GET /webhook` com `hub.challenge`)
4. Subscreve o evento `messages`

### 5. Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/webhook` | Handshake de verificacao da Meta (`hub.challenge`) |
| `POST` | `/webhook` | Mensagens recebidas; exige `X-Hub-Signature-256` valido |
| `GET` | `/health` | Health check. Devolve `{"status": "ok", ...}` e o modo de verificacao de assinatura |

Em plataformas com healthchecks HTTP (Railway, Heroku, Kubernetes) aponta o health check
para `/health`.

## Fontes de dados

- **STCP**: API nao-oficial do [stcp.pt](https://stcp.pt) para tempos reais + GTFS estatico
- **Metro do Porto**: Dados GTFS de [opendata.porto.digital](https://opendata.porto.digital)
  (resolvidos dinamicamente via CKAN) + frequencias conhecidas
- **CP**: Dados publicos de estacoes e linhas suburbanas
- **Meteorologia / eventos**: APIs publicas (ver `bot/services/`)

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Estrutura do projeto

```
run.py                 # Ponto de entrada (chama bot.main.main)
bot/
  main.py              # Registo de handlers, comandos e ciclo de vida
  config.py            # Configuracao, resolucao dos feeds GTFS
  database.py          # PostgreSQL (asyncpg) + fallback JSON: users,
                       #   favorites, user_settings, commuter_profiles
  handlers/            # Handlers de comandos e callbacks
    start.py           #   /start, /help
    bus.py             #   Autocarros STCP
    metro.py           #   Metro do Porto
    metrobus.py        #   MetroBus (BRT)
    trains.py          #   Comboios CP
    routes.py          #   Planeador de trajetos
    favorites.py       #   Favoritos
    settings.py        #   Configuracoes do utilizador
    commuter.py        #   Perfil de commuter
    zones.py           #   Calculador de zonas Andante
    alerts.py          #   Alertas de servico
    accessibility.py   #   Acessibilidade das estacoes
    tourist.py         #   Guia turistico
    events.py          #   Eventos no Porto
    weather.py         #   Meteorologia
    location.py        #   Paragens perto de mim
    inline.py          #   Modo inline (@NomeDoBot)
  services/            # Acesso a dados e regras de negocio
                       #   stcp, metro, metro_realtime, metrobus, cp,
                       #   trip_planner, zones, fares, alerts,
                       #   accessibility, tourist, events, weather,
                       #   notifications
  keyboards/
    inline.py          # Builders de teclados inline
  utils/
    cache.py           # Cache TTL em memoria
    formatting.py      # Formatacao de mensagens (MarkdownV2)
    i18n.py            # Traducoes PT/EN
    search.py          # Pesquisa difusa de paragens/estacoes
    telegram.py        # Helpers de Telegram
whatsapp/              # Variante WhatsApp (Flask + Meta Cloud API)
  app.py               #   Rotas /webhook e /health, verificacao HMAC
  worker.py            #   Processamento das mensagens recebidas
  storage.py           #   Estado das sessoes
  formatting.py        #   Formatacao das mensagens WhatsApp
  strings.py           #   Textos
tests/                 # Testes unitarios (pytest)
data/                  # Cache GTFS + fallback JSON (efemero! ver Persistencia)
Dockerfile             # Imagem non-root com HEALTHCHECK
docker-compose.yml     # Servicos bot + whatsapp
Procfile               # worker: (Telegram) e web: (WhatsApp/gunicorn)
railway.toml           # Config de deploy do Railway
```
