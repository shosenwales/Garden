import unittest
from tools.query_converter import QueryConverter, QueryLanguage, SPLQuery, SearchTerm, TimeRange

class TestQueryConverter(unittest.TestCase):
    def setUp(self):
        self.converter = QueryConverter()

    def test_parse_spl_basic_search(self):
        query = "error"
        result = self.converter._parse_spl(query)
        self.assertIsInstance(result, SPLQuery)
        self.assertEqual(len(result.search_terms), 1)
        self.assertEqual(result.search_terms[0], "error")

    def test_parse_spl_with_field(self):
        query = "status=404"
        result = self.converter._parse_spl(query)
        self.assertIsInstance(result, SPLQuery)
        self.assertEqual(len(result.search_terms), 1)
        self.assertIsInstance(result.search_terms[0], SearchTerm)
        self.assertEqual(result.search_terms[0].field, "status")
        self.assertEqual(result.search_terms[0].value, "404")

    def test_parse_spl_with_time_range(self):
        query = "earliest=-1d latest=now error"
        result = self.converter._parse_spl(query)
        self.assertIsInstance(result, SPLQuery)
        self.assertEqual(result.time_range.earliest, "-1d")
        self.assertEqual(result.time_range.latest, "now")
        self.assertEqual(len(result.search_terms), 1)
        self.assertEqual(result.search_terms[0], "error")

    def test_parse_spl_with_commands(self):
        query = "error | stats count by status | table status count"
        result = self.converter._parse_spl(query)
        self.assertIsInstance(result, SPLQuery)
        self.assertEqual(len(result.commands), 2)
        self.assertEqual(result.commands[0]['name'], "stats")
        self.assertEqual(result.commands[0]['args'], ["count", "by", "status"])
        self.assertEqual(result.commands[1]['name'], "table")
        self.assertEqual(result.commands[1]['args'], ["status", "count"])

    def test_parse_spl_complex_query(self):
        query = "earliest=-1h latest=now status=404 OR status=500 | stats count by status | table status count"
        result = self.converter._parse_spl(query)
        self.assertIsInstance(result, SPLQuery)
        self.assertEqual(result.time_range.earliest, "-1h")
        self.assertEqual(result.time_range.latest, "now")
        self.assertTrue(any(isinstance(term, SearchTerm) and term.field == "status" and term.value == "404" 
                          for term in result.search_terms))
        self.assertTrue(any(isinstance(term, SearchTerm) and term.field == "status" and term.value == "500" 
                          for term in result.search_terms))
        self.assertEqual(len(result.commands), 2)

    def test_convert_to_all_languages(self):
        query = "error status=404"
        results = self.converter.convert_to_all_languages(query, QueryLanguage.SPL)
        self.assertIsInstance(results, dict)
        self.assertIn("leql", results)
        self.assertIn("wql", results)
        # Since we haven't implemented the actual conversions yet,
        # we expect placeholder values
        self.assertEqual(results["leql"], "LEQL query placeholder")
        self.assertEqual(results["wql"], "WQL query placeholder")

if __name__ == '__main__':
    unittest.main() 