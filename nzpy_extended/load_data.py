async def load_data(conn, table_name, rows, columns=None,
                    delimiter='|', encoding='LATIN9',
                    create_if_missing=True, temporary=False,
                    distribute_on_random=True, logdir=None,
                    escape_char='\\', quoting=None):
    return await conn.load_data(
        table_name=table_name,
        rows=rows,
        columns=columns,
        delimiter=delimiter,
        encoding=encoding,
        create_if_missing=create_if_missing,
        temporary=temporary,
        distribute_on_random=distribute_on_random,
        logdir=logdir,
        escape_char=escape_char,
        quoting=quoting,
    )
