import sys

import nzpy_extended as nzpy

import pytest

pytestmark = pytest.mark.full

# Check if running in Jython
if 'java' in sys.platform:
    from javax.net.ssl import TrustManager, X509TrustManager
    from jarray import array
    from javax.net.ssl import SSLContext

    class TrustAllX509TrustManager(X509TrustManager):
        '''Define a custom TrustManager which will blindly accept all
        certificates'''

        def checkClientTrusted(self, chain, auth):
            pass

        def checkServerTrusted(self, chain, auth):
            pass

        def getAcceptedIssuers(self):
            return None
    # Create a static reference to an SSLContext which will use
    # our custom TrustManager
    trust_managers = array([TrustAllX509TrustManager()], TrustManager)
    TRUST_ALL_CONTEXT = SSLContext.getInstance("SSL")
    TRUST_ALL_CONTEXT.init(None, trust_managers, None)
    # Keep a static reference to the JVM's default SSLContext for restoring
    # at a later time
    DEFAULT_CONTEXT = SSLContext.getDefault()


@pytest.fixture
def trust_all_certificates(request):
    '''Decorator function that will make it so the context of the decorated
    method will run with our TrustManager that accepts all certificates'''
    # Only do this if running under Jython
    is_java = 'java' in sys.platform

    if is_java:
        from javax.net.ssl import SSLContext
        SSLContext.setDefault(TRUST_ALL_CONTEXT)

    def fin():
        if is_java:
            SSLContext.setDefault(DEFAULT_CONTEXT)

    request.addfinalizer(fin)


@pytest.mark.asyncio
async def testSocketMissing():
    conn_params = {
        'unix_sock': "/file-does-not-exist",
        'user': "doesn't-matter",
        'database': "dummy_db"
        }

    with pytest.raises(nzpy.InterfaceError):
        await nzpy.connect(**conn_params)


@pytest.mark.asyncio
async def testDatabaseMissing(db_kwargs):
    db_kwargs["database"] = "missing-db"
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)

# This requires a line in pg_hba.conf that requires md5 for the database
# nzpy_md5


@pytest.mark.asyncio
async def testMd5(db_kwargs):
    db_kwargs["database"] = "nzpy_md5"

    # Should only raise an exception saying db doesn't exist
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)


@pytest.mark.usefixtures("trust_all_certificates")
@pytest.mark.asyncio
async def testSsl(db_kwargs):
    db_kwargs["ssl"] = True
    conn = await nzpy.connect(**db_kwargs)
    await conn.close()


@pytest.mark.asyncio
async def testUnicodeDatabaseName(db_kwargs):
    db_kwargs["database"] = "nzpy_sn\uFF6Fw"

    # Should only raise an exception saying db doesn't exist
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)


@pytest.mark.asyncio
async def testBytesPassword(con, db_kwargs):
    username = 'boltzmann'
    password = 'cha\uFF6Fs'
    cursor = con.cursor()
    try:
        await cursor.execute(
            "create user " + username + " with password '" + password + "';")
        await con.commit()
    except nzpy.ProgrammingError as e:
        if 'already exists' not in str(e):
            raise

    db_kwargs['user'] = username
    db_kwargs['password'] = password.encode('utf8')
    db_kwargs['database'] = 'nzpy_md5'
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)

    await cursor.execute("drop user " + username)
    await con.commit()


# This requires a line in pg_hba.conf that requires scram-sha-256 for the
# database scram-sha-256

@pytest.mark.asyncio
async def test_scram_sha_256(db_kwargs):
    db_kwargs["database"] = "nzpy_scram_sha_256"

    # Should only raise an exception saying db doesn't exist
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)


@pytest.mark.full
@pytest.mark.asyncio
async def test_bytes_database_name_raises(db_kwargs):
    db_kwargs = dict(db_kwargs)
    db_kwargs["database"] = bytes("nzpy_sn\uFF6Fw", "utf8")
    with pytest.raises(nzpy.ProgrammingError):
        await nzpy.connect(**db_kwargs)


@pytest.mark.skip(reason="LISTEN/NOTIFY is PostgreSQL-specific; not supported on Netezza")
@pytest.mark.full
@pytest.mark.asyncio
async def test_notify(con):
    assert list(con.notifications) == []


@pytest.mark.skip(reason="GSS/KRB5 authentication is not supported by nzpy_extended")
@pytest.mark.full
@pytest.mark.asyncio
async def test_gss(db_kwargs):
    db_kwargs = dict(db_kwargs)
    db_kwargs["database"] = "nzpy_gss"
    with pytest.raises(nzpy.InterfaceError):
        await nzpy.connect(**db_kwargs)


@pytest.mark.skip(reason="pg_terminate_backend is PostgreSQL-specific; not available on Netezza")
@pytest.mark.full
@pytest.mark.asyncio
async def test_broken_pipe(con, db_kwargs):
    pass
