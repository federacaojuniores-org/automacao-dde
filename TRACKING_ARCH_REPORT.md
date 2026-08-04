# Relatório de Arquitetura — Planilha de Tracking da Rede de Empresas Juniores

Documento de contexto sobre a planilha `00 - TRACKING [DDE 26]` (Google Sheets, ID `163X5ADTJkHXK4INVs4KPdAXveUXhz0sYEoDGIdHWdOM`) e sua cópia paralela para 2025 (`TRACKING [DDE 2025]`, ID `1AlAz1rdY_7UE6IEViEV0TBZyiVO0eL1N0kgr8mgwJZo`).

Esta planilha é o sistema central de acompanhamento de desempenho da rede nacional de Empresas Juniores (EJs), organizada em 27 federações regionais. Uma dessas federações se chama "Juniores" e é a única com rastreamento completo e granular.

---

## 1. Visão Geral

A planilha tem duas funções centrais:
1. **Prêmio Dia Júnior (Prêmio DJ)**: ranking/pontuação composta que avalia as EJs da federação Juniores em faturamento, evolução de cluster, colaboração e CSAT.
2. **Dashboard de Rede**: painel comparativo entre as 27 federações (faturamento, ritmo de meta, risco de concentração, evolução de cluster), com drill-down para a federação Juniores.

**Assimetria Estrutural:** A federação Juniores tem rastreamento completo, individual, por EJ e por contrato. As outras 26 federações só têm o resumo mensal agregado por federação.

---

## 2. Arquitetura de Arquivos

| Arquivo | ID | Papel |
|---|---|---|
| `00 - TRACKING [DDE 26]` | `163X5ADTJkHXK4INVs4KPdAXveUXhz0sYEoDGIdHWdOM` | Arquivo "master" corrente, ciclo 2026. |
| `TRACKING [DDE 2025]` | `1AlAz1rdY_7UE6IEViEV0TBZyiVO0eL1N0kgr8mgwJZo` | Cópia estrutural para o ciclo 2025. |

---

## 3. Arquitetura de Abas (Arquivo Master 2026)

| Aba | Papel | Escopo de Dado |
|---|---|---|
| `[REDE] Base` | Tabela `Rede_Base`: 1 linha por federação × mês (27×12 = 324 linhas). | Todas as 27 federações |
| `[REDE] Dashboard` | Painel visual: seletor de federação + data de referência. | Detalhe rico para a selecionada; Benchmark cobre as 27 |
| `Prêmio DJ` | Ranking do Prêmio Dia Júnior. | Só federação Juniores |
| `Farol de Cluster [G3]` | Classificação de cluster por EJ. | Só 5 das 27 federações cadastradas |
| `Painel de Análise [G3]` | Tabela `Painel_Analise`: painel detalhado por EJ. | Só federação Juniores |
| `[EMPRESAS JUNIORES] Geral v2.0` | Tabela `Empresas_Juniores`: 1 linha por EJ. ~1480 linhas. | Todas as 27 federações |
| `[MONITORAMENTO] Geral v2.0` | Tabela `Contratos`: 1 linha por contrato. | Só federação Juniores |
| `[MONITORAMENTO] Acumulado v2.0` | Tabela `Acumulado_Mensal`: 1 linha por EJ × mês. ~10.360 linhas. | Todas as 27 federações |

---

## 4. Tabelas Nomeadas Principais

### 4.1 `Empresas_Juniores` (aba `[EMPRESAS JUNIORES] Geral v2.0`)
Snapshot agregado por EJ. Colunas-chave: `ID`, `EMPRESA_JUNIOR`, `FEDERACAO`, `CLUSTER_2026`, `META_DE_REVENUE`, `FATURAMENTO`, `TRACKING_CSAT`, `CSAT_PARCIAL`.

### 4.2 `Contratos` (aba `[MONITORAMENTO] Geral v2.0`)
1 linha por contrato (só Juniores). Colunas-chave: `ID`, `EMPRESA_JUNIOR`, `FEDERACAO`, `DATA_E_HORA_AUDITORIA`, `FATURAMENTO`, `ACAO_COLABORATIVA`, `TIPOS_DE_PARTICIPACAO`, `CSAT`, `NPS`.

