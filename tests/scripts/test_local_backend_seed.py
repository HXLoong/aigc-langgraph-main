import pytest

from scripts.local_backend_seed import validate_seed_target


@pytest.mark.parametrize('mysql,goats', [
    ('mysql+aiomysql://test@10.0.0.1/otc_goal_seed', 'http://127.0.0.1:1'),
    ('mysql+aiomysql://test@localhost/production', 'http://127.0.0.1:1'),
    ('mysql+aiomysql://test@localhost/otc_goal_seed', 'http://tstgoats.example'),
    ('mysql+aiomysql://test@localhost/otc_goal_seed', 'http://127.0.0.1:48081'),
    ('mysql+aiomysql://test@localhost/', 'http://127.0.0.1:1'),
])
def test_seed_refuses_shared_database_or_live_goats(mysql, goats):
    with pytest.raises(ValueError):
        validate_seed_target(mysql, goats)


def test_seed_accepts_only_named_local_isolation_and_inert_goats():
    validate_seed_target('mysql+aiomysql://test@127.0.0.1:13308/otc_goal_seed', 'http://127.0.0.1:1')
