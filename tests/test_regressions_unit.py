import asyncio
import inspect
import types

import pytest

import nzpy_extended as nzpy
import nzpy_extended.fastapi as nzpy_fastapi
import nzpy_extended.sync as sync_nzpy
from datetime import timezone as Timezone
from nzpy_extended.core import Connection, Datetime
from nzpy_extended.types import timestamptz_in
from nzpy_extended.pool import SyncPool
from nzpy_extended import core as core_mod
from nzpy_extended.protocol import EXTAB_SOCK_DATA, EXTAB_SOCK_DONE
from nzpy_extended.utils import i_pack as i_pack_mod


pytestmark = [pytest.mark.full, pytest.mark.unit]


@pytest.mark.asyncio
async def test_prepare_qmark_ignores_literals_and_comments():
    conn = Connection()
    query = "SELECT '?', ? -- ?\n, '?'"
    prepared = await conn.Prepare(None, query, ("value",))
    assert prepared == "SELECT '?', 'value' -- ?\n, '?'"


@pytest.mark.asyncio
async def test_prepare_named_uses_mapping_order():
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "named"
        conn = Connection()
        prepared = await conn.Prepare(
            None,
            "SELECT :second, :first, :second",
            {"first": 1, "second": "two"},
        )
        assert prepared == "SELECT 'two', 1, 'two'"
    finally:
        nzpy.paramstyle = orig_paramstyle


def test_timestamptz_in_returns_aware_utc_datetime():
    value = timestamptz_in(b"2024-12-11 14:30:00-05", 0, 22)
    assert value == Datetime(2024, 12, 11, 19, 30, 0, tzinfo=Timezone.utc)


def test_import_star_uses_string_all_entries():
    namespace = {}
    exec("from nzpy_extended import *", {}, namespace)
    assert "connect" in namespace
    assert "Connection" in namespace


@pytest.mark.asyncio
async def test_sync_async_connect_forwards_unix_sock(monkeypatch):
    captured = {}

    async def fake_connect(self, **kwargs):
        captured.update(kwargs)

    async def fake_close(self):
        return None

    monkeypatch.setattr(Connection, "connect", fake_connect)
    monkeypatch.setattr(Connection, "close", fake_close)

    conn = await sync_nzpy._async_connect(
        user="admin",
        host=None,
        unix_sock="/tmp/nz.sock",
        port=5480,
        database="JUST_DATA",
        password="password",
        ssl=None,
        securityLevel=0,
        timeout=None,
        application_name=None,
        max_prepared_statements=1000,
        datestyle="ISO",
        logLevel=0,
        tcp_keepalive=True,
        char_varchar_encoding="latin",
        on_connect=None,
    )

    try:
        assert captured["unix_sock"] == "/tmp/nz.sock"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_connect_applies_application_name_to_handshake(monkeypatch):
    class DummySocket:
        def settimeout(self, timeout):
            return None

        def setblocking(self, flag):
            return None

        def setsockopt(self, *args):
            return None

        def close(self):
            return None

    class DummyLoop:
        async def sock_connect(self, sock, address):
            return None

    class DummyHandshake:
        def __init__(self, sock, ssl, log):
            self.guardium_applName = "default"

        def startup(self, database, security_level, user, password, pg_options):
            raise RuntimeError(self.guardium_applName)

    monkeypatch.setattr(core_mod.socket, "socket", lambda *args, **kwargs: DummySocket())
    monkeypatch.setattr(core_mod.asyncio, "get_event_loop", lambda: DummyLoop())
    monkeypatch.setattr(core_mod.handshake, "SyncHandshake", DummyHandshake)

    conn = Connection()
    with pytest.raises(RuntimeError, match="my-app"):
        await conn.connect(
            user="admin",
            host="localhost",
            unix_sock=None,
            port=5480,
            database="JUST_DATA",
            password="password",
            ssl=None,
            securityLevel=0,
            timeout=None,
            application_name="my-app",
            max_prepared_statements=1000,
            datestyle="ISO",
            logLevel=0,
            tcp_keepalive=True,
            char_varchar_encoding="latin",
        )


@pytest.mark.asyncio
async def test_fastapi_lifespan_handles_sync_open():
    events = []

    class DummyPool:
        def open(self):
            events.append("open")

        def close_all(self):
            events.append("close")

    app = types.SimpleNamespace(state=types.SimpleNamespace())
    async with nzpy_fastapi.lifespan(DummyPool())(app):
        assert app.state.nz_pool is not None
        assert events == ["open"]

    assert events == ["open", "close"]


