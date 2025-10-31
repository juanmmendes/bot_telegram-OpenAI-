# Bot Telegram + OpenAI

Este projeto entrega um bot de Telegram que conversa com usuarios usando a API publica da OpenAI. O codigo foi reorganizado para ficar modular, seguro em relacao a variaveis sensiveis e facil de manter para trabalhos academicos ou portfolio.

## Principais recursos
- Estrutura em modulos (`bot/`) separando configuracao, cliente do Telegram e cliente da OpenAI.
- Historico por chat guardado em memoria para respostas mais naturais.
- Transcricao de audios (voz ou arquivos) usando Whisper via OpenAI e analise de imagens com o modelo multimodal.
- Respostas humanizadas com tom acolhedor e organizacao em listas/paragrafos curtos.
- Buffer inteligente: o bot espera alguns segundos antes de responder, agrupando mensagens consecutivas.
- Teclado de atalhos com comandos frequentes (/start, /help, /cotacoes, /reset) e botao "Verificar cotacoes" sempre disponivel no menu.
- Consulta cotacoes de moedas em tempo real (USD, EUR, GBP, JPY, ARS, BTC vs. BRL) usando a AwesomeAPI, tanto automaticamente quando o usuario pergunta quanto sob demanda pelo menu.
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

## Publicando no GitHub
O projeto ainda nao foi enviado para nenhum repositorio remoto. Para subir no seu GitHub:

1. Crie um repositório vazio na sua conta (sem README licenca ou .gitignore).
2. No terminal, defina o remoto e envie o historico:
   ```bash
   git remote add origin https://github.com/<seu-usuario>/<seu-repo>.git
   git push -u origin work
   ```
3. Caso prefira usar `main` ou `master`, ajuste o nome da branch local antes do push (`git branch -m work main`).

Isso garantira que o mesmo codigo presente aqui fique disponivel no GitHub.

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
