import sys
import types
import unittest
from unittest.mock import patch

import sync_planilhas_ejs as sync
import update_sheets
import validar_planilhas_ejs as validator


class SyncResilienceTest(unittest.TestCase):
    def test_google_internal_error_is_retried(self):
        class HttpError(Exception):
            def __init__(self):
                self.resp = types.SimpleNamespace(status=500)

        class Request:
            calls = 0

            def execute(self):
                self.calls += 1
                if self.calls == 1:
                    raise HttpError()
                return {"values": [["ID"]]}

        googleapiclient = types.ModuleType("googleapiclient")
        errors = types.ModuleType("googleapiclient.errors")
        errors.HttpError = HttpError
        request = Request()
        with patch.dict(sys.modules, {"googleapiclient": googleapiclient, "googleapiclient.errors": errors}), \
             patch.object(sync.time, "sleep"):
            self.assertEqual(sync.com_retry(request), {"values": [["ID"]]})
        self.assertEqual(request.calls, 2)

    def test_named_table_range_uses_live_metadata(self):
        tables = {"Cluster_JUNIORES": ("Farol de Cluster [G3]", {
            "startRowIndex": 2, "endRowIndex": 32,
            "startColumnIndex": 1, "endColumnIndex": 21,
        })}
        self.assertEqual(
            sync.intervalo_tabela(tables, "Cluster_JUNIORES"),
            "'Farol de Cluster [G3]'!B3:U32",
        )

    def test_ruler_is_found_by_labels_after_row_shift(self):
        rows = [[], ["", "RÉGUA DE CLUSTER"], ["", "DE", "ATÉ", "CLUSTER"]]
        rows += [["", n * 10, (n + 1) * 10, f"C{n}"] for n in range(1, 6)]
        ruler = sync.extrair_regua(rows)
        self.assertEqual(len(ruler), 10)
        self.assertEqual(ruler[0], ("Régua | Cluster 1 | Piso", 10))

    def test_source_values_cannot_be_used_as_headers(self):
        rows = [["62", "Energy Junior", "3", "PERMANECE"], ["79", "Zetta Júnior", "5", "PERMANECE"]]
        with self.assertRaisesRegex(ValueError, "colunas ausentes"):
            sync.campos_por_id(rows, "Farol", ("EJ", "CLUSTER", "FAROL"))

    def test_access_row_follows_named_table_position(self):
        snapshot = {
            "acessos_inicio": 4,
            "acessos": [["ID", "EJ", "ID da planilha", "Última sincronização", "Status"],
                        [62, "Energy Junior", "sheet-id", "", ""]],
        }
        self.assertEqual(sync.acessos(snapshot, {})[0]["linha"], 6)

    def test_blank_excel_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cabeçalho vazio"):
            update_sheets.validar_cabecalhos(["ID", None, "FATURAMENTO"], ("ID",), "relatório")

    def test_missing_required_excel_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "obrigatórias ausentes"):
            update_sheets.validar_cabecalhos(["ID", "EMPRESA_JUNIOR"], ("FATURAMENTO",), "relatório")

    def test_configured_field_is_published_by_ej_name(self):
        campo = {"tabela": "Premio_ENCEJ", "buscar_por": "EJ", "campo": "IMS",
                 "chave": "Premiação | IMS", "formato": "formatado"}
        snap = {"campos_config": {"Premio_ENCEJ": {
            "bruto": [["EJ", "IMS"], ["Energy Junior", 4.6]],
            "formatado": [["EJ", "IMS"], ["Energy Junior", "4,600"]],
        }}}
        ix = {"campos_config": sync.indexar_campos_configurados(snap, [campo])}
        self.assertEqual(sync.campos_configurados(ix, "62", "Energy Junior"),
                         [("Premiação | IMS", "4,600")])

    def test_current_prize_ranks_remain_unpublished(self):
        self.assertFalse(any("Rank" in campo["chave"] for campo in sync.carregar_campos()))

    def test_pi_rule_caps_cluster_3_and_drops_clusters_4_and_5(self):
        self.assertEqual(validator.MENSAGEM_PI, "Falta P.I.")
        self.assertEqual(validator.aplicar_regra_pi(3, 4, False), 3)
        self.assertEqual(validator.aplicar_regra_pi(4, 5, False), 3)
        self.assertEqual(validator.aplicar_regra_pi(5, 5, False), 4)
        self.assertEqual(validator.aplicar_regra_pi(5, 5, True), 5)
        self.assertTrue(validator.falta_pi_para_subir(3, 4, False))
        self.assertTrue(validator.falta_pi_para_subir(5, 5, False))
        self.assertFalse(validator.falta_pi_para_subir(3, 3, False))


if __name__ == "__main__":
    unittest.main()
