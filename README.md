# Bot Telegram + OpenAI

Um atendente virtual completo que recebe texto, audio ou imagem no Telegram, conversa em portugues e ainda consulta cotacoes em tempo real para enriquecer suas respostas.

## Por que este bot chama atencao
- Conversa natural: mantem historico individual por chat e responde com tom humano definido no `SYSTEM_PROMPT` de `bot/app.py`.
- Multimodal na pratica: transcreve audios automaticamente e analisa imagens enviadas pelo usuario no mesmo fluxo de conversa.
- Contexto vivo: detecta pedidos de cotacao na mensagem, busca valores atualizados via AwesomeAPI e injeta esse contexto antes de falar com a IA.
- Buffer inteligente: agrupa mensagens consecutivas por alguns segundos para evitar respostas picadas e enviar um unico pedido coerente ao modelo.
- Menu intuitivo: comandos rapidos, teclado personalizado e mensagens de boas-vindas pensadas para orientar novos usuarios.

## Como o bot funciona de ponta a ponta
1. **Recebe atualizacoes do Telegram**: `BotApp.run()` usa long polling (`getUpdates`) para buscar mensagens novas e remove qualquer webhook restante antes de iniciar.
2. **Organiza cada chat**: um `ChatState` por usuario guarda historico, controla o buffer (`pending_parts`) e registra o `last_message_id` para responder sempre em thread.
3. **Classifica o que chegou**: comandos (`/start`, `/help`, ...) sao tratados imediatamente; atalhos do menu como "Verificar cotacoes" acionam as acoes equivalentes.
4. **Processa midias**:
   - Audios/voz sao baixados, convertidos para bytes e enviados a `OpenAIClient.transcribe_audio`, que devolve texto pronto para o prompt.
   - Fotos e documentos de imagem viram `data:` URLs em Base64 com a legenda opcional como prompt adicional.
5. **Enfileira no buffer**: todo conteudo textual ou multimodal cai em `pending_parts`. O bot espera `RESPONSE_BUFFER_SECONDS` segundos sem novas mensagens antes de elaborar a resposta. Se outra mensagem chegar nesse intervalo, ela e agrupada.
6. **Enriquece com dados externos**: `_build_realtime_context` analisa o texto, identifica moedas (USD, EUR, GBP, JPY, ARS, BTC...) e consulta a AwesomeAPI. Se a resposta chegar, o contexto e anexado ao prompt com o bloco `[Contexto em tempo real]`.
7. **Conversa com a OpenAI**: `OpenAIClient.generate_reply` recebe o historico (mensagem de sistema + conversas anteriores) e retorna a resposta final. Enquanto aguarda a IA, o bot envia a acao "typing" para o Telegram.
8. **Entrega e registra**: a resposta da IA e enviada via `sendMessage`, guardada no historico do `ChatState` e o ciclo recomeca. Erros externos geram mensagens amigaveis sugerindo tentar novamente.

## Buffer inteligente em detalhes
- Valor padrao: 2.5 segundos (`RESPONSE_BUFFER_SECONDS`), ajustavel via `.env`.
- `ChatState.should_flush` verifica o tempo desde a ultima parte recebida. Ao ultrapassar o intervalo, `_reply_with_buffer` consolida as mensagens, anexa contexto e chama a IA.
- Beneficios: conversas mais naturais, consumo otimizado da API da OpenAI e nenhuma resposta fragmentada enquanto o usuario ainda digita.

## Suporte a audio e imagem
- **Audio**: qualquer mensagem de voz ou audio anexo e baixado pela API do Telegram, transcrito e colocado no prompt com a etiqueta `[Audio do usuario]`.
- **Imagem**: imagens sao analisadas pelo modelo multimodal com o texto/legenda que voce enviar. Se nao houver legenda, o bot usa um prompt generico pedindo uma analise visual.

## Requisitos
- Python 3.10 ou superior.
- Conta na OpenAI com chave de API ativa.
- Dependencias listadas em `requirements.txt`.

### Configuracao rapida
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

Crie um arquivo `.env` a partir do modelo:
```bash
copy .env.example .env
```
Preencha os campos:
- `TELEGRAM_BOT_TOKEN`: token fornecido pelo BotFather.
- `OPENAI_API_KEY`: sua chave privada da OpenAI.
- `OPENAI_MODEL`: modelo de chat (padrao `gpt-4o-mini`).
- `OPENAI_TRANSCRIPTION_MODEL`: modelo de transcricao (padrao `gpt-4o-mini-transcribe`).
- `RESPONSE_BUFFER_SECONDS`: segundos que o bot espera antes de responder (ex.: `3`).

> O `.gitignore` ja ignora `.env`. Jamais commite suas chaves.

## Executando localmente
```bash
python main.py
```

- O bot usa long polling; deixe o processo rodando e interaja com ele no Telegram.
- Logs em nivel INFO indicam inicio, comandos recebidos, falhas externas e outras acoes importantes.

## Comandos e atalhos inclusos
- `/start`: mensagem de boas-vindas e exibe o menu.
- `/help`: explica rapidamente como usar o bot.
- `/cotacoes`: consulta USD, EUR e GBP contra BRL em tempo real.
- `/reset`: limpa o historico daquele chat e recomeca do zero.
- `/sobre`: apresenta o projeto e seu objetivo.
- Menu com botoes (`MENU_KEYBOARD`): Conversar com IA, Verificar cotacoes, Ajuda, Resetar conversa.

## Estrutura do projeto
```
bot/
  app.py            # Loop principal, buffer, processamento de midias e integracao OpenAI
  config.py         # Carrega variaveis de ambiente e valida configuracao
  openai_client.py  # Wrapper para chat completions e transcricao de audio
  telegram_client.py# Cliente HTTP com retries e envio de mensagens/atalhos
main.py             # Ponto de entrada que instancia BotApp e inicia o polling
requirements.txt    # Dependencias
.env.example        # Modelo de configuracao
```

## Personalizacoes sugeridas
- Ajuste o `SYSTEM_PROMPT` para mudar a personalidade do bot (mais tecnico, divertido, corporativo...).
- Altere `DEFAULT_CURRENCY_CODES` para decidir quais moedas aparecem no atalho `/cotacoes`.
- Adapte o teclado em `MENU_KEYBOARD` com opcoes especificas da sua aplicacao.
- Acrescente novos blocos em `_build_realtime_context` para consultar outras APIs e enriquecer o prompt.

## Proximos passos possiveis
- Persistir o historico em Redis ou banco SQL para manter contexto entre reinicios.
- Criar testes automatizados para `openai_client.py` e `telegram_client.py`, garantindo resiliencia a quedas de rede.
- Integrar observabilidade (Sentry, Prometheus, logs estruturados) para acompanhar uso em producao.
