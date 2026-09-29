"""按产品图的公共出口完成参数节点测试，所有清洗与 HTTP 代码均真实执行。"""
from importlib import import_module

from app.extraction.fields import merge_fields
from app.graph.state import merge_by_id
from app.subgraphs.request_boundary import after_clean, after_prepare


async def run_request_nodes(prepare, state, product):
    """独立参数节点与真实清洗/提交节点组合，外部依赖仍由各测试自行替换。"""
    current = dict(state)

    def merge(update):
        """沿用 State 的账本与 Trace reducer，不屏蔽校验或注入业务结果。"""
        records = merge_fields(current.get("field_records"), update.get("field_records"))
        trace = merge_by_id(current.get("trace"), update.get("trace"))
        current.update(update)
        current.update(field_records=records, trace=trace)

    merge(await prepare(current))
    if after_prepare(current) == "clean":
        backend = import_module(f"app.subgraphs.{product}.backend")
        merge(await getattr(backend, f"{product}_clean_request")(current))
        route = after_clean(current)
        if route != "done":
            suffix = "query_backend" if route == "query" else "submit"
            merge(await getattr(backend, f"{product}_{suffix}")(current))
    return current
