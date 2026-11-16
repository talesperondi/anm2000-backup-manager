# Contribuindo

Obrigado pelo interesse. Este projeto nasceu de uma necessidade real de operação
e ganha muito com relatos de outras versões do cliente ANM2000.

## Antes de abrir uma issue

- Verifique se já existe uma issue semelhante.
- Rode `python main.py status` e `python main.py run --dry-run` e inclua a saída
  (remova nomes de OLTs, IPs e caminhos que identifiquem sua empresa).
- Informe a versão do programa, do Windows e do cliente ANM2000.

## Enviando código

1. Faça um fork e crie uma branch descritiva (`fix/export-timeout`,
   `feat/relatorio-semanal`).
2. Instale as dependências:
   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt -r requirements-build.txt
   ```
3. Rode os testes antes e depois da mudança:
   ```powershell
   python -m unittest discover -s tests
   ```
4. Mantenha o estilo do código existente (português nos textos de interface,
   docstrings curtas, sem dependências novas sem necessidade).
5. Abra o pull request explicando **o problema** e **como foi validado**. Se a
   mudança afetar a automação da interface, descreva o teste feito com o cliente
   ANM2000 real (versão e resultado).

## Áreas onde ajuda é bem-vinda

- Suporte a outras versões/idiomas do cliente ANM2000 (os textos de confirmação
  mudam entre versões).
- Exportação de relatório consolidado (CSV/HTML) do histórico.
- Northbound TL1 como alternativa à automação de interface.
- Testes com topologias maiores (dezenas de OLTs).
- Tradução da interface e da documentação.

## Conduta

Seja direto e respeitoso. Issues com dados reais de clientes (IPs, credenciais,
nomes de OLTs) serão editadas ou fechadas.
