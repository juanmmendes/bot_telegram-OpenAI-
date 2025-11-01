# Bot Telegram + OpenAI

Assistente virtual em portugues que conversa no Telegram, entende texto, audio e imagem, e responde usando a OpenAI com direito a contexto de cotacoes em tempo real.

## Essencia do Projeto
- **Entrada multicanal**: texto, voz e imagens sao tratados sem comandos complexos.
- **Contexto vivo**: detecta pedidos de cotacao e consulta a AwesomeAPI antes de falar com a IA.
- **Fluxo modular**: cada responsabilidade fica em um arquivo especifico dentro de `bot/`.
- **Seguranca**: chaves e tokens ficam em `.env`, longe do codigo versionado.

## Fluxo de Mensagens
1. `main.py` cria uma instacia de `BotApp` e inicia o polling no Telegram.
2. `BotApp.run()` busca atualizacoes com `getUpdates` e distribui cada mensagem para `_handle_update`.
3. `ChatState` registra o historico individual e acumula novas partes (texto, audio, imagem) em `pending_parts`.
4. Quando o buffer atinge o intervalo configurado (`RESPONSE_BUFFER_SECONDS`), `_reply_with_buffer` monta o prompt final.
5. `_build_realtime_context` detecta moedas mencionadas e adiciona dados recentes da AwesomeAPI.
6. `OpenAIClient.generate_reply` envia historico + contexto para a OpenAI e retorna a resposta.
7. `TelegramClient.sendMessage` responde ao usuario mantendo a thread correta.

## Buffer Inteligente (exemplo)
```
tempo   entrada                          acao
0.0 s   "oi bot!"                        guardado em pending_parts
0.9 s   mensagem de voz                  baixada, transcrita e anexada como texto
1.6 s   foto com legenda                 baixada, convertida para data:image/... e anexada
2.7 s   nenhum novo update               buffer dispara, prompt completo segue para a OpenAI
```
Beneficios: menos chamadas para a OpenAI, respostas mais completas e conversas fluindo naturalmente.

## Suporte Multimodal
- **Texto**: processado imediatamente; atalhos reconhecem palavras como "Ajuda" ou "Verificar cotacoes".
- **Audio**: `_process_voice_message` baixa o arquivo, identifica o MIME, transcreve com Whisper (`OpenAIClient.transcribe_audio`) e adiciona a transcricao ao prompt.
- **Imagem**: `_queue_image_from_file` faz download, gera Base64, detecta o tipo (`_guess_image_mime`) e inclui a imagem no prompt multimodal, com legenda opcional.

## Comandos e Atalhos
```
| comando / atalho             | acao                                                          |
|------------------------------|---------------------------------------------------------------|
| /start                       | Mensagem de boas-vindas e teclado principal                   |
| /help ou "Ajuda"             | Guia rapido com recursos disponiveis                          |
| /cotacoes                    | Consulta USD, EUR e GBP contra BRL                            |
| /reset ou "Resetar conversa" | Limpa historico do chat atual                                 |
| /sobre                       | Mostra um resumo do projeto                                   |
| "Conversar com IA"           | Confirma ao usuario que o bot esta pronto para ouvir          |
| "Verificar cotacoes"         | Dispara consulta de moedas via menu sem precisar de comando   |
```

## Estrutura do Projeto
```
bot/
  app.py            # Loop principal, buffer, midias, cotacoes, chamadas OpenAI
  config.py         # Carrega variaveis de ambiente e valida configuracao
  openai_client.py  # Chat Completions e transcricao de audio
  telegram_client.py# Cliente HTTP com retries, menus e downloads
main.py             # Ponto de entrada que inicia o bot
requirements.txt    # Dependencias do projeto
.env.example        # Modelo de configuracao
```

## Configuracao e Execucao
1. Crie um ambiente virtual e instale dependencias:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copie e edite o arquivo de variaveis:
   ```
   copy .env.example .env
   ```
   Preencha:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL` (padrao `gpt-4o-mini`)
   - `OPENAI_TRANSCRIPTION_MODEL` (padrao `gpt-4o-mini-transcribe`)
   - `RESPONSE_BUFFER_SECONDS` (ex.: `3` para agrupar mensagens por cerca de 3 segundos)
3. Execute o bot:
   ```
   python main.py
   ```
   O processo usa long polling. Mantenha o terminal aberto e converse com o bot no Telegram.

> `.env` continua ignorado pelo Git. Guarde seus tokens com cuidado.

## Personalizacao Recomendada
- Ajuste o `SYSTEM_PROMPT` em `bot/app.py` para alterar estilo e tom das respostas.
- Modifique `DEFAULT_CURRENCY_CODES` para incluir outras moedas ou criptos de interesse.
- Adapte `MENU_KEYBOARD` com atalhos proprios do seu projeto.
- Acrescente novos blocos em `_build_realtime_context` para integrar APIs adicionais (clima, noticias, dados internos).

## Checklist Final
- [ ] Dependencias instaladas e ambiente virtual ativo
- [ ] `.env` preenchido com tokens validos
- [ ] Bot em execucao com `python main.py`
- [ ] Testes de texto, audio e imagem confirmando funcionamento
- [ ] Cotacoes retornando dados da AwesomeAPI
- [ ] README suficientemente claro para apresentar o projeto
