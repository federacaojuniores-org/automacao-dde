"""
Distribui os dados da planilha mestre (00 - TRACKING [DDE 26]) para as planilhas individuais das EJs.

Cada EJ tem uma cópia do modelo "Tracking da EJ". Este script só grava valores, sem fórmulas
apontando para a mestre, em quatro lugares de cada cópia:
  _dados!A2:B              pares "Fonte | campo" -> valor, lidos pela Visão Geral e pelo Simulador
  Premiação!B13:H          critérios da premiação vigente (config_planilhas_ejs.json)
  Monitoramento Geral!B8   contratos de 2026 da EJ
  Monitoramento Acumulado!B8  linhas mês a mês da EJ

A lista de EJs vem da aba de acessos da mestre. As colunas são achadas pelo cabeçalho (ID, EJ,
ID da planilha, Última sincronização, Status), então dá para mudar a ordem ou incluir outras.
EJ sem ID da planilha ganha uma cópia do modelo na pasta do drive compartilhado (config: modelo_id e
pasta_planilhas), e o ID da cópia é anotado na aba de acessos. A conta de serviço precisa ser gerente de
conteúdo do drive compartilhado. O script não mexe em compartilhamento.

Uso:
  python sync_planilhas_ejs.py                 # todas as EJs com planilha na aba de acessos
  python sync_planilhas_ejs.py --ej 90 --ej 62 # só algumas
  python sync_planilhas_ejs.py --dry-run       # lê a mestre e mostra o que seria gravado
  python sync_planilhas_ejs.py --snapshot x.json --ej 90 --saida y.json  # teste offline
  python sync_planilhas_ejs.py --copiar-modelo # copia o modelo para a pasta e mostra o ID novo
"""
import argparse
import json
import os
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone

socket.setdefaulttimeout(120)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config_planilhas_ejs.json")
MASTER_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "163X5ADTJkHXK4INVs4KPdAXveUXhz0sYEoDGIdHWdOM")
BRT = timezone(timedelta(hours=-3))
EPOCH = datetime(1899, 12, 30)
PAUSA_ENTRE_EJS = 2.5  # segundos; cada EJ usa 2 chamadas de escrita (limite da API: 60 por minuto)

T_PAINEL = "Painel de Análise [G3]"
T_FAROL = "Farol de Cluster [G3]"
# última linha da área de critérios na aba Premiação do modelo (a nota de rodapé fica duas linhas abaixo)
PREM_FIM = 43
T_CORS = "CORS"
T_GERAL = "[MONITORAMENTO] Geral v2.0"
T_ACUM = "[MONITORAMENTO] Acumulado v2.0"

TABELAS_MESTRE = {
    "painel": "Painel_Analise",
    "farol": "Cluster_JUNIORES",
    "cors": "CORS",
    "cors_2025": "CORS_2025_Ate_Data",
    "geral": "Contratos",
    "acum": "Acumulado_Mensal",
    "premio": "Premio_ENCEJ",
    "acessos": "Planilhas_EJs",
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]

