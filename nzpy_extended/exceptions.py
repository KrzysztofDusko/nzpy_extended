class Warning(Exception):
    pass


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class ConnectionClosedError(InterfaceError):
    def __init__(self, msg=None):
        super().__init__(msg if msg is not None else "connection is closed")


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


class ArrayContentNotSupportedError(NotSupportedError):
    pass


class ArrayContentNotHomogenousError(ProgrammingError):
    pass


class ArrayDimensionsNotConsistentError(ProgrammingError):
    pass
