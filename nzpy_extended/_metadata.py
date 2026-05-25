"""Column metadata resolution for result-set descriptions.

Provides ``MetadataResolver`` which maps raw PostgreSQL OID / type-modifier
information to rich DB-API ``description`` tuples (column name, data type,
precision, scale, nullability, length, etc.).

Previously these methods lived on ``Connection``.
"""

from __future__ import annotations

import datetime
from typing import Any

from .protocol import TYPE_MOD_OFFSET
from .types import (
    DbosTupleDesc,
    NZ_TYPE_NUMERIC,
    OID_BOOL,
    OID_BPCHAR,
    OID_BYTEINT,
    OID_DATE,
    OID_FLOAT4,
    OID_FLOAT8,
    OID_INT2,
    OID_INT4,
    OID_INT8,
    OID_NCHAR,
    OID_NUMERIC,
    OID_NVARCHAR,
    OID_TEXT,
    OID_TIME,
    OID_TIMESTAMP,
    OID_TIMESTAMPTZ,
    OID_TIMETZ,
    OID_VARCHAR,
)


class MetadataResolver:
    """Stateless collection of column-metadata helpers.

    Can be used as a module-level namespace; instantiation is optional.
    """

    # ----- OID-to-type-name ------------------------------------------------

    @staticmethod
    def _oid_type_name(oid: int) -> str:
        """Return a human-readable Netezza type name for *oid*."""
        names: dict[int, str] = {
            OID_BOOL: "BOOLEAN",
            OID_BYTEINT: "BYTEINT",
            OID_INT2: "SMALLINT",
            OID_INT4: "INTEGER",
            OID_INT8: "BIGINT",
            OID_NUMERIC: "NUMERIC",
            OID_FLOAT4: "REAL",
            OID_FLOAT8: "DOUBLE PRECISION",
            OID_BPCHAR: "CHAR",
            OID_VARCHAR: "VARCHAR",
            OID_TEXT: "TEXT",
            OID_DATE: "DATE",
            OID_TIME: "TIME",
            OID_TIMESTAMP: "TIMESTAMP",
            OID_TIMESTAMPTZ: "TIMESTAMPTZ",
            OID_TIMETZ: "TIMETZ",
            OID_NCHAR: "NCHAR",
            OID_NVARCHAR: "NVARCHAR",
        }
        return names.get(oid, f"UNKNOWN({oid})")

    # ----- Type-modifier helpers -------------------------------------------

    @staticmethod
    def _numeric_precision_scale_from_modifier(
        type_mod: int,
    ) -> tuple[int, int]:
        """Extract (precision, scale) from a NUMERIC type modifier."""
        if type_mod > TYPE_MOD_OFFSET:
            normalized = type_mod - TYPE_MOD_OFFSET
            return normalized >> 16, normalized & 0xFFFF
        return 0, 0

    @staticmethod
    def _character_declared_length(oid: int, type_mod: int) -> int | None:
        """Return declared character length for BPCHAR / VARCHAR / etc."""
        if oid in (OID_BPCHAR, OID_VARCHAR, OID_TEXT, OID_NCHAR, OID_NVARCHAR):
            if type_mod > TYPE_MOD_OFFSET:
                return type_mod - TYPE_MOD_OFFSET
        return None

    # ----- Python-type mapping ---------------------------------------------

    @staticmethod
    def _oid_to_python_type(oid: int) -> type:
        """Map an OID to the corresponding Python built-in type."""
        import decimal as _decimal

        mapping: dict[int, type] = {
            OID_BOOL: bool,
            OID_BYTEINT: int,
            OID_INT2: int,
            OID_INT4: int,
            OID_INT8: int,
            OID_NUMERIC: _decimal.Decimal,
            OID_FLOAT4: float,
            OID_FLOAT8: float,
            OID_BPCHAR: str,
            OID_VARCHAR: str,
            OID_TEXT: str,
            OID_DATE: datetime.date,
            OID_TIME: datetime.time,
            OID_TIMESTAMP: datetime.datetime,
            OID_TIMESTAMPTZ: datetime.datetime,
            OID_TIMETZ: str,
            OID_NCHAR: str,
            OID_NVARCHAR: str,
        }
        return mapping.get(oid, str)

    # ----- Nullability -----------------------------------------------------

    @staticmethod
    def _column_null_ok(index: int, tupdesc: DbosTupleDesc | None) -> bool:
        if tupdesc is None:
            return True
        if tupdesc.nullsAllowed is not None and tupdesc.nullsAllowed <= 0:
            return False
        if index < len(tupdesc.field_nullAllowed):
            return bool(tupdesc.field_nullAllowed[index])
        return True

    # ----- Main resolver ---------------------------------------------------

    def resolve_column_metadata(
        self,
        col: dict[str, Any],
        index: int,
        tupdesc: DbosTupleDesc | None,
    ) -> dict[str, Any]:
        """Build a rich metadata dict for one result-set column.

        This is the method that ``Cursor.description``, ``get_schema_table``,
        and ``get_column_metadata`` ultimately call.
        """
        oid = col["type_oid"]
        type_mod = col.get("type_modifier", -1)
        type_size = col.get("type_size", -1)
        name = col["name"].decode() if isinstance(col["name"], bytes) else col["name"]

        type_name = self._oid_type_name(oid)
        declared_len = self._character_declared_length(oid, type_mod)
        num_prec, num_scale = self._numeric_precision_scale_from_modifier(type_mod)

        column_size = type_size if type_size > 0 else -1

        if tupdesc is not None and index < tupdesc.numFields:  # type: ignore[operator]
            nz_type = tupdesc.field_type[index]
            if nz_type == NZ_TYPE_NUMERIC:
                num_prec = self.CTable_i_fieldPrecision(tupdesc, index)
                num_scale = self.CTable_i_fieldScale(tupdesc, index)
                if num_prec > 0:
                    column_size = max(column_size, tupdesc.field_size[index] & 0xFFFF)
            elif type_size <= 0:
                fs = tupdesc.field_size[index]
                if fs > 0:
                    column_size = fs & 0xFFFF if fs > 255 else fs

        if oid == OID_NUMERIC and num_prec == 0:
            num_prec, num_scale = self._numeric_precision_scale_from_modifier(type_mod)
            if num_prec > 0 and column_size <= 0:
                column_size = num_prec // 2 + 1

        if declared_len is not None:
            column_size = declared_len

        numeric_precision = num_prec if oid == OID_NUMERIC else -1
        numeric_scale = num_scale if oid == OID_NUMERIC else -1

        if oid == OID_FLOAT8:
            numeric_precision, numeric_scale = 53, -1
        elif oid == OID_FLOAT4:
            numeric_precision, numeric_scale = 24, -1

        data_type = self._oid_to_python_type(oid)
        declared_type_name = type_name
        if declared_len is not None:
            declared_type_name = f"{type_name}({declared_len})"
        elif oid == OID_NUMERIC and num_prec > 0:
            declared_type_name = f"NUMERIC({num_prec},{num_scale})"

        display_size = column_size if column_size > 0 else None
        internal_size = (
            type_size if type_size > 0 else column_size if column_size > 0 else None
        )

        return {
            "name": name,
            "type_name": type_name,
            "declared_type_name": declared_type_name,
            "provider_type": oid,
            "type_modifier": type_mod,
            "column_size": column_size,
            "display_size": display_size,
            "internal_size": internal_size,
            "numeric_precision": numeric_precision,
            "numeric_scale": numeric_scale,
            "data_type": data_type,
            "null_ok": self._column_null_ok(index, tupdesc),
            "is_long": column_size > 8000,
            "declared_length": declared_len,
        }

    # ----- CTable helpers --------------------------------------------------

    @staticmethod
    def CTable_i_fieldPrecision(tupdesc: DbosTupleDesc, coldex: int) -> int:
        return ((tupdesc.field_size[coldex]) >> 8) & 0x7F

    @staticmethod
    def CTable_i_fieldScale(tupdesc: DbosTupleDesc, coldex: int) -> int:
        return (tupdesc.field_size[coldex]) & 0x00FF

    @staticmethod
    def CTable_i_fieldType(tupdesc: DbosTupleDesc, coldex: int) -> int:
        return tupdesc.field_type[coldex]

    @staticmethod
    def CTable_i_fieldSize(tupdesc: DbosTupleDesc, coldex: int) -> int:
        return tupdesc.field_size[coldex]

    @staticmethod
    def CTable_i_fieldNumericDigit32Count(tupdesc: DbosTupleDesc, coldex: int) -> int:
        return tupdesc.field_trueSize[coldex] // 4


__all__ = [
    "MetadataResolver",
]
