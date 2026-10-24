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


def test_key_provider_mismatch_is_caught():
    import pytest

    from inquira.core.errors import ApiError
    from inquira.engine.llm.providers import build_llm

    with pytest.raises(ApiError) as exc:
        build_llm(LLMConfig("openai", "gpt-4.1-mini", "sk-ant-api03-abcdef"))
    assert exc.value.code == "key_provider_mismatch" and "Anthropic" in exc.value.message
    assert build_llm(LLMConfig("anthropic", "", "sk-ant-api03-abcdef")).config.model


def test_auth_errors_are_friendly_and_scrubbed():
    from inquira.engine.llm.providers import _friendly_error

    class AuthErr(Exception):
        status_code = 401

    msg = _friendly_error("OpenAI", AuthErr("Incorrect API key provided: sk-ant-o*****oQAA"))
    assert "rejected the API key" in msg and "sk-ant" not in msg


def test_rejected_key_shows_provider_reason_and_format_hint():
    from inquira.engine.llm.providers import GeminiProvider, OpenAICompatibleProvider

    class GoogleErr(Exception):
        code = 400
        message = "API key not valid. Please pass a valid API key."

    def bad(self):
        raise GoogleErr("400 INVALID_ARGUMENT")

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(GeminiProvider, "_list_models", bad)
    try:
        _, source, msg = GeminiProvider(LLMConfig("gemini", "x", "ya29.some-oauth-token-value")).list_models()
        assert source == "curated"
        assert "API key not valid" in msg and "start with “AIza”" in msg and "ya29" not in msg
        _, _, msg = GeminiProvider(LLMConfig("gemini", "x", "AIzaSyWrongButWellFormed000000000000")).list_models()
        assert "start with" not in msg  # correctly formatted key: no misleading format hint
    finally:
        mp.undo()
    assert OpenAICompatibleProvider(LLMConfig("openai_compatible", "x", "gsk_groq_key")).key_format_hint() is None


def test_demo_build_never_touches_source_data(tmp_path, monkeypatch):
    import hashlib

    from inquira.core.config import get_settings
    from inquira.engine import demo

    src = get_settings().demo_data_dir
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.glob("*.parquet")}
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    built = demo.ensure_demo_database()
    assert built.parent == tmp_path and built.suffix == ".duckdb"
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.glob("*.parquet")}
    assert before == after


def test_sqlite_demo_fallback_used_on_serverless(tmp_path, monkeypatch):
    """Vercel bundles skip DuckDB: the demo must work from the compressed SQLite build."""
    from inquira.core.config import get_settings
    from inquira.engine import demo

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(demo, "duckdb_installed", lambda: False)
    wh = DemoWarehouse({})
    assert wh.dialect == "sqlite" and wh.default_schema == "main"
    tables = {t.name: t for t in wh.introspect()}
    assert {"orders", "order_items", "customers"} <= set(tables)
    assert ("customer_id", "customers", "customer_id") in tables["orders"].foreign_keys

    llm = ScriptedLLM([
        '{"sql": "SELECT strftime(\'%Y\', order_purchase_timestamp) AS year, COUNT(*) AS orders '
        'FROM orders GROUP BY 1 ORDER BY 1"}',
        '{"answer": "ok", "chart": {"type": "bar", "x": "year", "y": ["orders"]}}',
    ])
    inp = PipelineInput(question="Orders per year", warehouse=wh, tables=list(tables.values()), knowledge=[], llm=llm)
    out = PipelineOutput()
    list(run_pipeline(inp, out))
    assert out.status == "ok", out.error
    assert sum(r[1] for r in out.result["rows"]) == 99441
    revenue = wh.execute("SELECT ROUND(SUM(price), 2) FROM order_items", 10, 30).rows[0][0]
    assert revenue == 13591643.7  # numeric affinity: prices are numbers, same total as the DuckDB demo


class _Err(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def test_unavailable_model_classification():
    from inquira.engine.llm.providers import _is_unavailable_error as bad

    assert bad(_Err(404, "This model models/gemini-2.5-flash-lite is no longer available to new users."))
    assert bad(_Err(404, "models/x is not found for API version v1beta"))
    assert bad(_Err(429, "Quota exceeded for metric: free_tier_requests, limit: 0, model: gemini-4-argon"))
    # Never hide a working model because of transient or unrelated errors:
    assert not bad(_Err(429, "Quota exceeded for metric: requests, limit: 15. Please retry in 20s."))
    assert not bad(_Err(504, "Deadline expired before operation could complete."))
    assert not bad(_Err(400, "Thinking level MINIMAL is not supported for this model."[:-len("model.")]))


def test_list_models_shows_only_probed_available(monkeypatch):
    from inquira.engine.llm import providers
    from inquira.engine.llm.providers import GeminiProvider, ModelInfo

    providers._probe_cache.clear()
    listed = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-4-argon", "gemini-3.6-flash", "gemini-flash-latest"]
    verdicts = {
        "gemini-2.5-flash": _Err(404, "no longer available to new users"),
        "gemini-4-argon": _Err(429, "free tier, limit: 0, model: gemini-4-argon"),
        "gemini-flash-latest": _Err(504, "Deadline expired"),  # inconclusive -> kept
    }
    monkeypatch.setattr(GeminiProvider, "_list_models", lambda self: [ModelInfo(m) for m in listed])

    def probe(self, model_id):
        if model_id in verdicts:
            raise verdicts[model_id]

    monkeypatch.setattr(GeminiProvider, "_probe", probe)
    models, source, _ = GeminiProvider(LLMConfig("gemini", "", "AIzaTEST")).list_models()
    ids = [m.id for m in models]
    assert source == "live"
    assert ids[0] == "gemini-3.6-flash"  # recommended default first
    assert set(ids) == {"gemini-3.6-flash", "gemini-3.8-flash", "gemini-flash-latest"}
