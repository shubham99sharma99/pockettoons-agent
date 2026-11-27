import pytest

from agent import db

pytestmark = pytest.mark.needs_db


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM sessions",
    "WITH m AS (SELECT date_trunc('month', date) AS m, count(DISTINCT user_id) AS mau FROM sessions GROUP BY 1) SELECT * FROM m",
    "select * from analytics.users limit 3;",
    "SELECT a.user_id FROM users a JOIN sessions b USING (user_id) LIMIT 1",
    "SELECT 1 UNION ALL SELECT 2",
])
def test_allows_selects(sql):
    assert db.check_sql(sql)


@pytest.mark.parametrize("sql,msg", [
    ("DROP TABLE users", "SELECT"),
    ("DELETE FROM users", "SELECT"),
    ("INSERT INTO users VALUES (1)", "SELECT"),
    ("SELECT 1; SELECT 2", "one statement"),
    ("SELECT * FROM raw.users", "schema"),
    ("SELECT * FROM read_csv('/etc/passwd')", "functions"),
    ("SELECT * FROM 'data.parquet'", "Unknown table"),
    ("SELECT * FROM information_schema.tables", "schema"),
    ("SELECT * FROM secret_table", "Unknown table"),
    ("ATTACH 'x.db'", "SELECT"),
    ("PRAGMA database_list", "SELECT"),
    ("COPY users TO 'out.csv'", "SELECT"),
    ("", "Empty"),
])
def test_rejects(sql, msg):
    with pytest.raises(db.SQLGuardError, match=msg):
        db.check_sql(sql)


def test_row_cap_and_true_count():
    r = db.execute("SELECT session_id FROM sessions", max_rows=50)
    assert len(r.rows) == 50 and r.truncated and r.row_count > 1000


def test_db_errors_are_returned_not_raised():
    r = db.execute("SELECT no_such_column FROM users")
    assert r.error and "no_such_column" in r.error


def test_timeout_interrupts():
    r = db.execute("SELECT count(*) FROM content_views a, content_views b", timeout_s=0.5)
    assert r.error and "timed out" in r.error


def test_external_access_disabled_even_for_trusted_helper():
    with pytest.raises(Exception):
        db.query_df("SELECT * FROM read_csv('/etc/passwd')")


def test_connection_is_read_only():
    with pytest.raises(Exception):
        db.query_df("CREATE TABLE analytics.hack AS SELECT 1")
