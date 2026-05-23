import asyncio
from collections import deque
from warnings import warn

from .exceptions import (ConnectionClosedError, InterfaceError,
                         OperationalError, ProgrammingError)


class Cursor():
    __module__ = 'nzpy_extended.core'

    def __init__(self, connection):
        self._c = connection
        self.arraysize = 1
        self.ps = None
        self._row_count = -1
        self._cached_rows = deque()
        self.notices = deque()
        self._generator = None
        self._has_rows = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    @property
    def connection(self):
        warn("DB-API extension cursor.connection used", stacklevel=3)
        return self._c

    @property
    def rowcount(self):
        return self._row_count

    description = property(lambda self: self._getDescription())

    @property
    def has_rows(self):
        return self._has_rows

    def _getDescription(self):
        if self.ps is None:
            return None
        row_desc = self.ps['row_desc']
        if len(row_desc) == 0:
            return None
        tupdesc = self.ps.get('tupdesc')
        columns = []
        for i, col in enumerate(row_desc):
            meta = self._c._resolve_column_metadata(col, i, tupdesc) if self._c else None
            if meta is None:
                columns.append((col["name"].decode(), col["type_oid"],
                                None, None, None, None, None))
            else:
                columns.append((
                    meta['name'],
                    meta['provider_type'],
                    meta['display_size'],
                    meta['internal_size'],
                    meta['numeric_precision'] if meta['numeric_precision'] >= 0 else None,
                    meta['numeric_scale'] if meta['numeric_scale'] >= 0 else None,
                    meta['null_ok'],
                ))
        return tuple(columns)

    def get_schema_table(self):
        if self.ps is None:
            return []
        row_desc = self.ps['row_desc']
        if len(row_desc) == 0:
            return []
        tupdesc = self.ps.get('tupdesc')
        rows = []
        for i, col in enumerate(row_desc):
            meta = self._c._resolve_column_metadata(col, i, tupdesc) if self._c else None
            if meta is None:
                continue
            rows.append({
                'ColumnName': meta['name'],
                'ColumnOrdinal': i + 1,
                'ColumnSize': meta['column_size'],
                'NumericPrecision': meta['numeric_precision'],
                'NumericScale': meta['numeric_scale'],
                'DataType': meta['data_type'],
                'ProviderType': meta['provider_type'],
                'AllowDBNull': meta['null_ok'],
                'IsReadOnly': True,
                'IsLong': meta['is_long'],
                'IsAutoIncrement': False,
            })
        return rows

    def get_column_metadata(self, index):
        if self.ps is None or index < 0 or index >= len(self.ps['row_desc']):
            raise ProgrammingError(f"Column ordinal {index} is out of range")
        col = self.ps['row_desc'][index]
        tupdesc = self.ps.get('tupdesc')
        if self._c is None:
            raise ProgrammingError("Cursor closed")
        return self._c._resolve_column_metadata(col, index, tupdesc)

    async def execute(self, operation, args=None, stream=None, timeout=None):
        try:
            self.stream = stream
            self._timeout = timeout
            await self.clear()

            if self._c is not None and not self._c.in_transaction and not self._c.autocommit:
                await self._c.execute(self, "begin", None)
                self._c.in_transaction = True

            if self._c is not None:
                exec_gen = self._c._command_generation + 1
                self._exec_gen = exec_gen
                coro = self._c.execute(self, operation, args)
                if timeout is not None and timeout > 0:
                    try:
                        await asyncio.wait_for(coro, timeout=timeout)
                    except asyncio.TimeoutError:
                        await self._c.cancel(exec_gen=exec_gen)
                        raise OperationalError("Command execution timeout")
                else:
                    await coro

        except AttributeError as e:
            if self._c is None:
                raise InterfaceError("Cursor closed")
            elif self._c._sock is None:
                raise ConnectionClosedError()
            else:
                raise e
        return self

    async def executemany(self, operation, param_sets):
        await self.clear()
        rowcounts = []
        for parameters in param_sets:
            await self.execute(operation, parameters)
            rowcounts.append(self._row_count)

        self._row_count = -1 if -1 in rowcounts else sum(rowcounts)
        return self

    async def fetchone(self):
        try:
            return await self.__anext__()
        except StopAsyncIteration:
            return None
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")
        except AttributeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def fetchmany(self, num=None):
        try:
            rows = []
            for _ in range(self.arraysize if num is None else num):
                try:
                    rows.append(await self.__anext__())
                except StopAsyncIteration:
                    break
            return tuple(rows)
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def fetchall(self):
        try:
            generator = getattr(self, '_generator', None)
            if generator is None:
                if self.ps is None:
                    raise ProgrammingError("A query hasn't been issued.")
                elif len(self.ps['row_desc']) == 0:
                    raise ProgrammingError("no result set")
                return []
            rows = list(self._cached_rows)
            self._cached_rows.clear()
            async for state in generator:
                if state in ("DATA_ROW", "DATA_BATCH"):
                    rows.extend(self._cached_rows)
                    self._cached_rows.clear()
                elif state == "COMMAND_COMPLETE":
                    self._has_rows = len(rows) > 0
                    continue
                elif state in ("ROW_DESCRIPTION", "DESCRIPTION", "DBOS_COLUMN_DESCRIPTION"):
                    self._has_rows = (
                        len(self._cached_rows) > 0 or
                        (self.ps is not None and len(self.ps.get('row_desc', [])) > 0)
                    )
                    self._generator = generator
                    return rows
                elif state == "READY_FOR_QUERY":
                    self._generator = None
                    return rows
                elif state == "ERROR":
                    err = self._c.error if self._c is not None else None
                    if self._c is not None:
                        await self._c._drain_protocol_generator(generator)
                    self._generator = None
                    if err is not None:
                        raise ProgrammingError(err)
                    return rows
            self._generator = None
            return rows
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def close(self):
        generator = getattr(self, '_generator', None)
        if generator is not None:
            if self._c is not None:
                await self._c._drain_protocol_generator(generator)
            self._generator = None
        self._c = None

    def __aiter__(self):
        return self

    def setinputsizes(self, sizes):
        pass

    def setoutputsize(self, size, column=None):
        pass

    async def __anext__(self):
        if getattr(self, '_timeout', None) is not None and self._timeout > 0:
            try:
                return await asyncio.wait_for(self._anext_internal(), timeout=self._timeout)
            except asyncio.TimeoutError:
                if self._c is not None:
                    await self._c.cancel(exec_gen=getattr(self, '_exec_gen', None))
                raise OperationalError("Command fetch timeout")
        else:
            return await self._anext_internal()

    async def _anext_internal(self):
        try:
            return self._cached_rows.popleft()
        except IndexError:
            generator = getattr(self, '_generator', None)
            if generator is not None:
                while True:
                    try:
                        state = await generator.__anext__()
                    except StopAsyncIteration:
                        break
                    if state in ("DATA_ROW", "DATA_BATCH"):
                        if len(self._cached_rows) > 0:
                            return self._cached_rows.popleft()
                    elif state == "COMMAND_COMPLETE":
                        if not self._cached_rows:
                            raise StopAsyncIteration()
                        continue
                    elif state == "READY_FOR_QUERY":
                        self._generator = None
                        raise StopAsyncIteration()
                    elif state == "ERROR":
                        err = self._c.error if self._c is not None else None
                        if self._c is not None:
                            await self._c._drain_protocol_generator(generator)
                        self._generator = None
                        if err is not None:
                            raise ProgrammingError(err)
                        raise StopAsyncIteration()
                self._generator = None
                raise StopAsyncIteration()

            if self.ps is None:
                raise ProgrammingError("A query hasn't been issued.")
            elif len(self.ps['row_desc']) == 0:
                raise ProgrammingError("no result set")
            else:
                raise StopAsyncIteration()

    async def clear(self):
        generator = getattr(self, '_generator', None)
        if generator is not None:
            if self._c is not None:
                await self._c._drain_protocol_generator(generator)
            else:
                async for state in generator:
                    pass
            self._generator = None

        self.ps = None
        self._row_count = -1
        self._has_rows = False
        self._cached_rows.clear()

    async def nextset(self):
        self._cached_rows.clear()

        generator = getattr(self, '_generator', None)
        if generator is None:
            return None

        while True:
            try:
                state = await generator.__anext__()
            except StopAsyncIteration:
                self._generator = None
                return None

            if state in ("ROW_DESCRIPTION", "DESCRIPTION", "DBOS_COLUMN_DESCRIPTION"):
                self._has_rows = (
                    len(self._cached_rows) > 0 or
                    (self.ps is not None and len(self.ps.get('row_desc', [])) > 0)
                )
                return True
            elif state == "COMMAND_COMPLETE":
                continue
            elif state == "READY_FOR_QUERY":
                self._generator = None
                return None
            elif state == "ERROR":
                err = self._c.error if self._c is not None else None
                if self._c is not None:
                    await self._c._drain_protocol_generator(generator)
                self._generator = None
                if err is not None:
                    raise ProgrammingError(err)
                return None
            if state in ("DATA_ROW", "DATA_BATCH"):
                self._has_rows = len(self._cached_rows) > 0
                return True
