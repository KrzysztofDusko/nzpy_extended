import asyncio
import sys
sys.path.insert(0, '.')
import nzpy_extended as nzpy


async def main():
    conn = await nzpy.connect(
        user="admin",
        password="password",
        host="192.168.0.144",
        port=5480,
        database="JUST_DATA",
    )
    try:
        cur = conn.cursor()
        await cur.execute("SELECT 1 AS id, 'test' AS name, CURRENT_TIMESTAMP AS ts")

        print("=== description ===")
        for col in cur.description:
            print(col)

        print("\n=== get_schema_table() ===")
        for col in cur.get_schema_table():
            print(col)

        print("\n=== get_column_metadata(0) ===")
        print(cur.get_column_metadata(0))
    finally:
        await conn.close()


asyncio.run(main())
