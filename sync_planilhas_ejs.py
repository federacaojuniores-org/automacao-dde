"""
Distribui os dados da planilha mestre (00 - TRACKING [DDE 26]) para as planilhas individuais das EJs.

Cada EJ tem uma cópia do modelo "Tracking da EJ". Este script só grava valores, sem fórmulas
apontando para a mestre, em quatro lugares de cada cópia:
  _dados!A2:B              pares "Fonte | campo" -> valor, lidos pela Visão Geral e pelo Simulador
  Premiação!B13:H          critérios da premiação vigente (config_planilhas_ejs.json)
  Monitoramento Geral!B8   contratos de 2026 da EJ
  Monitoramento Acumulado!B8  linhas mês a mês da EJ

A lista de EJs vem da aba de acessos da mestre (ID, EJ, e-mail, ID da planilha, ...).
O script não cria arquivos nem mexe em compartilhamento: a conta de serviço não tem cota no Drive,
então as cópias são criadas por uma pessoa e compartilhadas com a conta de serviço como editora.

Uso:
  python sync_planilhas_ejs.py                 # todas as EJs com planilha na aba de acessos
  python sync_planilhas_ejs.py --ej 90 --ej 62 # só algumas
  python sync_planilhas_ejs.py --dry-run       # lê a mestre e mostra o que seria gravado
  python sync_planilhas_ejs.py --snapshot x.json --ej 90 --saida y.json  # teste offline
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
T_CORS = "CORS"
T_GERAL = "[MONITORAMENTO] Geral v2.0"
T_ACUM = "[MONITORAMENTO] Acumulado v2.0"

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
    ("ULTIMA_AUDITORIA", "dt"),  # Última auditoria
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


# ---------------------------------------------------------------- leitura da mestre

def ler_mestre(service, cfg):
    aba_p = cfg["premiacao"]["aba"]
    ranges = [f"'{T_PAINEL}'!A1:AZ200", f"'{T_FAROL}'!A1:Z200", f"'{T_CORS}'!A1:BZ200",
              f"'{T_GERAL}'!A1:FZ", f"'{T_ACUM}'!A1:EZ"]
    r = service.spreadsheets().values().batchGet(
        spreadsheetId=MASTER_ID, ranges=ranges, valueRenderOption="UNFORMATTED_VALUE",
        dateTimeRenderOption="SERIAL_NUMBER").execute()["valueRanges"]
    # a premiação é copiada como aparece na mestre (texto formatado)
    p = service.spreadsheets().values().get(
        spreadsheetId=MASTER_ID, range=f"'{aba_p}'!A1:BZ200", valueRenderOption="FORMATTED_VALUE").execute()
    nomes = ["painel", "farol", "cors", "geral", "acum"]
    snap = {n: x.get("values", []) for n, x in zip(nomes, r)}
    snap["premio"] = p.get("values", [])
    return snap


def ler_acessos(service, cfg):
    from googleapiclient.errors import HttpError
    try:
        r = service.spreadsheets().values().get(
            spreadsheetId=MASTER_ID, range=f"'{cfg['aba_acessos']}'!A1:H200",
            valueRenderOption="UNFORMATTED_VALUE").execute()
    except HttpError as e:
        if getattr(e.resp, "status", 0) == 400:
            return None  # a aba ainda não existe
        raise
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
    painel, farol, cors = snap["painel"], snap["farol"], snap["cors"]

    # Painel: linha 1 tem mês e data de referência, linha 2 os cabeçalhos, dados a partir da 3
    h = pad(painel[1])
    cols_p = [(j, str(h[j]).strip()) for j in range(1, len(painel[1]))
              if str(h[j]).strip() and not str(h[j]).startswith("Coluna")]
    P = {}
    for row in painel[2:]:
        row = pad(row)
        if not str(row[1]).strip():
            break  # abaixo da tabela há blocos auxiliares
        P[txt(row[1])] = [(f"Painel | {k}", row[j]) for j, k in cols_p]
    l1 = pad(painel[0])

    # Farol: cabeçalhos na linha 4, dados a partir da 5, até antes da coluna "RÉGUA"
    h = pad(farol[3])
    cols_f = []
    for j in range(1, len(farol[3])):
        k = str(h[j]).strip()
        if k.upper().startswith("RÉGUA"):
            break
        if k:
            cols_f.append((j, k))
    F = {}
    for row in farol[4:]:
        row = pad(row)
        if not str(row[1]).strip():
            break
        F[txt(row[1])] = [(f"Farol | {k}", row[j]) for j, k in cols_f]

    # CORS: datas na linha 2, cabeçalhos na linha 4; dois blocos que começam em "ID" (2026 e 2025)
    h = pad(cors[3])
    ids = [j for j in range(len(cors[3])) if str(h[j]).strip() == "ID"]
    blocos = []
    for n, (ini, fonte) in enumerate(zip(ids, ("CORS 2026", "CORS 2025"))):
        fim = ids[n + 1] if n + 1 < len(ids) else len(cors[3])
        blocos.append((ini, fonte, [(j, str(h[j]).strip()) for j in range(ini, fim) if str(h[j]).strip()]))
    C = {}
    for row in cors[4:]:
        row = pad(row)
        if not txt(row[0]):
            break
        for ini, fonte, cols in blocos:
            eid = txt(row[ini])
            if eid:
                C.setdefault(eid, []).extend((f"{fonte} | {k}", row[j]) for j, k in cols)
    l2 = pad(cors[1])
    datas_cors = (l2[1], l2[3])

    def por_id(tab):
        rows = snap[tab]
        if not rows:
            return [], {}
        hdr = [str(x).strip() for x in rows[0]]
        out = {}
        for row in rows[1:]:
            row = pad(row)
            if str(row[0]).strip():
                out.setdefault(txt(row[0]), []).append(row)
        return hdr, out

    return {"painel": P, "farol": F, "cors": C, "ref_mes": l1[4], "ref_data": l1[5], "datas_cors": datas_cors,
            "geral": por_id("geral"), "acum": por_id("acum")}


def premio_da_ej(snap, cfg, nome_ej):
    pc = cfg["premiacao"]
    rows = snap["premio"]
    hdr = [str(x).strip() for x in rows[0]]
    jej = hdr.index(pc["coluna_ej"])
    alvo = norm(nome_ej)
    linha = next((pad(r) for r in rows[1:] if len(r) > jej and norm(r[jej]) == alvo), None)
    corte = ""
    for r in rows:
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


def celula_geral(G, row, key, typ):
    if key == "_SOL":
        return solucoes(G, row)
    v = G(row, key)
    if key == "STATUS_FINALIZACAO":
        return {"1": "Finalizado", "0": "Em andamento"}.get(txt(v), txt(v))
    if typ == "d":
        return to_serial(v)
    if typ == "dt":
        return to_serial(v, com_hora=True)
    if typ in ("m", "i", "n", "p"):
        return to_num(v)
    return txt(v)


def celula_acum(A, row, key, typ, ano):
    v = A(row, key)
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


def montar_ej(ix, snap, cfg, eid, agora):
    """Retorna (lista de {range, values}, avisos) para a EJ."""
    avisos = []
    if eid not in ix["painel"]:
        raise ValueError(f"ID {eid} não está no {T_PAINEL}")
    painel = ix["painel"][eid]
    nome = txt(dict(painel).get("Painel | EJ", ""))
    ref = to_serial(ix["ref_data"])
    ano = (EPOCH + timedelta(days=ref)).year if isinstance(ref, float) else agora.year

    # _dados
    pares = list(painel) + ix["farol"].get(eid, []) + ix["cors"].get(eid, [])
    if eid not in ix["farol"]:
        avisos.append("sem linha no Farol de Cluster")
    if eid not in ix["cors"]:
        avisos.append("sem linha no CORS")
    hdr_p, linha_p, corte = premio_da_ej(snap, cfg, nome)
    pares += [
        ("Controle | Data de referência", ref),
        ("Controle | Mês de referência", mes_numero(ix["ref_mes"])),
        ("Controle | Última atualização", serial(agora.replace(tzinfo=None, second=0, microsecond=0))),
        ("Controle | Data de corte CORS", to_serial(ix["datas_cors"][0])),
        ("Controle | Data comparável CORS 2025", to_serial(ix["datas_cors"][1])),
        ("Controle | Nome da premiação", cfg["premiacao"]["nome"]),
        ("Controle | Data de corte premiação", corte),
    ]
    dados = [[k, "" if v is None else v] for k, v in pares]

    # Premiação
    if linha_p is None:
        avisos.append(f"EJ '{nome}' não encontrada na aba {cfg['premiacao']['aba']}")
    prem = []
    for c in cfg["premiacao"]["criterios"]:
        if "grupo" in c:
            prem.append([c["grupo"], "", "", "", "", "", ""])
            continue
        v = ""
        if linha_p is not None:
            if c["campo"] in hdr_p:
                v = valor_premio(linha_p[hdr_p.index(c["campo"])], c.get("formato"))
            else:
                avisos.append(f"coluna '{c['campo']}' não existe na aba da premiação")
        prem.append([c["campo"], "", "", "", "", v, c.get("descricao", "")])

    # Monitoramento Geral
    gh, gmap = ix["geral"]
    gi = {k: i for i, k in enumerate(gh)}
    G = lambda row, k: row[gi[k]] if k in gi else ""
    faltando = [k for k, _ in COLS_GERAL if k != "_SOL" and k not in gi]
    if faltando:
        avisos.append("colunas ausentes no Geral: " + ", ".join(faltando))
    grow = sorted(gmap.get(eid, []), key=lambda r: to_serial(G(r, "DATA_DE_ASSINATURA")) or 0, reverse=True)
    geral = [[celula_geral(G, r, k, t) for k, t in COLS_GERAL] for r in grow]

    # Monitoramento Acumulado
    ah, amap = ix["acum"]
    ai = {k: i for i, k in enumerate(ah)}
    A = lambda row, k: row[ai[k]] if k in ai else ""
    faltando = [k for k, _ in COLS_ACUM if k not in ai]
    if faltando:
        avisos.append("colunas ausentes no Acumulado: " + ", ".join(faltando))
    arow = sorted((r for r in amap.get(eid, []) if txt(A(r, "MES"))), key=lambda r: int(to_num(A(r, "MES"))))
    acum = [[celula_acum(A, r, k, t, ano) for k, t in COLS_ACUM] for r in arow]
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
    # a área de critérios da Premiação vai da linha 13 à 46; a 48 tem a nota de rodapé
    if 12 + len(prem) > 46:
        avisos.append("a premiação tem mais critérios do que cabem na aba (linhas 13 a 46)")
    limpar = [f"'_dados'!A{2 + len(dados)}:B150",
              f"'Monitoramento Geral'!B{8 + len(geral)}:AZ1000",
              f"'Monitoramento Acumulado'!B{8 + len(acum)}:BH1000"]
    if 13 + len(prem) <= 46:
        limpar += [f"'Premiação'!B{13 + len(prem)}:B46", f"'Premiação'!G{13 + len(prem)}:H46"]
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


def acessos(snap, cfg):
    """Linhas da aba de acessos: ID | EJ | E-mail | ID da planilha | Link | Última sincronização | Status."""
    rows = snap["acessos"] or []
    out = []
    for i, r in enumerate(rows[1:], start=2):
        r = pad(r, 8)
        eid, sid = txt(r[0]), str(r[3]).strip()
        m = re.search(r"/d/([A-Za-z0-9_-]{20,})", sid)
        sid = m[1] if m else sid
        if eid:
            out.append({"linha": i, "id": eid, "planilha": sid})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ej", action="append", help="ID da EJ (pode repetir)")
    ap.add_argument("--dry-run", action="store_true", help="não grava nada")
    ap.add_argument("--snapshot", help="usa um JSON com os dados da mestre em vez da API")
    ap.add_argument("--saida", help="com --snapshot ou --dry-run, salva os blocos montados neste JSON")
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
            cred, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        print(f"Conta de serviço: {creds.service_account_email}")
        snap = {"acessos": ler_acessos(service, cfg)}
        if snap["acessos"] is None:
            print(f"A aba '{cfg['aba_acessos']}' não existe na mestre. Nada a atualizar.")
            return
        print("Lendo a planilha mestre...")
        snap.update(ler_mestre(service, cfg))

    ix = indexar(snap)
    alvo = acessos(snap, cfg) if snap.get("acessos") else [{"linha": None, "id": e, "planilha": ""} for e in args.ej or []]
    if args.ej:
        alvo = [a for a in alvo if a["id"] in set(args.ej)]
    print(f"{len(alvo)} EJ(s) para atualizar")

    status, saida, erros = [], {}, 0
    for a in alvo:
        try:
            nome, blocos, limpar, avisos = montar_ej(ix, snap, cfg, a["id"], agora)
            saida[a["id"]] = {"nome": nome, "blocos": blocos, "limpar": limpar, "avisos": avisos}
            linhas = {b["range"].split("!")[0]: len(b["values"]) for b in blocos}
            print(f"  {a['id']:>4} {nome}: " + ", ".join(f"{k} {n}" for k, n in linhas.items()))
            for x in avisos:
                print(f"       aviso: {x}")
            if not a["planilha"]:
                msg = "Sem ID da planilha"
            elif args.dry_run or args.snapshot:
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
        data = [{"range": f"'{cfg['aba_acessos']}'!F{l}:G{l}", "values": [[quando, m]]} for l, m in status if l]
        com_retry(service.spreadsheets().values().batchUpdate(
            spreadsheetId=MASTER_ID, body={"valueInputOption": "RAW", "data": data}))
    if args.saida:
        json.dump(saida, open(args.saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Concluído: {len(status) - erros} ok, {erros} com erro")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
