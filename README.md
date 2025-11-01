# Bot Telegram + OpenAI

![Bot waving friendly](https://media.giphy.com/media/xT0xeJpnrWC4XWblEk/giphy.gif)

Assistente virtual multimodal que junta Telegram, OpenAI e dados em tempo real em uma experiencia dinamica. Pense nele como um bot-animador: entende texto, audio, imagem e responde com contexto vivo e boa educacao.

## Visao Geral Cinematica
![Movie timeline animation](https://media.giphy.com/media/3oKIPtjElfqwMOTbH2/giphy.gif)

```
main.py  -> liga o BotApp e inicia o polling
bot/app.py -> core: buffer, midias, fluxos e chamadas OpenAI
bot/telegram_client.py -> integra com a API do Telegram (updates, menus, arquivos)
bot/openai_client.py -> conversa com a OpenAI e transcreve audios
bot/config.py -> carrega variaveis (.env) e valida configuracao
```

### Fluxo Cena a Cena
1. Usuario envia texto, audio ou imagem no Telegram.
2. `BotApp.run()` captura o update via `getUpdates` (long polling).
3. `ChatState` guarda historico e monta um buffer com as partes recebidas.
4. `_build_realtime_context` detecta pedidos de cotacao e consulta a AwesomeAPI.
5. `OpenAIClient.generate_reply` monta a resposta final com historico + contexto recente.
6. `TelegramClient.sendMessage` entrega a mensagem na thread correta e o ciclo continua.

![Loop animation](https://media.giphy.com/media/l0HlAvv7T8EMbG7Rm/giphy.gif)

## Buffer em Slow Motion
```
tempo   evento                          efeito
0.0s    usuario: "oi bot!"              -> vira texto no pending_parts
0.8s    usuario: audio explicando      -> baixa, transcreve, adiciona "[Audio do usuario]"
1.5s    usuario: imagem (print)        -> baixa, converte para data:image/... e coloca no prompt
2.6s    pausa maior que RESPONSE_BUFFER_SECONDS
        _reply_with_buffer consolida tudo, inclui contexto de cotacoes e chama a OpenAI
```
Esse mini delay gera respostas completas, poucas chamadas de IA e conversas naturais (sem spam de respostas picadas).

## Multimodal Showroom
![Multimodal animation](https://media.giphy.com/media/xT39CVZFTx9X9vB5qM/giphy.gif)

- **Audio**: `_process_voice_message` baixa o arquivo, detecta MIME, transcreve com `OpenAIClient.transcribe_audio` e injeta o texto no prompt.
- **Imagem**: `_queue_image_from_file` baixa, converte para Base64 e manda para o modelo multimodal com a legenda ou um prompt padrao.
- **Texto**: entra direto no buffer; atalhos como "Verificar cotacoes" saltam direto para a resposta pronta.

## Painel de Comandos
```
| comando / atalho             | acao                                                                 |
|------------------------------|----------------------------------------------------------------------|
| /start                       | Mostra boas-vindas + teclado principal                              |
| /help ou "Ajuda"             | Guia rapido com tudo que o bot faz                                  |
| /cotacoes                    | Consulta USD, EUR e GBP vs BRL via AwesomeAPI                       |
| /reset ou "Resetar conversa" | Limpa historico do chat e recomeca                                  |
| /sobre                       | Bastidores do projeto                                               |
| "Conversar com IA"           | Confirma que o bot esta ouvindo                                     |
| "Verificar cotacoes"         | Consulta de moedas sem precisar digitar comando                     |
```

## Setup Turbo
![Rocket launch animation](https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Preencha `.env`:
- `TELEGRAM_BOT_TOKEN` (pego com o BotFather)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (padrao `gpt-4o-mini`)
- `OPENAI_TRANSCRIPTION_MODEL` (padrao `gpt-4o-mini-transcribe`)
- `RESPONSE_BUFFER_SECONDS` (ex.: `3` para agrupar mensagem em ~3 segundos)

> `.env` ja esta listado no `.gitignore`. Nunca envie suas chaves para o repositorio.

Execute:
```
python main.py
```
Deixe rodando e fale com o bot no Telegram. Logs em nivel INFO mostram cada etapa (updates, chamadas, erros externos).

## Bastidores (Blueprint)
```
bot/
  app.py            <- loop principal, buffer, midias, cotacoes, OpenAI
  config.py         <- variaveis de ambiente e validacao
  openai_client.py  <- Chat Completions e Whisper
  telegram_client.py<- requests com retry, menus e download de arquivos
main.py             <- ponto de entrada
requirements.txt    <- dependencias
.env.example        <- modelo de configuracao
```

## Hints de Customizacao
- Ajuste o `SYSTEM_PROMPT` se quiser um bot mais tecnico, informal ou corporativo.
- Modifique `DEFAULT_CURRENCY_CODES` para trocar as moedas de destaque.
- Escreva novos atalhos alterando `MENU_KEYBOARD`.
- Acrescente outros blocos de contexto em `_build_realtime_context` para integrar novas APIs (clima, noticias, status interno...).

## Checklist Final
- [ ] Dependencias instaladas no ambiente virtual
- [ ] `.env` configurado com tokens validos
- [ ] `python main.py` em execucao sem erros
- [ ] Testes com texto, audio e imagem realizados
- [ ] Cotacoes retornando dados da AwesomeAPI
- [ ] README pronto para apresentar o projeto
