from __future__ import annotations

import asyncpg


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        statement_cache_size=0,
        command_timeout=5.0,
        server_settings={"application_name": "london-property-explorer"},
    )
