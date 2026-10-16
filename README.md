# Smart House Scale — integração HACS descontinuada

Este repositório foi descontinuado na versão 0.5.0.

O projeto deixou de manter um componente customizado/HACS. A instalação oficial
agora é somente o App **Smart House Scale**:

https://github.com/aoliveira07/smart-house-scale

O App escuta uma entidade de peso publicada pelo Home Assistant. A integração
nativa do Home Assistant continua responsável pelo Bluetooth e pela
descriptografia Xiaomi; não instale este repositório em novas casas.

Para atualizar uma instalação antiga:

1. atualize o App Smart House Scale para `0.5.0` ou posterior;
2. configure, na aba **Configuração**, a entidade de peso do Home Assistant;
3. confirme uma pesagem e a fila antes de remover a integração antiga;
4. remova **Smart House Scale** em HACS e exclua a entrada antiga em
   **Configurações → Dispositivos e serviços**, se ela ainda aparecer.

O histórico central no PostgreSQL não é removido por essa desinstalação.

License: MIT.
