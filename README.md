# Bot Telegram + OpenAI

Este projeto entrega um bot de Telegram que conversa com usuarios usando a API publica da OpenAI. O codigo foi reorganizado para ficar modular, seguro em relacao a variaveis sensiveis e facil de manter para trabalhos academicos ou portfolio.

## Principais recursos
- Estrutura em modulos (`bot/`) separando configuracao, cliente do Telegram e cliente da OpenAI.
- Historico por chat guardado em memoria para respostas mais naturais.
- Transcricao de audios (voz ou arquivos) usando Whisper via OpenAI e analise de imagens com o modelo multimodal.
- Buffer inteligente: o bot espera alguns segundos antes de responder, agrupando mensagens consecutivas.
- Teclado de atalhos com comandos frequentes (/start, /help, /reset).
- Configuracao via `.env` (exemplo em `.env.example`) para manter tokens fora do codigo.

## Requisitos
- Python 3.10 ou superior.
- Dependencias listadas em `requirements.txt`.

### Instalacao das dependencias
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Configurando as variaveis de ambiente
1. Copie o arquivo de exemplo:
   ```bash
   copy .env.example .env
   ```
2. Edite `.env` preenchendo:
   - `TELEGRAM_BOT_TOKEN`: token fornecido pelo BotFather.
   - `OPENAI_API_KEY`: chave da API da OpenAI.
   - `OPENAI_MODEL`: modelo desejado (padrao `gpt-4o-mini`).
   - `OPENAI_TRANSCRIPTION_MODEL`: modelo para transcricao de audio (padrao `gpt-4o-mini-transcribe`).
   - `RESPONSE_BUFFER_SECONDS`: tempo de espera antes da resposta (ex.: `3` aguarda ~3 segundos).

> Nunca suba sua chave real para o Git. O `.gitignore` ja impede que `.env` seja versionado.

## Executando o bot
```bash
python main.py
```

O bot usa long polling; deixe o processo rodando e envie mensagens pelo Telegram.

## Estrutura dos arquivos
```
bot/
  app.py            # Loop principal e fluxo da conversa
  config.py         # Carrega Settings a partir das variaveis de ambiente
  openai_client.py  # Cliente para Chat Completions e transcricoes da OpenAI
  telegram_client.py# Cliente HTTP com retries para a API do Telegram
main.py             # Ponto de entrada que inicializa o BotApp
requirements.txt    # Dependencias do projeto
.env.example        # Exemplo de configuracao
README.md           # Este guia
```

## Evolucoes sugeridas
- Persistir historico em banco/redis para manter contexto entre reinicios.
- Criar testes automatizados para os modulos de configuracao e clientes HTTP.
- Adicionar comandos especificos do curso (por exemplo, materiais ou links rapidos).
