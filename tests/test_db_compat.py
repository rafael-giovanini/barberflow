import unittest

from db_compat import adapt_sql_for_postgresql


class PostgreSQLSqlCompatibilityTests(unittest.TestCase):
    def test_translates_sqlite_constructs_only_outside_literals_and_comments(self):
        sql = """
            -- BEGIN IMMEDIATE and date('now', 'localtime') in a comment
            SELECT '?' AS literal,
                   'BEGIN IMMEDIATE' AS note,
                   'date(''now'', ''localtime'')' AS date_text,
                   name COLLATE NOCASE
            FROM services
            /* COLLATE NOCASE and ? must remain in this comment */
            WHERE description = ? AND created_at = date('now', 'localtime')
        """

        adapted = adapt_sql_for_postgresql(sql)

        self.assertIn("SELECT '?' AS literal", adapted)
        self.assertIn("'BEGIN IMMEDIATE' AS note", adapted)
        self.assertIn("'date(''now'', ''localtime'')' AS date_text", adapted)
        self.assertIn("LOWER(name)", adapted)
        self.assertIn("description = %s", adapted)
        self.assertIn("created_at = CURRENT_DATE::text", adapted)
        self.assertIn("BEGIN IMMEDIATE and date('now', 'localtime') in a comment", adapted)
        self.assertIn("COLLATE NOCASE and ? must remain in this comment", adapted)
        self.assertNotIn("description = ?", adapted)

    def test_translates_begin_immediate_and_does_not_touch_dollar_quoted_body(self):
        sql = "BEGIN IMMEDIATE; SELECT $$BEGIN IMMEDIATE ? COLLATE NOCASE$$, ?"

        self.assertEqual(
            adapt_sql_for_postgresql(sql),
            "BEGIN; SELECT $$BEGIN IMMEDIATE ? COLLATE NOCASE$$, %s",
        )


if __name__ == "__main__":
    unittest.main()
