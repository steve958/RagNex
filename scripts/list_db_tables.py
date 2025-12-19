import asyncio
from dotenv import dotenv_values
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    env = dotenv_values(".env")
    url = env["DATABASE_URL"]
    eng = create_async_engine(url)

    async with eng.connect() as conn:
        res = await conn.execute(sa.text(
            "select tablename from pg_tables where schemaname='public' order by tablename"
        ))
        print([r[0] for r in res.fetchall()])

    await eng.dispose()

asyncio.run(main())
