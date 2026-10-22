# Automação DDE — Sincronização de Tracking 2026

Este repositório contém a automação completa de download e sincronização em segundo plano para a planilha de Tracking 2026 de faturamento e amadurecimento organizacional da Juniores.

A automação elimina todo o trabalho manual diário de login, geração de relatórios, download, limpeza de dados e atualização de planilhas de forma segura e resiliente.

---

Como Funciona (Arquitetura)

1. **Fase 1: Download Invisível (Playwright):** Um navegador *headless* faz login no Portal da Brasil Júnior, navega até a aba de relatórios da federação, aciona a atualização de 3 relatórios estratégicos, monitora até que estejam prontos e realiza o download de forma estruturada.
2. **Fase 2: Auto-Alinhamento:** O script lê os arquivos Excel locais e a sua planilha de Tracking, mapeia os cabeçalhos por nome (não por posição) e atualiza apenas as células de dados correspondentes. Se a BJ mudar o layout ou adicionar novas colunas, elas serão colocadas no final automaticamente **sem quebrar nenhuma fórmula**

---

## Estrutura de Arquivos

*   `daily_sync.py`: Script orquestrador central (Phase 1 -> Phase 2), às 05:30 e 17:30.
*   `sync_planilhas_ejs.py`: Copia indicadores e premiações para `_dados` e cola diretamente as linhas dos dois Monitoramentos.
*   `campos_dados_ej.json`: Cópia de recuperação do catálogo; a fonte oficial é a tabela `Campos_Dados_EJ` na matriz.
*   `config_planilhas_ejs.json`: Configuração operacional: modelo, pasta, aba de acessos e título da premiação vigente.
*   `test_exact_downloads.py`: Script do Playwright para navegação e download do portal BJ.
*   `update_sheets.py`: Script de leitura de Excel e escrita auto-alinhada no Google Sheets via API.
*   `validate_sheets.py`: Script de diagnóstico que lê os indicadores do Dashboard para validar a consistência das fórmulas após cada atualização.
*   `TRACKING_ARCH_REPORT.md`: Relatório completo detalhando a arquitetura de dados, fórmulas corrigidas, conceitos de negócio e gotchas da planilha de Tracking.
*   `.gitignore`: Filtro de segurança que impede que suas senhas ou chaves de API cheguem ao GitHub.
*   `.env.example`: Modelo de configuração para variáveis de ambiente locais.

---

## Configuração e Instalação Local

### 1. Pré-requisitos
*   Python 3.11+
*   `uv` instalado
*   Chave privada da Conta de Serviço do Google (arquivo `.json`)
*   Credenciais do Portal BJ (precisa ser as do diretor de DDE)

### 2. Instalação do Ambiente
Navegue até a pasta do projeto e execute os comandos:

```bash
# Criar o ambiente virtual
uv venv

# Instalar as dependências necessárias
.venv/bin/pip install -r requirements.txt

# Instalar os binários do navegador do Playwright
.venv/bin/playwright install chromium
```

### 3. Configuração de Variáveis de Ambiente
1. Copie o arquivo `.env.example` para `.env`:
   ```bash
   cp .env.example .env
   ```
2. Abra o arquivo `.env` no seu editor e preencha com suas credenciais do portal, ID da planilha master e o nome do seu arquivo `.json` de chave do Google.

---

## Como Executar

### Execução Manual:
Para atualizar a planilha a qualquer momento com os dados em tempo real mais recentes do portal, execute:
```bash
.venv/bin/python daily_sync.py
```

### Execução Agendada (GitHub Actions):
A automação está configurada no **GitHub Actions** para rodar **todos os dias às 08:00 AM (horário de Brasília)** (`0 11 * * *` em UTC). 

Como roda inteiramente na nuvem do GitHub, a sincronização acontecerá de forma 100% autônoma, mesmo se o seu computador estiver desligado ou sem internet!

Para acompanhar a execução, basta abrir a aba **Actions** do seu repositório no GitHub. Lá você verá o histórico de execuções diárias e poderá rodar a automação manualmente a qualquer momento clicando no botão **Run workflow**.


---

## Planilhas individuais das EJs (Fase 3)

Cada EJ tem uma cópia do modelo "Tracking da EJ". O `sync_planilhas_ejs.py` roda automaticamente depois da atualização bem-sucedida da mestre. Indicadores e premiações são gravados na aba oculta `_dados`; Visão Geral, Premiação e Simulador consultam essa base por fórmula. Monitoramento Geral e Monitoramento Acumulado recebem diretamente as linhas filtradas do Portal.

**Aba de controle na mestre** (`[CONTROLE] Tracking EJs`): contém as tabelas nativas `Planilhas_EJs`, com uma linha por EJ, e `Campos_Dados_EJ`, que controla quais campos adicionais entram em `_dados`. O código localiza ambas pelo nome da tabela, então a posição delas na aba não interfere no fluxo.

**Criar a planilha de uma EJ nova:** faça uma cópia do modelo no Drive, compartilhe com a conta de serviço como editora e cole o ID na aba de acessos. A conta de serviço não tem cota no Drive, então não consegue criar arquivos. O compartilhamento com a presidência é feito por uma pessoa e o script não mexe nele.

**Adicionar ou retirar dados:** edite a tabela `Campos_Dados_EJ` na matriz. Cada linha informa a tabela nativa de origem, se a EJ será localizada por `ID` ou `EJ`, o cabeçalho da coluna, a chave publicada em `_dados` e se o valor deve ser bruto ou formatado. Desmarcar `ATIVO` remove o campo na sincronização seguinte. Antes de escrever, o fluxo valida tabelas, colunas, chaves duplicadas e a existência de cada EJ.

**Trocar a premiação:** adicione os campos da nova tabela em `Campos_Dados_EJ` e altere a aba Premiação no modelo para consultar as novas chaves com `XLOOKUP`. Os rankings atuais estão desativados para não serem publicados às EJs.

### Controles de execução — mapeados, não implementados

Uma futura área de botões pode disparar os workflows `Daily Tracking Synchronization`, `Planilhas das EJs`, `Aplicar modelo às EJs` e `Validar planilhas das EJs`. Para execução imediata, o caminho recomendado é um Web App privado da organização chamando `workflow_dispatch` no GitHub, sem token armazenado na planilha. A API pública do cron-job.org permite consultar, criar, alterar, ativar e desativar jobs e ler o histórico, mas não documenta um endpoint para executar um job imediatamente; por isso ela não é a melhor base para esses botões.

```bash
python sync_planilhas_ejs.py --dry-run          # lê a mestre e mostra o que seria gravado
python sync_planilhas_ejs.py --ej 90            # só uma EJ
python sync_planilhas_ejs.py                    # todas as EJs da aba de acessos
```

Para rodar fora do horário: aba Actions, workflow "Planilhas das EJs", botão Run workflow (dá para informar os IDs das EJs).
