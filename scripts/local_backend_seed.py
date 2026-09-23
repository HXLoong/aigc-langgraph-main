"""导入仅用于本地 GOATS 失败边界验收的合成身份与证券种子。"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlsplit

import aiomysql
from pymysql.constants import CLIENT

logger = logging.getLogger(__name__)
SEED = Path(__file__).resolve().parents[1] / 'tests/fixtures/local_backend/identity_seed.sql'


def validate_seed_target(mysql_uri: str, goats_base_url: str) -> None:
    database = urlsplit(mysql_uri)
    goats = urlsplit(goats_base_url)
    if (database.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or not database.path.lstrip('/').startswith(('otc_goal_', 'local_eval_'))):
        raise ValueError('种子仅允许写入本机 otc_goal_ / local_eval_ 前缀隔离库')
    if (goats.scheme != 'http' or goats.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or goats.port != 1):
        raise ValueError('合成种子仅用于 GOATS_BASE_URL 指向本机不可达端口 1 的验收')


async def run(*, apply: bool) -> None:
    from app.config import get_settings
    from app.storage.mysql import connection_args

    settings = get_settings()
    validate_seed_target(settings.mysql_uri, settings.goats_base_url)
    if not apply:
        logger.info('待导入：合成群/成员/用户配置/授权各 1 行，公共证券 2 行；使用 --apply 执行')
        return
    connection = await aiomysql.connect(
        **connection_args(settings.mysql_uri), autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS,
    )
    try:
        counts = {}
        async with connection.cursor() as cursor:
            await cursor.execute(SEED.read_text())
            while True:
                if cursor.description:
                    for table, count, expected in await cursor.fetchall():
                        if count != expected:
                            raise ValueError(f'本地种子校验失败，可能存在 ID 冲突：{table}')
                        counts[table] = count
                if not await cursor.nextset():
                    break
        if len(counts) != 5:
            raise ValueError('本地种子校验结果不完整')
        await connection.commit()
        logger.info('合成种子导入并校验完成：%s', counts)
    except BaseException:
        await connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    asyncio.run(run(apply=args.apply))


if __name__ == '__main__':
    main()
