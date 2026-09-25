"""
Confere as planilhas das EJs contra a planilha mestre, sem gravar nada.

Para cada EJ da aba de acessos verifica:
  arquivo      nome, pasta do drive compartilhado, não está na lixeira
  estrutura    abas, _dados oculta, intervalos nomeados, gráficos, proteções e entradas livres do Simulador
  erros        nenhuma célula com #N/A, #REF!, #VALUE!, #DIV/0!, #ERROR!, #NAME? ou #NUM!
  identidade   ID e nome da EJ no _dados batem com a linha da aba de acessos
  gravação     _dados, Premiação e Monitoramentos iguais, célula a célula, ao que a sincronização gravaria agora
               (sem linhas antigas sobrando embaixo)
  mestre       contagem de contratos e de meses e soma do faturamento contadas direto nas abas da mestre;
               critérios da Premiação comparados direto com a linha da EJ na aba do prêmio
  simulador    entradas vazias, índice igual ao previsto do Farol, cluster, "para subir" e "para não cair"
               recalculados aqui pela regra do índice
  atualização  data de "Atualizado em" das últimas 24 horas

O repositório é público, então o log mostra só o endereço das divergências, nunca os valores.

Uso:
  python validar_planilhas_ejs.py             # todas as EJs
  python validar_planilhas_ejs.py --ej 90     # só algumas
"""
import argparse
import math
import os
import re
import sys
from datetime import datetime

import sync_planilhas_ejs as S

ERROS = re.compile(r"^#(N/A|REF!|VALUE!|DIV/0!|ERROR!|NAME\?|NUM!|NULL!)")
ABAS = ["Visão Geral", "Premiação", "Simulador", "Monitoramento Geral", "Monitoramento Acumulado", "_dados"]
TOL = 1e-6


def igual(a, b):
    if a in (None, "") and b in (None, ""):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).upper() == str(b).upper()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=TOL)
    return str(a).strip() == str(b).strip()


def col(j):
    return S.letra(j)


def celulas(valores, r0, c0):
    """Converte a lista de linhas lida da API em {(linha, coluna): valor}, só com as preenchidas."""
    out = {}
    for i, row in enumerate(valores):
        for j, v in enumerate(row):
            if v not in (None, ""):
                out[(r0 + i, c0 + j)] = v
    return out


