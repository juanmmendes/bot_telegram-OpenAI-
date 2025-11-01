# Bot Telegram + OpenAI

```
 ______     _         _______      _                       
|  ____|   | |       |__   __|    | |                      
| |__   ___| |_ _   _ _| |  _ __ | |__   ___  _ __   ___  
|  __| / __| __| | | | | | | '_ \| '_ \ / _ \| '_ \ / _ \ 
| |____\__ \ |_| |_| | | | | | | | | | | (_) | | | |  __/ 
|______|___/\__|\__, |_| |_|_| |_|_| |_|\___/|_| |_|\___| 
                 __/ |                                    
                |___/                                     
```

Seja bem vindo ao atendente virtual que combina Telegram + OpenAI de forma intuitiva, animada e pronta para portfolio ou trabalhos academicos.

## Mapa rapido
- `main.py` liga o bot rodando `BotApp.run()` em modo polling.
- `bot/app.py` cuida do fluxo inteiro, buffer inteligente, midias e conversa com a OpenAI.
- `bot/telegram_client.py` lida com a API do Telegram (getUpdates, sendMessage, download de arquivos).
- `bot/openai_client.py` encapsula Chat Completions e transcricao de audio.
- `bot/config.py` busca variaveis de ambiente e valida configuracao.

## Tour animado: do ping ao pong
```
[00s] usuario envia texto/audio/imagem -> Telegram
[01s] BotApp pega a atualizacao via getUpdates
[02s] ChatState guarda historico, agrupa mensagens no buffer
[03s] _build_realtime_context detecta pedidos de cotacao
[04s] Dados frescos da AwesomeAPI entram no prompt
[05s] OpenAI gera resposta completa
[06s] Telegram recebe a mensagem final com thread correta
```

## Superpoderes em destaque
- Conversa humana orientada pelo `SYSTEM_PROMPT`: respostas empaticas, claras e em portugues.
- Historico por chat mantido em memoria com corte automatico para deixar o contexto leve.
- Menu intuitivo com botoes fixos (Conversar com IA, Verificar cotacoes, Ajuda, Resetar conversa).
- Comandos secos `/start`, `/help`, `/cotacoes`, `/reset`, `/sobre` prontos para o usuario.
- Tratamento resiliente de erros externos; mensagens amigaveis quando algum servico falha.

## Buffer em movimento
```
tempo  mensagem                                  acao
0.0s   "oi, tudo bem?"                            -> entra no pending_parts
1.1s   audio (voz explicando duvida)              -> vira texto "[Audio do usuario] ..."
1.8s   imagem (print da duvida)                   -> convertida para data:image/... e anexada
2.6s   nenhum novo update                         -> _reply_with_buffer dispara
      prompt final = texto + audio + imagem + contexto de cotacoes
```
Resultado: um unico pedido para a OpenAI, respostas coerentes e menor custo de tokens.

## Show multimodal
- **Audio**: `_process_voice_message` baixa o arquivo, detecta MIME, transcreve via `OpenAIClient.transcribe_audio` e encaixa o texto no prompt.
- **Imagem**: `_queue_image_from_file` baixa, converte para Base64, tenta adivinhar o MIME (`_guess_image_mime`) e manda para o modelo multimodal com legenda ou prompt padrao.
- **Texto**: entra direto no buffer; atalhos como "Verificar cotacoes" pulam para a resposta imediata.

## Painel de comandos
```
| comando / atalho     | acao                                                                 |
|----------------------|----------------------------------------------------------------------|
| /start               | Mensagem de boas-vindas + menu inicial                               |
| /help ou "Ajuda"     | Guia rapido de uso                                                   |
| /cotacoes            | Consulta USD, EUR e GBP vs BRL em tempo real                         |
| /reset ou "Resetar conversa" | Limpa historico daquele chat                                 |
| /sobre               | Resumo do projeto e possibilidades                                  |
| "Conversar com IA"   | Confirma que o assistente esta pronto para ouvir                     |
| "Verificar cotacoes" | Dispara consulta de moedas mesmo sem digitar comando                 |
```

## Inicio rapido
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Depois edite `.env`:
- `TELEGRAM_BOT_TOKEN` (BotFather)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (padrao `gpt-4o-mini`)
- `OPENAI_TRANSCRIPTION_MODEL` (padrao `gpt-4o-mini-transcribe`)
- `RESPONSE_BUFFER_SECONDS` (ex.: `3` para agrupar mensagens por ~3 segundos)

> `.env` ja esta no `.gitignore`. Mantenha suas chaves seguras.

Para rodar:
```
python main.py
```
Mantenha o terminal aberto e converse com o bot pelo Telegram.

## Estrutura visual do projeto
```
bot/
  app.py               <- loop principal, buffer, midias, cotacoes, chamadas OpenAI
  config.py            <- carrega variaveis de ambiente e valida
  openai_client.py     <- Chat Completions + transcricao de audio
  telegram_client.py   <- cliente HTTP com retries e helpers de teclado
main.py                <- ponto de entrada para iniciar o bot
requirements.txt       <- dependencias
.env.example           <- modelo de configuracao
```

## Modo dev e personalizacao
- Ajuste o `SYSTEM_PROMPT` em `bot/app.py` para trocar o tom (mais tecnico, informal, corporativo).
- Mude `DEFAULT_CURRENCY_CODES` para destacar outras moedas ou cripto.
- Edite `MENU_KEYBOARD` para criar atalhos proprios para seu projeto ou disciplina.
- Novas integracoes? Acrescente blocos em `_build_realtime_context` e injete dados extras no prompt.

## Checklist final
- [ ] Dependencias instaladas no ambiente virtual
- [ ] `.env` com tokens do Telegram e da OpenAI configurados
- [ ] Bot rodando com `python main.py`
- [ ] Teste com texto, audio e imagem realizado com sucesso
- [ ] Logs monitorados para validar consultas de cotacao e chamadas da OpenAI
- [ ] README pronto para apresentar o projeto para colegas ou avaliadores
