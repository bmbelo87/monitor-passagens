# Monitor de passagens: São Paulo ↔ Belo Horizonte

Consulta o Google Flights pela SerpApi, salva no SQLite a menor tarifa encontrada para cada combinação de datas e manda alertas ao Telegram quando identifica queda, novo menor preço registrado ou valor abaixo do limite.

Padrão: GRU ou CGH → CNF, ida em 17/12/2026 e volta em 20/12/2026, sem datas alternativas. O SerpApi aceita GRU e CGH juntos numa busca, então cada rodada faz uma única consulta. O intervalo está configurado em 6 horas, estimando cerca de 120 buscas em um ciclo de 30 dias.

## Custo e cota

O plano gratuito da SerpApi inclui 250 buscas por mês. Com uma busca a cada 6 horas, o monitor usa cerca de 120 por ciclo de 30 dias, deixando margem para consultas manuais ou outros usos da mesma chave. Não reinicie o processo repetidamente: cada inicialização dispara uma rodada imediatamente. Confira a cota no painel da SerpApi.

Preços e cotas mudam; consulte a [página de preços da SerpApi](https://serpapi.com/pricing). Cada busca concluída consome uma consulta. Este programa não faz nenhuma chamada automaticamente até ser iniciado.

## Configuração no Windows

Requisitos: Python 3.10 ou mais recente, chave SerpApi e bot do Telegram.

Na pasta do projeto, abra o PowerShell e rode:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Preencha `SERPAPI_API_KEY` no `.env`. Para o Telegram:

1. Converse com `@BotFather` no Telegram, crie um bot e copie o token para `TELEGRAM_BOT_TOKEN`.
2. Abra uma conversa com o bot e envie `/start`.
3. Abra `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` no navegador e copie `message.chat.id` para `TELEGRAM_CHAT_ID`. Mantenha o token privado.

## Rodar

```powershell
.\.venv\Scripts\python.exe monitor.py
```

O monitor consulta ao iniciar e repete no intervalo de `POLL_INTERVAL_MINUTES` (60 minutos por padrão). Para rodar continuamente, deixe o computador ligado e configure o Agendador de Tarefas do Windows para iniciar o script ao entrar no Windows. O histórico fica em `data/fares.sqlite3`.

## Rodar gratuitamente pelo GitHub Actions

O workflow em `.github/workflows/monitor.yml` executa uma busca a cada 6 horas e encerra. Na primeira execução sem histórico, envia a busca inicial; depois, envia alertas de mudança conforme os preços registrados. O histórico SQLite é salvo em `data/fares.sqlite3` por um commit automático.

1. Crie um repositório **privado** no GitHub e envie os arquivos do projeto. Não envie `.env` nem a pasta `.venv`.
2. No repositório, abra **Settings → Secrets and variables → Actions → New repository secret** e crie estes três secrets: `SERPAPI_API_KEY`, `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Abra **Actions**, habilite os workflows se o GitHub solicitar e selecione **Monitor de passagens → Run workflow** para iniciar uma busca manual. As próximas execuções ficam agendadas a cada 6 horas.

O horário do agendamento pode atrasar alguns minutos. Cada execução agendada faz uma rodada de busca; com a configuração padrão de uma combinação de datas, são aproximadamente 120 consultas por mês. O `GITHUB_TOKEN` do próprio workflow atualiza o banco SQLite no repositório.

## Variáveis principais

| Variável | Padrão | Uso |
|---|---:|---|
| `ORIGIN_AIRPORTS` | `GRU,CGH` | Aeroportos de origem considerados |
| `DESTINATION_AIRPORT` | `CNF` | Aeroporto de Belo Horizonte |
| `DEPARTURE_DATE` / `RETURN_DATE` | `2026-12-17` / `2026-12-20` | Ida e volta |
| `DATE_WINDOW_DAYS` | `0` | `0` busca só as datas definidas |
| `MAX_PRICE_BRL` | `500` | Limite que dispara alerta |
| `ADULTS` | `1` | Número de adultos |
| `POLL_INTERVAL_MINUTES` | `360` | Intervalo entre consultas (6 horas) |

O preço e as condições são os exibidos no resultado no momento da busca; bagagem, assentos e regras tarifárias podem variar. Confirme a tarifa final no site de venda antes de comprar. O monitor guarda o menor valor que ele próprio observou no histórico; isso não garante que seja o menor preço de todo o mercado.