def comparar_bloco(esperado, lido, r0, c0, rotulo, prob, limite=None):
    """esperado: lista de linhas que a sincronização grava a partir de (r0, c0); lido: células da planilha."""
    exp = {}
    for i, row in enumerate(esperado):
        for j, v in enumerate(row):
            exp[(r0 + i, c0 + j)] = v
    n = 0
    for (r, c), v in exp.items():
        if not igual(v, lido.get((r, c), "")):
            n += 1
            if n <= 5:
                prob.append(f"{rotulo}: {col(c)}{r} difere do esperado")
    # nada preenchido abaixo do bloco (linhas antigas)
    fim = r0 + len(esperado)
    sobra = [(r, c) for (r, c) in lido if r >= fim and c >= c0 and (limite is None or c <= limite)]
    if sobra:
        r, c = min(sobra)
        prob.append(f"{rotulo}: {len(sobra)} célula(s) sobrando abaixo do esperado, a partir de {col(c)}{r}")
    if n > 5:
        prob.append(f"{rotulo}: mais {n - 5} célula(s) diferentes")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ej", action="append")
    args = ap.parse_args()

    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    cfg = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
    cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "dde-projeto-9ed22179e048.json")
    cred = cred if os.path.isabs(cred) else os.path.join(S.PROJECT_DIR, cred)
    creds = service_account.Credentials.from_service_account_file(
        cred, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly",
                      "https://www.googleapis.com/auth/drive.readonly"])
    sh = build("sheets", "v4", credentials=creds, cache_discovery=False)
    dr = build("drive", "v3", credentials=creds, cache_discovery=False)

    print("Lendo a planilha mestre...")
    snap = {"acessos": S.ler_acessos(sh, cfg)}
    snap.update(S.ler_mestre(sh, cfg))
    ix = S.indexar(snap)
    agora = datetime.now(S.BRT)
    alvo = S.acessos(snap, cfg)
    if args.ej:
        alvo = [a for a in alvo if a["id"] in set(args.ej)]

    # referência do modelo: gráficos e proteções por aba
    mod = S.com_retry(sh.spreadsheets().get(spreadsheetId=cfg["modelo_id"],
                                            fields="sheets(properties(title),charts(chartId),protectedRanges(protectedRangeId))"))
    graf_mod = {s["properties"]["title"]: len(s.get("charts", [])) for s in mod["sheets"]}

    # mestre bruta, para contagens independentes
    def por_id(tab):
        rows = snap[tab]
        hdr = [str(x).strip() for x in rows[0]]
        out = {}
        for r in rows[1:]:
            r = S.pad(r)
            if str(r[0]).strip():
                out.setdefault(S.txt(r[0]), []).append(r)
        return hdr, out
    gh, gm = por_id("geral")
    ah, am = por_id("acum")
    gi = {k: i for i, k in enumerate(gh)}
    ai = {k: i for i, k in enumerate(ah)}
    tem_contrato = lambda r: any(S.txt(r[gi[k]]) for k in ("DATA_DE_ASSINATURA", "NOME_DO_CLIENTE", "FATURAMENTO"))

    prem = snap["premio"]
    phdr = [str(x).strip() for x in prem[0]]
    jej = phdr.index(cfg["premiacao"]["coluna_ej"])

    regua = {}
    for k, v in ix["regua"]:
        m = re.match(r"Régua \| Cluster (\d) \| (Piso|Teto)", k)
        regua[(int(m[1]), m[2])] = v

    total_prob, ej_ok = 0, 0
    print(f"{len(alvo)} EJ(s) para conferir\n")
    for a in alvo:
        prob = []
        sid, eid = a["planilha"], a["id"]
        try:
            if not sid:
                raise RuntimeError("sem ID da planilha na aba de acessos")

            # arquivo
            f = S.com_retry(dr.files().get(fileId=sid, fields="name,parents,driveId,trashed,mimeType",
                                           supportsAllDrives=True))
            if f.get("trashed"):
                prob.append("arquivo está na lixeira")
            if cfg["pasta_planilhas"] not in f.get("parents", []):
                prob.append("arquivo fora da pasta do drive compartilhado")
            if not f.get("driveId"):
                prob.append("arquivo fora de drive compartilhado")
            nome_ok = cfg["nome_planilha"].format(ej=a["ej"] or eid)
            if f.get("name") != nome_ok:
                prob.append(f"nome do arquivo diferente de '{nome_ok}'")

            # estrutura
            meta = S.com_retry(sh.spreadsheets().get(
                spreadsheetId=sid,
                fields="namedRanges(name),sheets(properties(title,hidden),charts(chartId),"
                       "protectedRanges(warningOnly,range,unprotectedRanges))"))
            titulos = [s["properties"]["title"] for s in meta["sheets"]]
            if titulos != ABAS:
                prob.append("abas diferentes do modelo: " + ", ".join(titulos))
            por_aba = {s["properties"]["title"]: s for s in meta["sheets"]}
            if not por_aba.get("_dados", {}).get("properties", {}).get("hidden"):
                prob.append("aba _dados não está oculta")
            nomes = {n["name"] for n in meta.get("namedRanges", [])}
            for n in ("Dados_Campo", "Dados_Valor"):
                if n not in nomes:
                    prob.append(f"intervalo nomeado {n} ausente")
            for t, s in por_aba.items():
                if len(s.get("charts", [])) != graf_mod.get(t, 0):
                    prob.append(f"{t}: {len(s.get('charts', []))} gráfico(s), o modelo tem {graf_mod.get(t, 0)}")
                prs = s.get("protectedRanges", [])
                if not prs:
                    prob.append(f"{t}: sem proteção")
                elif not all(p.get("warningOnly") for p in prs):
                    prob.append(f"{t}: proteção que bloqueia edição (deveria ser só aviso)")
            sim_livre = any(u.get("startRowIndex") == 7 and u.get("endRowIndex") == 11 and u.get("startColumnIndex") == 7
                            for p in por_aba.get("Simulador", {}).get("protectedRanges", [])
                            for u in p.get("unprotectedRanges", []))
            if not sim_livre:
                prob.append("Simulador: H8:H11 não estão livres da proteção")

            # valores
            rng = [f"'{t}'!A1:BZ1000" for t in ABAS]
            bu = S.com_retry(sh.spreadsheets().values().batchGet(
                spreadsheetId=sid, ranges=rng, valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER"))["valueRanges"]
            bf = S.com_retry(sh.spreadsheets().values().batchGet(
                spreadsheetId=sid, ranges=rng, valueRenderOption="FORMATTED_VALUE"))["valueRanges"]
            U = {t: celulas(v.get("values", []), 1, 0) for t, v in zip(ABAS, bu)}
            FV = {t: celulas(v.get("values", []), 1, 0) for t, v in zip(ABAS, bf)}

            # erros de fórmula
            for t in ABAS:
                errs = sorted((r, c) for (r, c), v in FV[t].items() if ERROS.match(str(v)))
                if errs:
                    r, c = errs[0]
                    prob.append(f"{t}: {len(errs)} célula(s) com erro, a primeira em {col(c)}{r}")

            # identidade
            dados = {str(U["_dados"].get((r, 0), "")): U["_dados"].get((r, 1), "") for r in range(2, 200)}
            if S.txt(dados.get("Painel | ID")) != eid:
                prob.append("_dados: Painel | ID não é o ID desta EJ")
            if S.norm(dados.get("Painel | EJ")) != S.norm(a["ej"]):
                prob.append("_dados: nome da EJ diferente da aba de acessos")

            # gravação: o que a sincronização gravaria agora
            nome, blocos, limpar, avisos = S.montar_ej(ix, snap, cfg, eid, agora)
            for b in blocos:
                aba, ref = b["range"].split("!")
                aba = aba.strip("'")
                m = re.match(r"([A-Z]+)(\d+)", ref)
                c0 = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(m[1]))) - 1
                r0 = int(m[2])
                vals = b["values"]
                lido = U[aba]
                if aba == "_dados":
                    # a hora da última atualização muda a cada rodada; confere à parte
                    vals = [row for row in vals if row[0] != "Controle | Última atualização"]
                    lido = {k: v for k, v in lido.items() if k[0] >= 2}
                    # compara por campo, não por posição
                    for k, v in vals:
                        if not igual(v, dados.get(k, "")):
                            prob.append(f"_dados: campo '{k}' difere do esperado")
                    extras = set(dados) - {k for k, _ in vals} - {"", "Controle | Última atualização", "Campo"}
                    if extras:
                        prob.append(f"_dados: {len(extras)} campo(s) a mais que o esperado")
                    continue
                if aba == "Premiação":
                    lido = {k: v for k, v in lido.items() if 13 <= k[0] <= S.PREM_FIM and 1 <= k[1] <= 7}
                comparar_bloco(vals, lido, r0, c0, aba, prob, limite=c0 + len(vals[0]) - 1 if vals else None)
            if not any(b["range"].startswith("'Monitoramento Geral'") for b in blocos):
                sobra = [k for k in U["Monitoramento Geral"] if k[0] >= 8 and k[1] >= 1]
                if sobra:
                    prob.append(f"Monitoramento Geral: {len(sobra)} célula(s) preenchidas numa EJ sem contratos")
            if not any(b["range"].startswith("'Monitoramento Acumulado'") for b in blocos):
                sobra = [k for k in U["Monitoramento Acumulado"] if k[0] >= 8 and k[1] >= 1]
                if sobra:
                    prob.append(f"Monitoramento Acumulado: {len(sobra)} célula(s) preenchidas numa EJ sem meses")

            # mestre, contado direto
            linhas_g = [r for r in gm.get(eid, []) if tem_contrato(r)]
            n_g = len({k[0] for k in U["Monitoramento Geral"] if k[0] >= 8 and k[1] >= 1})
            if n_g != len(linhas_g):
                prob.append(f"Monitoramento Geral: {n_g} contrato(s), a mestre tem {len(linhas_g)}")
            jf = 1 + [k for k, _ in S.COLS_GERAL].index("FATURAMENTO")
            soma_copia = sum(v for (r, c), v in U["Monitoramento Geral"].items()
                             if r >= 8 and c == jf and isinstance(v, (int, float)))
            soma_mestre = sum(S.to_num(r[gi["FATURAMENTO"]]) or 0 for r in linhas_g
                              if isinstance(S.to_num(r[gi["FATURAMENTO"]]), (int, float)))
            if not math.isclose(soma_copia, soma_mestre, abs_tol=0.01):
                prob.append("Monitoramento Geral: soma do faturamento difere da mestre")
            linhas_a = [r for r in am.get(eid, []) if S.txt(r[ai["MES"]])]
            n_a = len({k[0] for k in U["Monitoramento Acumulado"] if k[0] >= 8 and k[1] >= 1})
            if n_a != len(linhas_a):
                prob.append(f"Monitoramento Acumulado: {n_a} mês(es), a mestre tem {len(linhas_a)}")
            ja = 1 + [k for k, _ in S.COLS_ACUM].index("FATURAMENTO")
            soma_a = sum(v for (r, c), v in U["Monitoramento Acumulado"].items()
                         if r >= 8 and c == ja and isinstance(v, (int, float)))
            soma_am = sum(S.to_num(r[ai["FATURAMENTO"]]) or 0 for r in linhas_a
                          if isinstance(S.to_num(r[ai["FATURAMENTO"]]), (int, float)))
            if not math.isclose(soma_a, soma_am, abs_tol=0.01):
                prob.append("Monitoramento Acumulado: soma do faturamento mensal difere da mestre")

            # Premiação direto da aba do prêmio
            linha_p = next((S.pad(r) for r in prem[1:] if len(r) > jej and S.norm(r[jej]) == S.norm(a["ej"])), None)
            if linha_p is None:
                prob.append("Premiação: EJ não encontrada na aba do prêmio da mestre")
            else:
                n_crit = 0
                for r in range(13, S.PREM_FIM + 1):
                    campo = str(FV["Premiação"].get((r, 1), "")).strip()
                    if campo in phdr:
                        n_crit += 1
                        esperado = str(linha_p[phdr.index(campo)]).strip()
                        lido_v = str(FV["Premiação"].get((r, 6), "")).strip()
                        e2 = re.sub(r",\d+$", "", esperado.replace("º", ""))
                        l2 = re.sub(r",\d+$", "", lido_v.replace("º", ""))
                        if lido_v != esperado and l2 != e2:
                            prob.append(f"Premiação: G{r} ({campo}) difere da mestre")
                n_cfg = sum(1 for c in cfg["premiacao"]["criterios"] if "campo" in c)
                if n_crit != n_cfg:
                    prob.append(f"Premiação: {n_crit} critério(s) na aba, o config tem {n_cfg}")

            # Simulador
            Sim = U["Simulador"]
            if any(Sim.get((r, 7), "") not in ("", None) for r in range(8, 12)):
                prob.append("Simulador: há valores digitados em H8:H11")
            g = lambda k: dados.get(k, "")
            fat, col_, csat = S.to_num(g("Farol | FATURAMENTO ALCANÇADO")), S.to_num(g("Farol | FAT. COLAB")), S.to_num(g("Farol | CSAT ALCANÇADO"))
            ecm, prev, atual = S.to_num(g("Farol | ECM ALCANÇADO")), S.to_num(g("Farol | ÍNDICE PREVISTO")), S.to_num(g("Farol | CLUSTER"))
            mes = S.to_num(g("Controle | Mês de referência"))
            recalc = (fat + col_) * 12 / mes * csat * (1 + ecm) * 100
            if not math.isclose(max(recalc, 1), prev, rel_tol=1e-6, abs_tol=0.01):
                prob.append("Simulador: a fórmula do índice não reproduz o índice previsto do Farol")
            if not igual(Sim.get((28, 7)), prev):
                prob.append("Simulador: H28 diferente do índice previsto do Farol")
            piso = {c: regua[(c, "Piso")] for c in range(1, 6)}
            fp = fat * 12 / mes
            land = 1 if fp <= 0 else max(c for c in piso if piso[c] <= prev)
            fin = atual + 1 if land > atual else land
            if str(Sim.get((16, 4), "")) != f"Cluster {fin}":
                prob.append("Simulador: E16 (cluster no fim do ano) difere do cálculo")
            k = csat * (1 + ecm) * 100
            base = (fat + col_) * 12 / mes
            up2 = lambda x: math.ceil(round(x * 100, 6)) / 100
            sub = "Cluster máximo" if atual >= 5 else ("Já sobe" if fin > atual else up2(piso[atual + 1] / k - base))
            nc = "Sem risco" if fin >= atual else up2(piso[atual] / k - base)
            perto = lambda x, y: (math.isclose(x, y, abs_tol=0.011) if isinstance(x, (int, float)) and isinstance(y, (int, float))
                                  else igual(x, y))
            if not perto(Sim.get((16, 7)), sub):
                prob.append("Simulador: H16 (para subir) difere do cálculo")
            if not perto(Sim.get((16, 10)), nc):
                prob.append("Simulador: K16 (para não cair) difere do cálculo")
            st = "CAI" if fin < atual else ("SOBE" if fin > atual else "PERMANECE")
            if str(Sim.get((18, 4), "")) != st:
                prob.append("Simulador: E18 (situação) difere do cálculo")

            # atualização
            ua = dados.get("Controle | Última atualização")
            if not isinstance(ua, (int, float)) or S.serial(agora.replace(tzinfo=None)) - ua > 1:
                prob.append("Controle | Última atualização com mais de 24 horas")
            for t, ref in (("Visão Geral", (3, 9)), ("Premiação", (3, 9)), ("Simulador", (3, 9))):
                if not str(FV[t].get(ref, "")).startswith("Atualizado em "):
                    prob.append(f"{t}: J3 sem 'Atualizado em'")
            if avisos:
                prob += [f"aviso da montagem: {x}" for x in avisos]
        except Exception as e:
            prob.append(f"falha ao conferir: {type(e).__name__}: {str(e)[:200]}")

        total_prob += len(prob)
        if prob:
            print(f"{eid:>5} {a['ej']}: {len(prob)} problema(s)")
            for p in prob:
                print(f"        - {p}")
        else:
            ej_ok += 1
            print(f"{eid:>5} {a['ej']}: OK")

    print(f"\nResultado: {ej_ok} de {len(alvo)} EJs sem problema; {total_prob} problema(s) no total")
    sys.exit(1 if total_prob else 0)


if __name__ == "__main__":
    main()
