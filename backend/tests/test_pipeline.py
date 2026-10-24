from inquira.engine.charts import choose_chart
from inquira.engine.context import KnowledgeItem
from inquira.engine.llm.providers import LLMConfig, LLMProvider
from inquira.engine.pipeline import PipelineInput, PipelineOutput, run_pipeline
from inquira.engine.warehouse.adapters import DemoWarehouse


class ScriptedLLM(LLMProvider):
    id = "scripted"
    label = "Scripted"
    description = ""
    default_model = "x"
    models = []

    def __init__(self, replies):
        super().__init__(LLMConfig("scripted", "x"))
        self.replies = list(replies)
        self.prompts = []

    def _complete(self, system, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _run(llm):
    wh = DemoWarehouse({})
    inp = PipelineInput(question="Orders by status", warehouse=wh, tables=wh.introspect(),
                        knowledge=[KnowledgeItem("Delivered", "metric", "status = 'delivered'")], llm=llm)
    out = PipelineOutput()
    events = list(run_pipeline(inp, out))
    return out, events


def test_happy_path_streams_all_stages():
    llm = ScriptedLLM([
        '{"sql": "SELECT order_status, COUNT(*) AS orders FROM orders GROUP BY 1 ORDER BY 2 DESC", "assumptions": []}',
        '{"answer": "Most orders are **delivered**.", "chart": {"type": "bar", "x": "order_status", "y": ["orders"]}}',
    ])
    out, events = _run(llm)
    names = [e for e, _ in events]
    assert out.status == "ok"
    assert names[-2:] == ["chart", "answer"]
    assert "sql" in names and "result" in names
    assert out.chart["type"] == "bar"
    assert out.result["rows"][0][0] == "delivered"


def test_self_repairs_after_bad_sql():
    llm = ScriptedLLM([
        '{"sql": "DELETE FROM orders"}',  # rejected by the guard
        '{"sql": "SELECT nonexistent_col FROM orders"}',  # fails in the warehouse
        '{"sql": "SELECT COUNT(*) AS n FROM orders"}',
        '{"answer": "There are **99,441** orders.", "chart": {"type": "kpi", "y": ["n"]}}',
    ])
    out, events = _run(llm)
    assert out.status == "ok", out.error
    assert any(e == "step" and d["status"] == "error" and d["id"] == "validate" for e, d in events)
    assert any(e == "step" and d["status"] == "error" and d["id"] == "execute" for e, d in events)
    assert "DELETE FROM orders" in llm.prompts[1]  # error fed back to the model
    assert out.result["rows"] == [[99441]]


def test_gives_up_cleanly():
    llm = ScriptedLLM(['{"sql": "DROP TABLE orders"}'] * 3)
    out, events = _run(llm)
    assert out.status == "error"
    assert events[-1][0] == "error"


def test_cannot_answer():
    out, events = _run(ScriptedLLM(['{"sql": null, "cannot_answer": "No weather data."}']))
    assert out.status == "error" and "weather" in out.error


def test_chart_suggestion_is_validated():
    cols = [{"name": "state", "type": "string"}, {"name": "n", "type": "number"}]
    rows = [["SP", 10], ["RJ", 5], ["MG", 3]]
    assert choose_chart({"type": "bar", "x": "state", "y": ["n"]}, cols, rows)["type"] == "bar"
    hallucinated = choose_chart({"type": "line", "x": "made_up", "y": ["also_made_up"]}, cols, rows)
    assert hallucinated["type"] == "bar" and hallucinated["x"] == "state"
