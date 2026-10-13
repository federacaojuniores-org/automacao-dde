import unittest

import sync_planilhas_ejs as sync
import update_sheets


class SyncResilienceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
