from struct import Struct

from .utils import i_pack

# Message codes
NOTICE_RESPONSE = b"N"
AUTHENTICATION_REQUEST = b"R"
PARAMETER_STATUS = b"S"
BACKEND_KEY_DATA = b"K"
READY_FOR_QUERY = b"Z"
ROW_DESCRIPTION = b"T"
ERROR_RESPONSE = b"E"
DATA_ROW = b"D"
COMMAND_COMPLETE = b"C"
PARSE_COMPLETE = b"1"
BIND_COMPLETE = b"2"
CLOSE_COMPLETE = b"3"
PORTAL_SUSPENDED = b"s"
NO_DATA = b"n"
PARAMETER_DESCRIPTION = b"t"
NOTIFICATION_RESPONSE = b"A"
COPY_DONE = b"c"
COPY_DATA = b"d"
COPY_IN_RESPONSE = b"G"
COPY_OUT_RESPONSE = b"H"
EMPTY_QUERY_RESPONSE = b"I"

BIND = b"B"
PARSE = b"P"
EXECUTE = b"E"
FLUSH = b'H'
SYNC = b'S'
PASSWORD = b'p'
DESCRIBE = b'D'
TERMINATE = b'X'
CLOSE = b'C'


def create_message(code, data=b''):
    return code + i_pack(len(data) + 4) + data


FLUSH_MSG = create_message(FLUSH)
SYNC_MSG = create_message(SYNC)
TERMINATE_MSG = create_message(TERMINATE)
COPY_DONE_MSG = create_message(COPY_DONE)
EXECUTE_MSG = create_message(EXECUTE, b'\x00' + i_pack(0))

# DESCRIBE constants
STATEMENT = b'S'
PORTAL = b'P'

# ErrorResponse codes
RESPONSE_SEVERITY = "V"
RESPONSE_CODE = "C"
RESPONSE_MSG = "M"
RESPONSE_DETAIL = "D"
RESPONSE_HINT = "H"
RESPONSE_POSITION = "P"
RESPONSE__POSITION = "p"
RESPONSE__QUERY = "q"
RESPONSE_WHERE = "W"
RESPONSE_FILE = "F"
RESPONSE_LINE = "L"
RESPONSE_ROUTINE = "R"

IDLE = b"I"
IDLE_IN_TRANSACTION = b"T"
IDLE_IN_FAILED_TRANSACTION = b"E"

TYPE_MOD_OFFSET = 16

NULL = i_pack(-1)
NULL_BYTE = b'\x00'

# External table stuff
EXTAB_SOCK_DATA = 1
EXTAB_SOCK_ERROR = 2
EXTAB_SOCK_DONE = 3
EXTAB_SOCK_FLUSH = 4

EXTERNAL_TABLE_STREAM_MARKER = '__nzpy_stream__'

# Connection status
CONN_NOT_CONNECTED = 0
CONN_CONNECTED = 1
CONN_EXECUTING = 2
CONN_FETCHING = 3
CONN_CANCELLED = 4

# NZ datatype
NzTypeRecAddr = 1
NzTypeDouble = 2
NzTypeInt = 3
NzTypeFloat = 4
NzTypeMoney = 5
NzTypeDate = 6
NzTypeNumeric = 7
NzTypeTime = 8
NzTypeTimestamp = 9
NzTypeInterval = 10
NzTypeTimeTz = 11
NzTypeBool = 12
NzTypeInt1 = 13
NzTypeChar = 15
NzTypeVarChar = 16
NzDEPR_Text = 17
NzTypeUnknown = 18
NzTypeInt2 = 19
NzTypeInt8 = 20
NzTypeVarFixedChar = 21
NzTypeGeometry = 22
NzTypeVarBinary = 23
NzDEPR_Blob = 24
NzTypeNChar = 25
NzTypeNVarChar = 26
NzDEPR_NText = 27
NzTypeJson = 30
NzTypeJsonb = 31
NzTypeJsonpath = 32
NzTypeVector = 33
NzTypeLastEntry = 34

nzpy_extended_client_version = "Release 11.3.1.3"

dataType = {
    NzTypeChar: "NzTypeChar",
    NzTypeVarChar: "NzTypeVarChar",
    NzTypeVarFixedChar: "NzTypeVarFixedChar",
    NzTypeGeometry: "NzTypeGeometry",
    NzTypeVarBinary: "NzTypeVarBinary",
    NzTypeNChar: "NzTypeNChar",
    NzTypeNVarChar: "NzTypeNVarChar",
    NzTypeJson: "NzTypeJson",
    NzTypeJsonb: "NzTypeJsonb",
    NzTypeJsonpath: "NzTypeJsonpath",
    NzTypeVector: "NzTypeVector",
}