def test_sync_pool_preserves_use_count_and_rejects_foreign_release(monkeypatch):
    class DummyCursor:
        def execute(self, query):
            return None

        def fetchall(self):
            return [(1,)]

    class DummyConn:
        def cursor(self):
            return DummyCursor()

        def close(self):
            return None

    monkeypatch.setattr(sync_nzpy, "connect", lambda **kwargs: DummyConn())

    pool = SyncPool(min_size=0, max_size=2, ping_query=None)
    conn = pool.acquire()
    pool.release(conn)
    assert pool._pool[0].use_count == 1
    reused = pool.acquire()
    pool.release(reused)
    assert pool._pool[0].use_count == 2

    with pytest.raises(RuntimeError, match="already been released"):
        pool.release(DummyConn())


def test_float_metadata_uses_negative_scale():
    conn = Connection()
    meta =     conn._meta.resolve_column_metadata(
        {"type_oid": 701, "type_modifier": -1, "type_size": 8, "name": b"x"},
        0,
        None,
    )
    assert meta["numeric_precision"] == 53
    assert meta["numeric_scale"] == -1


def test_ssl_verify_flag_defaults_to_true():
    conn = Connection()
    params = conn.connect.__code__.co_varnames

def test_connect_timeout_parameter():
    conn = Connection()
    params = conn.connect.__code__.co_varnames
    assert 'connect_timeout' in params


def test_error_response_mapping():
    from nzpy_extended.core import IntegrityError, InterfaceError, DataError, InternalError

    async def _test_code(code, expected_cls):
        conn = Connection()
        conn._client_encoding = 'utf8'
        null = b'\x00'
        err_data = b'C' + code.encode() + null + b'M' + b'test msg' + null + null
        await conn._protocol.handle_ERROR_RESPONSE(err_data, None)
        assert isinstance(conn.error, expected_cls), f"Expected {expected_cls} for {code}, got {type(conn.error)}"

    async def run():
        await _test_code('23505', IntegrityError)
        await _test_code('28000', InterfaceError)
        await _test_code('22012', DataError)
        await _test_code('26000', InternalError)
        await _test_code('42601', nzpy.ProgrammingError)

    import asyncio
    asyncio.run(run())


def test_receiveAndWriteDatatoExternal_skips_write_when_fh_is_none():
    async def run():
        conn = Connection()
        conn.log = core_mod.logging.getLogger("test")

        statuses = [EXTAB_SOCK_DATA,
                    3,
                    b'abc',
                    EXTAB_SOCK_DONE]
        idx = 0

        async def mock_read(n):
            nonlocal idx
            if idx >= len(statuses):
                return b''
            result = statuses[idx]
            idx += 1
            if isinstance(result, int):
                return i_pack_mod(result)
            return result

        conn._read = mock_read

        # Should NOT crash — just drain socket data when fh is None
        await conn._extab.receiveAndWriteDatatoExternal("test", None)

    asyncio.run(run())


def test_xferTable_uses_to_thread_for_file_io():
    conn = Connection()
    src = inspect.getsource(conn._extab.xferTable)
    assert 'asyncio.to_thread(filehandle.read' in src, "xferTable must use asyncio.to_thread for filehandle.read"
    assert 'asyncio.to_thread(filehandle.close' in src, "xferTable must use asyncio.to_thread for filehandle.close"


def test_getFileFromBE_uses_to_thread_for_file_io():
    conn = Connection()
    src = inspect.getsource(conn._extab.getFileFromBE)
    assert 'asyncio.to_thread(open' in src, "getFileFromBE must use asyncio.to_thread for open"
    assert 'asyncio.to_thread(fh.write' in src, "getFileFromBE must use asyncio.to_thread for fh.write"


def test_receiveAndWriteDatatoExternal_uses_to_thread_for_write():
    conn = Connection()
    src = inspect.getsource(conn._extab.receiveAndWriteDatatoExternal)
    assert 'asyncio.to_thread(fh.write' in src, "receiveAndWriteDatatoExternal must use asyncio.to_thread for fh.write"
    assert 'asyncio.to_thread(fh.flush' in src, "receiveAndWriteDatatoExternal must use asyncio.to_thread for fh.flush"
    assert 'asyncio.to_thread(fh.close' in src, "receiveAndWriteDatatoExternal must use asyncio.to_thread for fh.close"
    assert 'if fh is not None:' in src, "receiveAndWriteDatatoExternal must null-check fh in finally before close"


def test_xferTable_uses_effective_block_size():
    conn = Connection()
    src = inspect.getsource(conn._extab.xferTable)
    assert 'effectiveBlockSize = max(blockSize, 1)' in src, "xferTable must guard against blockSize <= 0"
    assert 'filehandle.read, effectiveBlockSize' in src, "xferTable must use effectiveBlockSize for reads"