# Colunas das abas de monitoramento da planilha da EJ, na ordem em que aparecem a partir da coluna B.
# Tipos: d data, dt data e hora, m dinheiro, i inteiro, n decimal, p percentual, t/tw texto, mo mês.
# Os rótulos ficam no modelo; aqui só a origem de cada coluna.
COLS_GERAL = [
    ("DATA_DE_ASSINATURA", "d"),  # Assinatura
    ("NOME_DO_CLIENTE", "tw"),  # Cliente
    ("FATURAMENTO", "m"),  # Faturamento
    ("_SOL", "tw"),  # Soluções vendidas
    ("SOLUCOES", "i"),  # Nº de soluções
    ("MES", "i"),  # Mês
    ("ESTA_AUDITADO", "t"),  # Auditado?
    ("STATUS", "t"),  # Status da auditoria
    ("DATA_E_HORA_AUDITORIA", "dt"),  # Auditado em
    ("STATUS_FINALIZACAO", "t"),  # Situação
    ("DATA_DE_CONCLUSÃO_EFETIVA_DO_PROJETO", "d"),  # Data de conclusão
    ("DURAÇÃO_DO_PROJETO_EM_DIAS_ÚTEIS", "i"),  # Duração (dias úteis)
    ("FATURAMENTO_INICIAL", "m"),  # Valor inicial do contrato
    ("HOUVE_ALTERACAO_NO_FATURAMENTO", "t"),  # Valor alterado?
    ("FATURAMENTO_DAS_TERCERIZACOES", "m"),  # Valor terceirizado
    ("LUCRO", "m"),  # Lucro
    ("CUSTO_OPERACIONAL", "m"),  # Custo operacional
    ("DESPESAS", "m"),  # Despesas
    ("CIDADE_DO_CLIENTE", "t"),  # Cidade
    ("ESTADO_DO_CLIENTE", "t"),  # UF
    ("PAIS_DO_CLIENTE", "t"),  # País
    ("MODALIDADE", "t"),  # Porte do cliente
    ("É_MEI_MPE", "t"),  # MEI ou MPE?
    ("ATIVIDADE_ECONÔMICA", "tw"),  # Atividade econômica
    ("COMO_SUA_EJ_CONSEGUIU_O_CONTRATO", "t"),  # Como o contrato veio
    ("ORIGEM", "t"),  # Origem do cliente
    ("ACAO_COLABORATIVA", "t"),  # Conta como colaborativo?
    ("PROJETO_REALIZADO_CONJUNTO_COM_OUTRO_AGENTE", "t"),  # Feito com outro agente?
    ("TIPOS_DE_PARTICIPACAO", "t"),  # Tipo de participação
    ("TIPOS_DE_AGENTES_QUE_PARTICIPARAM", "t"),  # Tipo de agente
    ("AGENTES_QUE_PARTICIPARAM", "tw"),  # Agentes (CNPJ)
    ("N_DE_AGENTES_QUE_PARTICIPARAM", "i"),  # Nº de agentes
    ("O_PROJETO_FOI_INDICAÇÃO_DE_OUTRA_EJ", "t"),  # Indicado por outra EJ?
    ("EJ_QUE_INDICOU", "t"),  # EJ que indicou
    ("CSAT", "n"),  # CSAT
    ("DATA_DE_COLETA_DE_CSAT", "d"),  # Coleta do CSAT
    ("NPS", "i"),  # NPS
    ("DATA_DE_COLETA_DE_NPS", "d"),  # Coleta do NPS
    ("COMENTARIO_NPS", "tw"),  # Comentário do NPS
    ("N_DE_MEMBROS_PARTICIPANTES", "i"),  # Nº de membros
    ("MEMBROS_PARTICIPANTES", "tw"),  # Membros
    ("TEVE_ORIENTAÇÃO", "t"),  # Teve orientação?
    ("TIPO_DE_ORIENTAÇÃO", "t"),  # Tipo de orientação
    ("POTENCIAL_PROJETO_DE_IMPACTO", "t"),  # Projeto de impacto?
    ("BANDEIRA_DO_BRASIL_EMPREENDEDOR", "t"),  # Bandeira Brasil Empreendedor
    ("INDICADOR_FOCO", "tw"),  # Indicador foco
    ("METRIFICACAO_META", "t"),  # Meta do indicador
    ("UNIDADE_DE_MEDIDA", "t"),  # Unidade
    ("ACERTOS", "tw"),  # Acertos
    ("PONTOS_DE_MELHORIA", "tw"),  # Pontos de melhoria
    ("APRENDIZADOS", "tw"),  # Aprendizados
]

