import sqlite3
import pytest

flask = pytest.importorskip('flask')

def test_home_sql_query(tmp_path, monkeypatch):
    db = tmp_path / 'test.db'
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute('CREATE TABLE t (id INTEGER)')
    cur.execute('INSERT INTO t (id) VALUES (1)')
    con.commit()
    con.close()
    monkeypatch.setenv('DB_PATH', str(db))
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    resp = client.post('/', data={'action': 'query', 'sql': 'SELECT id FROM t'})
    text = resp.get_data(as_text=True)
    assert '1' in text
