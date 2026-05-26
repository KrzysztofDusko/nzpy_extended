"""
Netezza metadata API — async catalog queries.

Provides ``ConnectionMetadataProvider`` which executes queries against
Netezza system catalog views (``_v_table``, ``_v_view``, ``_v_relation_column``,
``_v_procedure``, ``_v_schema``, etc.) and returns structured results.

Usage from a connection::

    meta = conn.meta
    tables = await meta.get_tables(schema="ADMIN")
    cols = await meta.get_columns("MY_TABLE", schema="ADMIN")

The connection **must** be connected to the target database; catalog views
are database-scoped.  Running metadata queries on ``SYSTEM`` will only
show system objects.

Column names in ``_v_*`` views vary by Netezza version; the queries here
have been tested against NPS 11.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import Connection


class ConnectionMetadataProvider:
    """Async metadata queries against a Netezza connection.

    .. attribute:: _conn

        The underlying async ``Connection``.  Set once during construction.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _query(self, sql: str) -> list[tuple[Any, ...]]:
        """Execute *sql* and return all rows as a list of tuples."""
        cur = self._conn.cursor()
        try:
            await cur.execute(sql)
            return await cur.fetchall()
        finally:
            await cur.close()

    async def _query_dicts(self, sql: str) -> list[dict[str, Any]]:
        """Execute *sql* and return rows as dicts keyed by lowercased column name."""
        cur = self._conn.cursor()
        try:
            await cur.execute(sql)
            desc = cur.description
            if desc is None:
                return []
            col_names = [d[0].lower() for d in desc]
            rows = await cur.fetchall()
            return [dict(zip(col_names, row)) for row in rows]
        finally:
            await cur.close()

    # ── schemas / databases ─────────────────────────────────────────────────

    async def get_schemas(self) -> list[str]:
        """Return all schema names in the current database."""
        rows = await self._query(
            "SELECT schema FROM _v_schema ORDER BY schema"
        )
        return [r[0] for r in rows]

    async def get_databases(self) -> list[str]:
        """Return all database names visible to the current user."""
        rows = await self._query(
            "SELECT database FROM _v_database ORDER BY database"
        )
        return [r[0] for r in rows]

    async def get_current_database(self) -> str | None:
        """Return the name of the currently connected database."""
        rows = await self._query("SELECT current_catalog")
        return rows[0][0] if rows else None

    async def get_current_schema(self) -> str | None:
        """Return the current schema search path."""
        rows = await self._query("SELECT current_schema")
        return rows[0][0] if rows else None

    # ── tables ──────────────────────────────────────────────────────────────

    async def get_tables(
        self,
        schema: str | None = None,
        table_pattern: str | None = None,
        include_system: bool = False,
    ) -> list[dict[str, Any]]:
        """List tables with owner and type information.

        :param schema:          Filter by schema name (case-sensitive).
        :param table_pattern:   LIKE pattern for table name (e.g. ``'MY%'``).
        :param include_system:  When ``False`` (default), excludes system
                                schemas and system tables.
        :returns:               List of dicts with keys: ``schema``, ``table_name``,
                                ``owner``, ``objtype``, ``objid``, ``row_count``.
        """
        conditions = ["tablename IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        if table_pattern is not None:
            conditions.append(f"tablename LIKE '{table_pattern}'")
        if not include_system:
            conditions.append(
                "schema NOT IN ('DEFINITION_SCHEMA', 'INZA', 'NZ_QUERY_HISTORY')"
            )
            conditions.append("objtype <> 'SYSTEM_TABLE'")
        where = " AND ".join(conditions)
        return await self._query_dicts(
            f"SELECT schema, tablename AS table_name, owner, "
            f"objtype, objid, reltuples AS row_count "
            f"FROM _v_table WHERE {where} ORDER BY schema, tablename"
        )

    # ── views ───────────────────────────────────────────────────────────────

    async def get_views(
        self,
        schema: str | None = None,
        view_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """List views with owner and definition.

        :param schema:        Filter by schema name.
        :param view_pattern:  LIKE pattern for view name.
        :returns:             List of dicts with keys: ``schema``, ``view_name``,
                              ``owner``, ``objid``, ``definition``.
        """
        conditions = ["viewname IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        if view_pattern is not None:
            conditions.append(f"viewname LIKE '{view_pattern}'")
        where = " AND ".join(conditions)
        return await self._query_dicts(
            f"SELECT schema, viewname AS view_name, owner, objid, definition "
            f"FROM _v_view WHERE {where} ORDER BY schema, viewname"
        )

    # ── columns ─────────────────────────────────────────────────────────────

    async def get_columns(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return column metadata for a table or view.

        :param table_name:  Table or view name (required).
        :param schema:      Schema name.  If ``None``, the search path is used.
        :returns:           List of dicts with keys: ``column_name``, ``ordinal``,
                            ``data_type``, ``nullable``, ``objid``.
        """
        parts = table_name.upper().split(".")
        if len(parts) == 2:
            schema = parts[0]
            table_name = parts[1]

        conditions = [f"name = '{table_name.upper()}'"]
        if schema is not None:
            conditions.append(f"schema = '{schema.upper()}'")
        where = " AND ".join(conditions)

        return await self._query_dicts(
            f"SELECT attname AS column_name, attnum AS ordinal, "
            f"format_type AS data_type, "
            f"CASE WHEN attnotnull THEN 'N' ELSE 'Y' END AS nullable, "
            f"objid "
            f"FROM _v_relation_column "
            f"WHERE {where} ORDER BY attnum"
        )

    # ── distribution key ────────────────────────────────────────────────────

    async def get_distribution_key(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> list[str]:
        """Return the distribution key column name(s) for a table.

        Returns an empty list if the table is distributed randomly
        (no rows in ``_v_table_dist_map`` match).

        :param table_name:  Table name.
        :param schema:      Schema name.
        """
        parts = table_name.upper().split(".")
        if len(parts) == 2:
            schema = parts[0]
            table_name = parts[1]

        conditions = [f"tablename = '{table_name.upper()}'"]
        if schema is not None:
            conditions.append(f"schema = '{schema.upper()}'")
        where = " AND ".join(conditions)

        rows = await self._query(
            f"SELECT attname "
            f"FROM _v_table_dist_map "
            f"WHERE {where} "
            f"ORDER BY distattnum"
        )
        return [r[0] for r in rows]

    # ── table sizes / storage stats ─────────────────────────────────────────

    async def get_table_sizes(
        self,
        schema: str | None = None,
        table_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return storage statistics for tables.

        Uses ``_v_table_storage_stat`` for allocated/used bytes and
        ``_v_table.reltuples`` for estimated row count.

        :param schema:          Filter by schema name.
        :param table_pattern:   LIKE pattern for table name.
        :returns:               List of dicts with keys: ``schema``, ``table_name``,
                                ``used_bytes``, ``allocated_bytes``, ``size_mb``,
                                ``skew``.
        """
        conditions = ["tablename IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        if table_pattern is not None:
            conditions.append(f"tablename LIKE '{table_pattern}'")
        where = " AND ".join(conditions)

        return await self._query_dicts(
            f"SELECT schema, tablename AS table_name, "
            f"used_bytes, allocated_bytes, "
            f"(used_bytes / 1048576)::BIGINT AS size_mb, "
            f"skew "
            f"FROM _v_table_storage_stat "
            f"WHERE {where} ORDER BY used_bytes DESC"
        )

    # ── procedures ──────────────────────────────────────────────────────────

    async def get_procedures(
        self,
        schema: str | None = None,
        proc_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """List stored procedures.

        :param schema:        Filter by schema name.
        :param proc_pattern:  LIKE pattern for procedure name.
        :returns:             List of dicts with keys: ``schema``, ``proc_name``,
                              ``owner``, ``objid``, ``signature``, ``returns``,
                              ``builtin``, ``source``.
        """
        conditions = ["procedure IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        if proc_pattern is not None:
            conditions.append(f"procedure LIKE '{proc_pattern}'")
        where = " AND ".join(conditions)

        return await self._query_dicts(
            f"SELECT schema, procedure AS proc_name, owner, objid, "
            f"proceduresignature AS signature, returns, "
            f"builtin, proceduresource AS source "
            f"FROM _v_procedure WHERE {where} ORDER BY schema, procedure"
        )

    # ── sequences ───────────────────────────────────────────────────────────

    async def get_sequences(
        self,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sequences.

        :param schema:  Filter by schema name.
        :returns:       List of dicts with keys: ``schema``, ``seq_name``,
                        ``owner``, ``objid``.
        """
        conditions = ["seqname IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        where = " AND ".join(conditions)
        return await self._query_dicts(
            f"SELECT schema, seqname AS seq_name, owner, objid "
            f"FROM _v_sequence WHERE {where} ORDER BY schema, seqname"
        )

    # ── synonyms ────────────────────────────────────────────────────────────

    async def get_synonyms(
        self,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """List synonyms.

        :param schema:  Filter by schema name.
        :returns:       List of dicts with keys: ``schema``, ``synonym_name``,
                        ``ref_database``, ``ref_schema``, ``referenced_object``,
                        ``owner``, ``objid``.
        """
        conditions = ["synonym_name IS NOT NULL"]
        if schema is not None:
            conditions.append(f"schema = '{schema}'")
        where = " AND ".join(conditions)
        return await self._query_dicts(
            f"SELECT schema, synonym_name, refdatabase AS ref_database, "
            f"refschema AS ref_schema, refobjname AS referenced_object, "
            f"owner, objid "
            f"FROM _v_synonym WHERE {where} ORDER BY schema, synonym_name"
        )

    # ── sessions ────────────────────────────────────────────────────────────

    async def get_sessions(self) -> list[dict[str, Any]]:
        """Return active database sessions."""
        return await self._query_dicts(
            "SELECT id AS session_id, username, dbname AS database_name, "
            "conntime, priority, status, type AS client_type, "
            "client_os_username "
            "FROM _v_session ORDER BY conntime DESC"
        )

    # ── users ───────────────────────────────────────────────────────────────

    async def get_users(self) -> list[dict[str, Any]]:
        """List database users."""
        return await self._query_dicts(
            "SELECT username, objid FROM _v_user ORDER BY username"
        )

    # ── groups ──────────────────────────────────────────────────────────────

    async def get_groups(self) -> list[dict[str, Any]]:
        """List database groups."""
        return await self._query_dicts(
            "SELECT groupname, objid FROM _v_group ORDER BY groupname"
        )

    # ── query history ───────────────────────────────────────────────────────

    async def get_query_history(
        self,
        limit: int = 100,
        username: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent query history entries.

        Requires the history collection to be enabled on the database.

        :param limit:     Maximum number of rows to return.
        :param username:  Optional filter by user.
        """
        conditions = ["1=1"]
        if username is not None:
            conditions.append(f"qh_user = '{username}'")
        where = " AND ".join(conditions)
        return await self._query_dicts(
            f"SELECT qh_sessionid AS session_id, qh_user AS username, "
            f"qh_database AS database_name, "
            f"qh_sql AS query_text, qh_tsubmit AS submit_time, "
            f"qh_tstart AS start_time, qh_resrows AS result_rows "
            f"FROM _v_qryhist "
            f"WHERE {where} "
            f"ORDER BY qh_tsubmit DESC LIMIT {int(limit)}"
        )

    # ── generic search ──────────────────────────────────────────────────────

    async def search_objects(
        self,
        name_pattern: str,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for objects (tables, views, procedures) by name pattern.

        :param name_pattern:  LIKE pattern to match against object name.
        :param schema:        Optional schema filter.
        :returns:             List of dicts with keys: ``object_type``,
                              ``schema``, ``object_name``, ``owner``, ``objid``.
        """
        results: list[dict[str, Any]] = []

        tables = await self.get_tables(schema=schema, table_pattern=name_pattern)
        for t in tables:
            results.append({
                "object_type": "TABLE",
                "schema": t["schema"],
                "object_name": t["table_name"],
                "owner": t.get("owner"),
                "objid": t.get("objid"),
            })

        views = await self.get_views(schema=schema, view_pattern=name_pattern)
        for v in views:
            results.append({
                "object_type": "VIEW",
                "schema": v["schema"],
                "object_name": v["view_name"],
                "owner": v.get("owner"),
                "objid": v.get("objid"),
            })

        procs = await self.get_procedures(schema=schema, proc_pattern=name_pattern)
        for p in procs:
            results.append({
                "object_type": "PROCEDURE",
                "schema": p["schema"],
                "object_name": p["proc_name"],
                "owner": p.get("owner"),
                "objid": p.get("objid"),
            })

        return results