COLS_ACUM = [
    ("MES", "mo"),  # Mês
    ("FATURAMENTO", "m"),  # Faturamento do mês
    ("FATURAMENTO_ACUMULADO", "m"),  # Faturamento acumulado
    ("META_DE_REVENUE", "m"),  # Meta anual
    ("PORCENTAGEM_DE_FATURAMENTO_EM_RELACAO_A_META", "p"),  # % da meta
    ("CONTRATOS", "i"),  # Contratos
    ("SOLUCOES", "i"),  # Soluções
    ("CONTRATOS_FINALIZADOS", "i"),  # Contratos finalizados
    ("SOLUCOES_FINALIZADAS", "i"),  # Soluções finalizadas
    ("TEMPO_MEDIO_POR_CONTRATO_DIAS", "n"),  # Tempo médio por contrato (dias)
    ("FATURAMENTO_INICIAL", "m"),  # Valor inicial dos contratos
    ("HOUVE_ALTERACAO_NO_FATURAMENTO", "t"),  # Valor alterado?
    ("LUCRO", "m"),  # Lucro
    ("CUSTO_OPERACIONAL", "m"),  # Custo operacional
    ("DESPESAS", "m"),  # Despesas
    ("FATURAMENTO_COLABORATIVO", "m"),  # Colaborativo do mês
    ("FATURAMENTO_COLABORATIVO_ACUMULADO", "m"),  # Colaborativo acumulado
    ("TAXA_DE_COLABORACAO", "p"),  # Taxa de colaboração
    ("META_DE_COLLABORATIVE_RATE", "p"),  # Meta de colaboração
    ("PORCENTAGEM_DE_TAXA_DE_COLABORACAO_EM_RELACAO_A_META", "p"),  # % da meta de colaboração
    ("NUMERO_DE_CONTRATOS_QUE_REALIZOU_ACAO_COLABORATIVA", "i"),  # Contratos colaborativos
    ("AGENTES_COM_QUEM_REALIZOU_ACAO_COLABORATIVA", "tw"),  # Agentes (CNPJ)
    ("NUMERO_DE_AGENTES_COM_QUEM_REALIZOU_ACAO_COLABORATIVA", "i"),  # Nº de agentes
    ("EJS_PELAS_QUAIS_FOI_INDICADA", "tw"),  # EJs que indicaram a sua
    ("NUMERO_DE_EJS_PELAS_QUAIS_FOI_INDICADA", "i"),  # Nº de EJs que indicaram
    ("NUMERO_DE_CONTRATOS_REALIZADOS_POR_INDICACAO", "i"),  # Contratos por indicação
    ("NUMERO_DE_SOLUCOES_REALIZADOS_POR_INDICACAO", "i"),  # Soluções por indicação
    ("EJS_QUE_INDICOU", "tw"),  # EJs indicadas pela sua
    ("NUMERO_DE_EJS_QUE_INDICOU", "i"),  # Nº de EJs indicadas
    ("NUMERO_DE_CONTRATOS_QUE_INDICOU", "i"),  # Contratos indicados
    ("NUMERO_DE_SOLUCOES_QUE_INDICOU", "i"),  # Soluções indicadas
    ("CSAT", "n"),  # CSAT do mês
    ("CSAT_PARCIAL", "n"),  # CSAT acumulado
    ("META_DE_CSAT", "n"),  # Meta de CSAT
    ("PORCENTAGEM_DE_COLETA_CSAT", "p"),  # % de coleta do CSAT
    ("SOLUCOES_CSAT_PROMOTOR", "i"),  # Soluções com CSAT alto
    ("SOLUCOES_CSAT_NEUTRO", "i"),  # Soluções com CSAT médio
    ("SOLUCOES_CSAT_DETRATOS", "i"),  # Soluções com CSAT baixo
    ("NPS", "n"),  # NPS
    ("CONTRATOS_QUE_FORAM_COLETADOS_NPS", "i"),  # Contratos com NPS
    ("PORCENTAGEM_DE_CONTRATOS_COLETADOS_NPS", "p"),  # % de contratos com NPS
    ("MEMBROS", "i"),  # Membros
    ("NUMERO_DE_MEMBROS_QUE_EXECUTARAM_CONTRATOS_NO_MES", "i"),  # Membros em contratos
    ("PORCENTAGEM_DE_MEMBROS_QUE_EXECUTARAM_CONTRATOS_NO_MES", "p"),  # % em contratos
    ("QUANTIDADE_DE_MEMBROS_ENGAJADOS_COM_MEJ", "i"),  # Engajados com o MEJ
    ("PORCENTAGEM_DE_MEMBROS_ENGAJADOS_COM_MEJ", "p"),  # % engajados
    ("META_DE_MEJ_ENGAGED_MEMBERS", "p"),  # Meta de engajamento
    ("PORCENTAGEM_DE_MEMBROS_ENGAJADOS_COM_MEJ_EM_RELACAO_A_META", "p"),  # % da meta de engajamento
    ("TEMPO_PERMANENCIA_NO_MEJ", "n"),  # Tempo de permanência
    ("META_DE_LENGTH_OF_STAY", "n"),  # Meta de permanência
    ("PORCENTO_MEMBROS_TEMPO_PERMANENCIA_UM_ANO", "p"),  # % com 1 ano ou mais
    ("PORCENTO_MEMBROS_GRUPOS_SUBREPRESENTADOS", "p"),  # % de grupos sub-representados
    ("PROJETOS_DE_IMPACTO", "i"),  # Projetos de impacto
    ("META_DE_IMPACT_PROJECTS", "i"),  # Meta de projetos de impacto
    ("PORCENTAGEM_DE_PROJETOS_DE_IMPACTO_EM_RELACAO_A_META", "p"),  # % da meta de impacto
    ("POLITICAS_DI", "i"),  # Políticas de D&I
    ("META_DE_DI_POLITICS", "i"),  # Meta de D&I
    ("PORCENTAGEM_DE_POLITICAS_DE_DI_EM_RELACAO_A_META", "p"),  # % da meta de D&I
]


# ---------------------------------------------------------------- conversões

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().casefold()


def serial(dt):
    d = dt - EPOCH
    return d.days + d.seconds / 86400


def to_serial(v, com_hora=False):
    """Data da mestre (serial ou texto) -> número de série do Sheets."""
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return float(v) if com_hora else float(int(v))
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", s)
    if m:
        dt = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0) if com_hora else 0, int(m[5] or 0) if com_hora else 0)
        return serial(dt)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})(?: (\d{2}):(\d{2}))?", s)
    if m:
        dt = datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0) if com_hora else 0, int(m[5] or 0) if com_hora else 0)
        return serial(dt)
    return s


def to_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v or "").strip()
    if s in ("", "-"):
        return ""
    t = s.replace("R$", "").replace("%", "").replace(" ", "")
    try:
        return float(t.replace(".", "").replace(",", ".")) if "," in t else float(t)
    except ValueError:
        return s


