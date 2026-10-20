import unittest

import aplicar_modelo_ejs as model


class ApplyModelTest(unittest.TestCase):
    def test_user_input_follows_label_after_row_move(self):
        source = [[""], ["", "PI aprovado?"]]
        destination = [["", "PI aprovado?", "", "", "", "", "", True]]
        src = {"properties": {"sheetId": 1, "gridProperties": {}}, "data": [{"rowData": []}]}
        dst = {"properties": {"sheetId": 2, "gridProperties": {"rowCount": 10, "columnCount": 10}}}
        requests = model.planejar_aba("Simulador", src, source, dst, destination, {1: 2})
        restored = [r for r in requests if "updateCells" in r and
                    r["updateCells"]["range"].get("startColumnIndex") == 7]
        self.assertEqual(restored[-1]["updateCells"]["range"]["startRowIndex"], 1)
        self.assertTrue(restored[-1]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]["boolValue"])

    def test_sheet_ids_are_remapped_inside_charts_and_ranges(self):
        value = {"ranges": [{"sheetId": 10}], "spec": {"source": {"sheetId": 11}}}
        self.assertEqual(model.remapear_sheet_ids(value, {10: 20, 11: 21}),
                         {"ranges": [{"sheetId": 20}], "spec": {"source": {"sheetId": 21}}})

    def test_plan_never_replaces_files_or_sheets(self):
        src = {"properties": {"sheetId": 1, "gridProperties": {}}, "data": [{"rowData": []}]}
        dst = {"properties": {"sheetId": 2, "gridProperties": {"rowCount": 1, "columnCount": 1}}}
        requests = model.planejar_aba("Visão Geral", src, [["Título"]], dst, [["Antigo"]], {1: 2})
        forbidden = {"addSheet", "deleteSheet", "duplicateSheet"}
        self.assertFalse(any(forbidden.intersection(request) for request in requests))

    def test_equal_dimension_sizes_are_compacted(self):
        requests = model.requests_dimensao(1, "ROWS", [{"pixelSize": 20}, {"pixelSize": 20}, {"pixelSize": 30}])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["updateDimensionProperties"]["range"]["endIndex"], 2)


if __name__ == "__main__":
    unittest.main()
