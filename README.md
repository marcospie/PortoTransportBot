# Porto Transport Bot

Bot de Telegram para consultar transportes publicos do Porto em tempo real.

## Funcionalidades

- **Autocarros STCP** - Tempos de chegada em tempo real para todas as paragens
- **Metro do Porto** - Horarios estimados com base nas frequencias conhecidas
- **Pesquisa inteligente** - Pesquisa por nome ou codigo de paragem/estacao
- **Favoritos** - Guarda as tuas paragens e estacoes mais usadas
- **Interface interativa** - Botoes e menus inline para navegacao facil

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

**Com Docker (recomendado):**

```bash
docker compose up -d
```

**Sem Docker:**

```bash
pip install -r requirements.txt
python run.py
```

**No Railway:**

1. Cria um novo projeto no [Railway](https://railway.app)
2. Liga o teu repositorio GitHub
3. Adiciona a variavel de ambiente `TELEGRAM_BOT_TOKEN` nas settings do servico
4. Deploy automatico a cada commit (CD ativado por defeito)

## Comandos do Bot

| Comando | Descricao |
|---------|-----------|
| `/start` | Menu principal |
| `/bus` | Menu de autocarros STCP |
| `/metro` | Menu do Metro do Porto |
| `/stop BCM2` | Consulta rapida de paragem |
| `/station Trindade` | Consulta rapida de estacao |
| `/favorites` | Gerir favoritos |
| `/help` | Ajuda |

Tambem podes enviar texto livre - o bot tenta encontrar paragens ou estacoes que correspondam.

## Fontes de dados

- **STCP**: API nao-oficial do [stcp.pt](https://stcp.pt) para tempos reais
- **Metro do Porto**: Dados GTFS de [opendata.porto.digital](https://opendata.porto.digital) + frequencias conhecidas

## Testes

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Estrutura do projeto

```
bot/
  main.py           # Ponto de entrada e registo de handlers
  config.py          # Configuracao
  handlers/          # Handlers de comandos e callbacks
    start.py         # /start, /help
    bus.py           # Autocarros STCP
    metro.py         # Metro do Porto
    favorites.py     # Favoritos
  services/          # Servicos de dados
    stcp.py          # API STCP (tempo real)
    metro.py         # Dados Metro (GTFS + frequencias)
  keyboards/         # Teclados inline
    inline.py        # Builders de teclados
  utils/             # Utilitarios
    cache.py         # Cache TTL em memoria
    formatting.py    # Formatacao de mensagens
tests/               # Testes unitarios
```