def txt(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    v = re.sub(r"^(l:|:)\s*", "", str(v if v is not None else "").replace("⇩", "").strip())
    return "" if v == "-" else v


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pad(row, n=250):
    return list(row) + [""] * (n - len(row))


def letra(j):
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def mapear_tabelas(service):
    """Retorna os intervalos atuais das tabelas da mestre, sem depender de linhas fixas."""
    info = service.spreadsheets().get(
        spreadsheetId=MASTER_ID,
        fields="sheets(properties(title),tables(name,range))",
    ).execute()
    encontradas = {}
    for sheet in info.get("sheets", []):
        titulo = sheet["properties"]["title"]
        for table in sheet.get("tables", []):
            encontradas[table["name"]] = (titulo, table["range"])
    faltando = [nome for nome in TABELAS_MESTRE.values() if nome not in encontradas]
    if faltando:
        raise ValueError("Tabelas ausentes na mestre: " + ", ".join(faltando))
    return encontradas


def intervalo_tabela(tabelas, nome):
    titulo, r = tabelas[nome]
    inicio = f"{letra(r.get('startColumnIndex', 0))}{r.get('startRowIndex', 0) + 1}"
    fim = f"{letra(r['endColumnIndex'] - 1)}{r['endRowIndex']}"
    return f"'{titulo.replace(chr(39), chr(39) * 2)}'!{inicio}:{fim}"


def cabecalhos(rows, obrigatorios, origem):
    if not rows:
        raise ValueError(f"{origem}: tabela vazia")
    hdr = [str(x).strip() for x in rows[0]]
    vazios = [i + 1 for i, x in enumerate(hdr) if not x]
    duplicados = sorted({x for x in hdr if x and hdr.count(x) > 1})
    faltando = [x for x in obrigatorios if x not in hdr]
    problemas = []
    if vazios:
        problemas.append("cabeçalho vazio")
    if duplicados:
        problemas.append("cabeçalhos duplicados: " + ", ".join(duplicados))
    if faltando:
        problemas.append("colunas ausentes: " + ", ".join(faltando))
    if problemas:
        raise ValueError(f"{origem}: " + "; ".join(problemas))
    return hdr


def campos_por_id(rows, origem, obrigatorios):
    hdr = cabecalhos(rows, ("ID", *obrigatorios), origem)
    jid = hdr.index("ID")
    cols = [(j, k) for j, k in enumerate(hdr) if k and not k.startswith("Coluna")]
    out = {}
    for raw in rows[1:]:
        row = pad(raw, len(hdr))
        eid = txt(row[jid])
        if eid:
            if eid in out:
                raise ValueError(f"{origem}: ID duplicado {eid}")
            out[eid] = [(f"{origem} | {k}", row[j]) for j, k in cols]
    return hdr, out


def extrair_regua(rows):
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            if str(value).strip().upper().startswith("RÉGUA"):
                for h in range(i + 1, min(i + 4, len(rows))):
                    hdr = pad(rows[h], j + 3)
                    if [norm(x) for x in hdr[j:j + 3]] != ["de", "ate", "cluster"]:
                        continue
                    regua = []
                    for raw in rows[h + 1:]:
                        r = pad(raw, j + 3)
                        m = re.fullmatch(r"C(\d)", txt(r[j + 2]).upper())
                        if not m:
                            if regua:
                                break
                            continue
                        de, ate, n = r[j], r[j + 1], m.group(1)
                        if not isinstance(de, (int, float)):
                            raise ValueError(f"Régua de cluster C{n}: piso não numérico")
                        regua += [(f"Régua | Cluster {n} | Piso", de),
                                  (f"Régua | Cluster {n} | Teto", ate if isinstance(ate, (int, float)) else "")]
                    if len(regua) != 10:
                        raise ValueError(f"Régua de cluster incompleta: {len(regua) // 2} de 5 clusters")
                    return regua
    raise ValueError("Régua de cluster não encontrada no Farol")


# ---------------------------------------------------------------- leitura da mestre

def ler_mestre(service, cfg, tabelas):
    aba_p = cfg["premiacao"]["aba"]
    ranges = [intervalo_tabela(tabelas, TABELAS_MESTRE[k])
              for k in ("painel", "farol", "cors", "cors_2025", "geral", "acum")]
    ranges += [f"'{T_FAROL}'!A1:Z30", f"'{T_PAINEL}'!E1:F1", f"'{T_CORS}'!B2:D2"]
    r = service.spreadsheets().values().batchGet(
        spreadsheetId=MASTER_ID, ranges=ranges, valueRenderOption="UNFORMATTED_VALUE",
        dateTimeRenderOption="SERIAL_NUMBER").execute()["valueRanges"]
    nomes = ["painel", "farol", "cors", "cors_2025", "geral", "acum",
             "farol_aux", "painel_controle", "cors_controle"]
    snap = {n: x.get("values", []) for n, x in zip(nomes, r)}
    p = service.spreadsheets().values().batchGet(
        spreadsheetId=MASTER_ID,
        ranges=[intervalo_tabela(tabelas, TABELAS_MESTRE["premio"]), f"'{aba_p}'!A1:B200"],
        valueRenderOption="FORMATTED_VALUE").execute()["valueRanges"]
    snap["premio"], snap["premio_aux"] = (x.get("values", []) for x in p)
    # nas colunas de texto dos monitoramentos vale o que aparece na mestre (ex.: "100%" e não 1)
    f = service.spreadsheets().values().batchGet(
        spreadsheetId=MASTER_ID, ranges=ranges[4:6], valueRenderOption="FORMATTED_VALUE").execute()["valueRanges"]
    snap["geral_fmt"], snap["acum_fmt"] = (x.get("values", []) for x in f)
    return snap


def ler_acessos(service, cfg, tabelas):
    r = service.spreadsheets().values().get(
        spreadsheetId=MASTER_ID,
        range=intervalo_tabela(tabelas, TABELAS_MESTRE["acessos"]),
        valueRenderOption="UNFORMATTED_VALUE").execute()
    return r.get("values", [])


def mes_numero(v):
    if isinstance(v, (int, float)):
        return int(v)
    n = norm(v)
    for i, m in enumerate(MESES, 1):
        if norm(m) == n:
            return i
    return to_num(v)


def indexar(snap):
    """Organiza a mestre em dicionários por ID de EJ."""
    _, P = campos_por_id(snap["painel"], "Painel", ("EJ", "Cluster", "Farol de Cluster"))
    _, F = campos_por_id(snap["farol"], "Farol", ("EJ", "CLUSTER", "CLUSTER ALMEJADO", "FAROL",
                                                                  "SITUAÇÃO ATUAL", "ÍNDICE PREVISTO", "ÍNDICE ATUAL",
                                                                  "CLUSTER PREVISTO FINAL"))
    _, C26 = campos_por_id(snap["cors"], "CORS 2026", ("EJ", "CORS FINAL"))
    _, C25 = campos_por_id(snap["cors_2025"], "CORS 2025", ("EJ", "CORS FINAL"))
    C = {}
    for fonte in (C26, C25):
        for eid, pares in fonte.items():
            C.setdefault(eid, []).extend(pares)
    regua = extrair_regua(snap["farol_aux"])
    controle_p = pad((snap.get("painel_controle") or [[]])[0], 2)
    controle_c = pad((snap.get("cors_controle") or [[]])[0], 3)
    datas_cors = (controle_c[0], controle_c[2])

    def por_id(tab):
        rows = snap[tab]
        if not rows:
            return [], {}
        rows_f = snap.get(tab + "_fmt") or rows
        if len(rows_f) != len(rows):
            rows_f = rows  # leituras fora de sincronia: usa só os valores brutos
        hdr = cabecalhos(rows, ("ID", "EMPRESA_JUNIOR"), tab)
        jid = hdr.index("ID")
        out = {}
        for row, row_f in zip(rows[1:], rows_f[1:]):
            row = pad(row, len(hdr))
            eid = txt(row[jid])
            if eid:
                out.setdefault(eid, []).append((row, pad(row_f, len(hdr))))
        return hdr, out

    return {"painel": P, "farol": F, "cors": C, "regua": regua,
            "ref_mes": controle_p[0], "ref_data": controle_p[1], "datas_cors": datas_cors,
            "geral": por_id("geral"), "acum": por_id("acum")}


def premio_da_ej(snap, cfg, nome_ej):
    pc = cfg["premiacao"]
    rows = snap["premio"]
    hdr = [str(x).strip() for x in rows[0]]
    jej = hdr.index(pc["coluna_ej"])
    alvo = norm(nome_ej)
    linha = next((pad(r) for r in rows[1:] if len(r) > jej and norm(r[jej]) == alvo), None)
    corte = ""
    for r in snap.get("premio_aux", rows):
        r = pad(r, 4)
        if norm(r[0]) == norm(pc["rotulo_data_corte"]):
            corte = pc["texto_data_corte"].format(data=str(r[1]).strip())
    return hdr, linha, corte


# ---------------------------------------------------------------- montagem por EJ

def solucoes(G, row):
    vistos, out = set(), []
    for k in range(1, 13):
        nome = txt(G(row, f"NOME_SOLUCAO_{k}"))
        if not nome:
            continue
        val, cs = G(row, f"FATURAMENTO_SOLUCAO_{k}"), txt(G(row, f"CSAT_SOLUCAO_{k}"))
        chave = (txt(G(row, f"ID_SOLUCAO_{k}")), nome, str(val), cs)
        if chave in vistos:
            continue
        vistos.add(chave)
        v = to_num(val)
        s = f"{nome} (R$ {brl(v)}" if isinstance(v, (int, float)) else f"{nome} ("
        s += f", CSAT {cs.replace('.', ',')})" if cs else ")"
        out.append(s.replace("(, ", "("))
    return "; ".join(out)


def celula_geral(G, Gt, row, key, typ):
    if key == "_SOL":
        return solucoes(G, row)
    v = Gt(row, key) if typ in ("t", "tw") else G(row, key)
    if key == "STATUS_FINALIZACAO":
        return {"1": "Finalizado", "0": "Em andamento"}.get(txt(v), txt(v))
    if typ == "d":
        return to_serial(v)
    if typ == "dt":
        return to_serial(v, com_hora=True)
    if typ in ("m", "i", "n", "p"):
        return to_num(v)
    return txt(v)


def celula_acum(A, At, row, key, typ, ano):
    v = At(row, key) if typ in ("t", "tw") else A(row, key)
    if key == "MES":
        return serial(datetime(ano, int(to_num(v)), 1))
    if typ == "dt":
        return to_serial(v, com_hora=True)
    if typ in ("m", "i", "n", "p"):
        return to_num(v)
    return {"SIM": "Sim", "NAO": "Não"}.get(txt(v), txt(v))


def valor_premio(v, formato):
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    if formato == "posicao" and re.fullmatch(r"\d+", s):
        return s + "º"
    if formato == "inteiro":
        return re.sub(r",\d+$", "", s)
    return s


def valor_criterio(c, hdr, linha):
    if c.get("ocultar_valor"):
        return ""
    if c["campo"] not in hdr:
        raise ValueError(f"coluna '{c['campo']}' não existe na aba da premiação")
    return valor_premio(linha[hdr.index(c["campo"])], c.get("formato"))


def montar_ej(ix, snap, cfg, eid, agora):
    """Retorna (lista de {range, values}, avisos) para a EJ."""
    avisos = []
    if eid not in ix["painel"]:
        raise ValueError(f"ID {eid} não está no {T_PAINEL}")
    if eid not in ix["farol"]:
        raise ValueError(f"ID {eid} não está no {T_FAROL}")
    if eid not in ix["cors"]:
        raise ValueError(f"ID {eid} não está no {T_CORS}")
    painel = ix["painel"][eid]
    nome = txt(dict(painel).get("Painel | EJ", ""))
    ref = to_serial(ix["ref_data"])
    ano = (EPOCH + timedelta(days=ref)).year if isinstance(ref, float) else agora.year

    # _dados
    pares = list(painel) + ix["farol"][eid] + ix["cors"][eid]
    hdr_p, linha_p, corte = premio_da_ej(snap, cfg, nome)
    pares += [
        ("Controle | Data de referência", ref),
        ("Controle | Mês de referência", mes_numero(ix["ref_mes"])),
        ("Controle | Última atualização", serial(agora.replace(tzinfo=None, second=0, microsecond=0))),
        ("Controle | Data de corte CORS", to_serial(ix["datas_cors"][0])),
        ("Controle | Data comparável CORS 2025", to_serial(ix["datas_cors"][1])),
        ("Controle | Nome da premiação", cfg["premiacao"]["nome"]),
        ("Controle | Data de corte premiação", corte),
    ] + ix["regua"]
    if len(ix["regua"]) != 10:
        raise ValueError("régua de cluster incompleta no Farol (esperados 5 clusters)")
    dados = [[k, "" if v is None else v] for k, v in pares]

    # Premiação
    if linha_p is None:
        raise ValueError(f"EJ '{nome}' não encontrada na aba {cfg['premiacao']['aba']}")
    prem = []
    for c in cfg["premiacao"]["criterios"]:
        if "grupo" in c:
            prem.append([c["grupo"], "", "", "", "", "", ""])
            continue
        v = valor_criterio(c, hdr_p, linha_p)
        prem.append([c["campo"], "", "", "", "", v, c.get("descricao", "")])

    # Monitoramento Geral
    gh, gmap = ix["geral"]
    gi = {k: i for i, k in enumerate(gh)}
    G = lambda row, k: row[0][gi[k]] if k in gi else ""
    Gt = lambda row, k: row[1][gi[k]] if k in gi else ""
    faltando = [k for k, _ in COLS_GERAL if k != "_SOL" and k not in gi]
    if faltando:
        raise ValueError("colunas ausentes no Geral: " + ", ".join(faltando))
    # o Portal inclui uma linha em branco para EJs sem contrato; ela não entra
    tem_contrato = lambda r: any(txt(G(r, k)) for k in ("DATA_DE_ASSINATURA", "NOME_DO_CLIENTE", "FATURAMENTO"))
    data_ass = lambda r: (lambda v: v if isinstance(v, float) else 0)(to_serial(G(r, "DATA_DE_ASSINATURA")))
    grow = sorted(filter(tem_contrato, gmap.get(eid, [])), key=data_ass, reverse=True)
    geral = [[celula_geral(G, Gt, r, k, t) for k, t in COLS_GERAL] for r in grow]

    # Monitoramento Acumulado
    ah, amap = ix["acum"]
    ai = {k: i for i, k in enumerate(ah)}
    A = lambda row, k: row[0][ai[k]] if k in ai else ""
    At = lambda row, k: row[1][ai[k]] if k in ai else ""
    faltando = [k for k, _ in COLS_ACUM if k not in ai]
    if faltando:
        raise ValueError("colunas ausentes no Acumulado: " + ", ".join(faltando))
    arow = sorted((r for r in amap.get(eid, []) if txt(A(r, "MES"))), key=lambda r: int(to_num(A(r, "MES"))))
    acum = [[celula_acum(A, At, r, k, t, ano) for k, t in COLS_ACUM] for r in arow]
    # o acumulado colaborativo do Portal não fecha com o mensal; recalcula como soma corrida
    keys = [k for k, _ in COLS_ACUM]
    ic, ia = keys.index("FATURAMENTO_COLABORATIVO"), keys.index("FATURAMENTO_COLABORATIVO_ACUMULADO")
    soma = 0
    for r in acum:
        soma += r[ic] if isinstance(r[ic], (int, float)) else 0
        r[ia] = soma

    blocos = [{"range": f"'_dados'!A2:B{1 + len(dados)}", "values": dados},
              {"range": f"'Premiação'!B13:H{12 + len(prem)}", "values": prem}]
    if geral:
        blocos.append({"range": "'Monitoramento Geral'!B8", "values": geral})
    if acum:
        blocos.append({"range": "'Monitoramento Acumulado'!B8", "values": acum})
    # o que sobrar abaixo do que foi gravado (linhas de uma rodada anterior) é apagado
    # a área de critérios da Premiação vai da linha 13 à PREM_FIM; logo abaixo fica a nota de rodapé
    if 12 + len(prem) > PREM_FIM:
        raise ValueError(f"a premiação tem mais critérios do que cabem na aba (linhas 13 a {PREM_FIM})")
    limpar = [f"'_dados'!A{2 + len(dados)}:B150",
              f"'Monitoramento Geral'!B{8 + len(geral)}:AZ1000",
              f"'Monitoramento Acumulado'!B{8 + len(acum)}:BG1000"]
    if 13 + len(prem) <= PREM_FIM:
        limpar += [f"'Premiação'!B{13 + len(prem)}:B{PREM_FIM}", f"'Premiação'!G{13 + len(prem)}:H{PREM_FIM}"]
    return nome, blocos, limpar, avisos


# ---------------------------------------------------------------- escrita

def com_retry(req, tentativas=6):
    from googleapiclient.errors import HttpError
    for n in range(tentativas):
        try:
            return req.execute()
        except HttpError as e:
            status = getattr(e.resp, "status", 0)
            if status in (429, 500, 502, 503) and n < tentativas - 1:
                espera = min(90, 5 * 2 ** n)
                print(f"    API respondeu {status}; nova tentativa em {espera}s")
                time.sleep(espera)
                continue
            raise
        except (socket.timeout, ConnectionError):
            if n < tentativas - 1:
                time.sleep(10)
                continue
            raise


def gravar(service, sid, blocos, limpar):
    # grava primeiro e limpa depois: se a escrita falhar, a EJ continua vendo os dados anteriores
    v = service.spreadsheets().values()
    com_retry(v.batchUpdate(spreadsheetId=sid, body={"valueInputOption": "RAW", "data": blocos}))
    com_retry(v.batchClear(spreadsheetId=sid, body={"ranges": limpar}))


def buscar_na_pasta(drive, pasta, nome):
    q = "'%s' in parents and name = '%s' and trashed = false" % (pasta, nome.replace("\\", "\\\\").replace("'", "\\'"))
    r = com_retry(drive.files().list(q=q, fields="files(id, name)", supportsAllDrives=True,
                                     includeItemsFromAllDrives=True, corpora="allDrives"))
    return r.get("files", [])


def copiar(drive, origem, pasta, nome):
    """Copia o arquivo para a pasta; se já existir um com o mesmo nome (rodada anterior interrompida), reaproveita."""
    achados = buscar_na_pasta(drive, pasta, nome)
    if achados:
        return achados[0]["id"], False
    novo = com_retry(drive.files().copy(fileId=origem, body={"name": nome, "parents": [pasta]},
                                        fields="id", supportsAllDrives=True))
    return novo["id"], True


COLS_ACESSO = {"id": "ID", "ej": "EJ", "planilha": "ID da planilha", "quando": "Última sincronização", "status": "Status"}


def colunas_acesso(snap):
    """Posição de cada coluna da aba de acessos, pelo nome do cabeçalho."""
    hdr = [norm(x) for x in (snap["acessos"] or [[]])[0]]
    faltam = [n for n in COLS_ACESSO.values() if norm(n) not in hdr]
    if faltam:
        raise SystemExit("Colunas que faltam na aba de acessos: " + ", ".join(faltam))
    return {k: hdr.index(norm(n)) for k, n in COLS_ACESSO.items()}


def acessos(snap, cfg):
    """Linhas da aba de acessos (ID, EJ, ID da planilha, Última sincronização, Status, em qualquer ordem)."""
    rows = snap["acessos"] or []
    c = colunas_acesso(snap)
    out = []
    primeira_linha = snap.get("acessos_inicio", 0) + 2
    for i, r in enumerate(rows[1:], start=primeira_linha):
        r = pad(r, 30)
        eid, sid = txt(r[c["id"]]), str(r[c["planilha"]]).strip()
        m = re.search(r"/d/([A-Za-z0-9_-]{20,})", sid)
        sid = m[1] if m else sid
        if eid:
            out.append({"linha": i, "id": eid, "ej": str(r[c["ej"]]).strip(), "planilha": sid})
    return out


def validar_fonte(ix, snap, cfg, alvo):
    """Recusa a rodada inteira antes de qualquer escrita quando a mestre está incompleta."""
    problemas = []
    ids = [a["id"] for a in alvo]
    for nome, fonte in ((T_PAINEL, ix["painel"]), (T_FAROL, ix["farol"]), (T_CORS, ix["cors"])):
        faltam = [eid for eid in ids if eid not in fonte]
        if faltam:
            problemas.append(f"{nome}: IDs ausentes: {', '.join(faltam)}")

    gh = ix["geral"][0]
    faltam = [k for k, _ in COLS_GERAL if k != "_SOL" and k not in gh]
    if faltam:
        problemas.append("Geral: colunas ausentes: " + ", ".join(faltam))
    ah = ix["acum"][0]
    faltam = [k for k, _ in COLS_ACUM if k not in ah]
    if faltam:
        problemas.append("Acumulado: colunas ausentes: " + ", ".join(faltam))

    ph = cabecalhos(snap["premio"], (cfg["premiacao"]["coluna_ej"],), cfg["premiacao"]["aba"])
    faltam = [c["campo"] for c in cfg["premiacao"]["criterios"] if "campo" in c and c["campo"] not in ph]
    if faltam:
        problemas.append("Premiação: colunas ausentes: " + ", ".join(faltam))
    if 12 + len(cfg["premiacao"]["criterios"]) > PREM_FIM:
        problemas.append(f"Premiação: critérios excedem as linhas 13 a {PREM_FIM}")

    for eid in ids:
        if eid not in ix["painel"]:
            continue
        nome = txt(dict(ix["painel"][eid]).get("Painel | EJ", ""))
        if premio_da_ej(snap, cfg, nome)[1] is None:
            problemas.append(f"Premiação: EJ ausente: {nome}")
    if problemas:
        raise ValueError("Pré-validação da mestre falhou — " + " | ".join(problemas))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ej", action="append", help="ID da EJ (pode repetir)")
    ap.add_argument("--dry-run", action="store_true", help="não grava nada")
    ap.add_argument("--snapshot", help="usa um JSON com os dados da mestre em vez da API")
    ap.add_argument("--saida", help="com --snapshot ou --dry-run, salva os blocos montados neste JSON")
    ap.add_argument("--copiar-modelo", action="store_true", help="copia o modelo para a pasta das planilhas e sai")
    args = ap.parse_args()

    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    agora = datetime.now(BRT)
    service = None
    if args.snapshot:
        snap = json.load(open(args.snapshot, encoding="utf-8"))
    else:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from dotenv import load_dotenv
        load_dotenv()
        cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "dde-projeto-9ed22179e048.json")
        cred = cred if os.path.isabs(cred) else os.path.join(PROJECT_DIR, cred)
        creds = service_account.Credentials.from_service_account_file(
            cred, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        print(f"Conta de serviço: {creds.service_account_email}")
        if args.copiar_modelo:
            mid, novo = copiar(drive, cfg["modelo_id"], cfg["pasta_planilhas"], cfg["nome_modelo"])
            print(("Modelo copiado" if novo else "Já existe um modelo na pasta") + f": ID {mid}")
            print(f"  https://docs.google.com/spreadsheets/d/{mid}/edit")
            return
        tabelas = mapear_tabelas(service)
        snap = {
            "acessos": ler_acessos(service, cfg, tabelas),
            "acessos_inicio": tabelas[TABELAS_MESTRE["acessos"]][1].get("startRowIndex", 0),
        }
        print("Lendo a planilha mestre...")
        snap.update(ler_mestre(service, cfg, tabelas))

    ix = indexar(snap)
    alvo = acessos(snap, cfg) if snap.get("acessos") else [{"linha": None, "id": e, "planilha": ""} for e in args.ej or []]
    if args.ej:
        alvo = [a for a in alvo if a["id"] in set(args.ej)]
    validar_fonte(ix, snap, cfg, alvo)
    print(f"{len(alvo)} EJ(s) para atualizar")

    # EJ sem planilha ganha uma cópia do modelo na pasta do drive compartilhado
    if service and not args.dry_run:
        ca = colunas_acesso(snap)
        novas = []
        for a in alvo:
            if a["planilha"] or not a["linha"]:
                continue
            nome_arq = cfg["nome_planilha"].format(ej=a["ej"] or a["id"])
            try:
                a["planilha"], criada = copiar(drive, cfg["modelo_id"], cfg["pasta_planilhas"], nome_arq)
                novas.append({"range": f"'{cfg['aba_acessos']}'!{letra(ca['planilha'])}{a['linha']}", "values": [[a["planilha"]]]})
                print(f"  {a['id']:>4} planilha {'criada' if criada else 'reaproveitada'}: {nome_arq} ({a['planilha']})")
                time.sleep(1)
            except Exception as e:
                print(f"  {a['id']:>4}: não foi possível criar a planilha: {type(e).__name__}: {str(e)[:300]}")
        if novas:
            com_retry(service.spreadsheets().values().batchUpdate(
                spreadsheetId=MASTER_ID, body={"valueInputOption": "RAW", "data": novas}))

    status, saida, erros = [], {}, 0
    for a in alvo:
        try:
            nome, blocos, limpar, avisos = montar_ej(ix, snap, cfg, a["id"], agora)
            saida[a["id"]] = {"nome": nome, "blocos": blocos, "limpar": limpar, "avisos": avisos}
            linhas = {b["range"].split("!")[0]: len(b["values"]) for b in blocos}
            print(f"  {a['id']:>4} {nome}: " + ", ".join(f"{k} {n}" for k, n in linhas.items()))
            for x in avisos:
                print(f"       aviso: {x}")
            if not a["planilha"] and service and not args.dry_run:
                raise ValueError("Sem ID da planilha após a tentativa de criação")
            if args.dry_run or args.snapshot:
                msg = "Simulado"
            else:
                gravar(service, a["planilha"], blocos, limpar)
                msg = "OK" + (" (com avisos: " + "; ".join(avisos) + ")" if avisos else "")
                time.sleep(PAUSA_ENTRE_EJS)
        except Exception as e:  # uma EJ com problema não para as outras
            erros += 1
            msg = f"ERRO: {type(e).__name__}: {str(e)[:300]}"
            print(f"  {a['id']:>4}: {msg}")
        status.append((a["linha"], msg))

    if service and not args.dry_run and any(l for l, _ in status):
        quando = agora.strftime("%d/%m/%Y %H:%M")
        ca = colunas_acesso(snap)
        data = []
        for l, m in status:
            if l:
                data += [{"range": f"'{cfg['aba_acessos']}'!{letra(ca['quando'])}{l}", "values": [[quando]]},
                         {"range": f"'{cfg['aba_acessos']}'!{letra(ca['status'])}{l}", "values": [[m]]}]
        com_retry(service.spreadsheets().values().batchUpdate(
            spreadsheetId=MASTER_ID, body={"valueInputOption": "RAW", "data": data}))
    if args.saida:
        json.dump(saida, open(args.saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Concluído: {len(status) - erros} ok, {erros} com erro")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