### 4.3 `Acumulado_Mensal` (aba `[MONITORAMENTO] Acumulado v2.0`)
1 linha por EJ × mês. Colunas-chave: `ID`, `EMPRESA_JUNIOR`, `FEDERACAO`, `CLUSTER_2026`, `MES`, `CONTRATOS`, `FATURAMENTO`, `FATURAMENTO_ACUMULADO`, `META_DE_REVENUE`.

### 4.4 `Rede_Base` (aba `[REDE] Base`)
1 linha por federação × mês. Colunas: `Federacao`, `Mes`, `EJs`, `Fat_Mes`, `Fat_Acum`, `Meta_Ano`, `Contratos_Mes`, etc.

---

## 5. Regras de Negócio e Decisões de Design Confirmadas

### 5.1 Referências de Tabela, Não de Intervalo de Células
Use sempre `TableName[Coluna]` em vez de `'Aba'!$A:$A` nas fórmulas. Nunca use `VLOOKUP` por índice numérico; prefira `XLOOKUP`.

### 5.2 Base de Data = Auditoria, Não Assinatura
Faturamento corrente deve usar `Contratos[DATA_E_HORA_AUDITORIA]`. Como é datetime, o filtro de "até a data" deve ser `"<"&(data+1)` para evitar descartar auditorias feitas no próprio dia.
*Exceção histórica:* O painel de 2025 mantém `DATA_DE_ASSINATURA` intencionalmente.

### 5.3 Terceirização Não Conta como Faturamento Colaborativo
`Contratos[TIPOS_DE_PARTICIPACAO] = "Terceirização"` é excluído de faturamento/ações colaborativas.

### 5.4 Normalização de CSAT
`Empresas_Juniores[CSAT_PARCIAL]` vem como `0` quando a coleta é menor que 80%. Para agregações, trate `0` como valor neutro `3,5` antes de calcular a média.

### 5.5 EJs Zeradas é Métrica de Ano, Não de Mês
"EJs zeradas no ano" mede quem nunca faturou nada no ano até a data de referência (usa `FATURAMENTO_ACUMULADO`).

### 5.6 Mediana e Média por EJ Excluem Zeradas
Ignoram EJs com faturamento zero para não distorcer as métricas.

---

## 6. Problemas Conhecidos e Correções Históricas

### 6.1 `Farol de Cluster [G3]` Incompleto
Apenas Juniores, Concentro, FEJEA, FEJERS e PB júnior têm dados. O `FAROL` só funciona para Juniores devido a tabelas nomeadas corrompidas das outras federações. Use `SITUAÇÃO ATUAL` para cálculos de cluster cruzados.

### 6.2 Fórmula de "Saldo de Evolução" Corrigida (Dashboard)
A fórmula pondera a diferença bruta `(SOBE - CAI)` pelo peso do cluster, sem normalizar pelo tamanho do cluster antes:
`=SEERRO(((D42-F42)*3+(D43-F43)*2,5+(D44-F44)*1,5+(D45-F45)*1,5+(D46-F46)*1,5)/10;0)`

### 6.3 Bug "EJs que fazem 80%" Corrigido
Adicionado `Acumulado_Mensal[FATURAMENTO_ACUMULADO]<>""` no `FILTER` para excluir células em branco que eram somadas indevidamente como se fossem menores que 80%.

### 6.4 Correção Histórica em `Rede_Base 2025`
Fórmulas corrompidas que usavam colunas erradas (como `MES` apontando para `DATA_DE_COLETA`) foram corrigidas em todas as 324 linhas.

---

## 7. Recomendações para Edições Futuras
1. **Nunca assumir** que uma fórmula funciona igual para todas as federações (só Juniores tem dados granulares completos).
2. Ao duplicar a planilha para um novo ano, audite as fórmulas de `Rede_Base` contra os novos nomes das tabelas de origem.
3. Não use referências numéricas fixas ou fórmulas que dependam de posições estáticas de colunas se puder evitar.
