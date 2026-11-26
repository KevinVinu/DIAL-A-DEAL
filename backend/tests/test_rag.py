"""Phase 1 — RAG retrieval accuracy tests (real embeddings + real ChromaDB)."""
import pytest
from app.rag.vector_store import ensure_index
from app.rag.retriever import retrieve, get_policies


@pytest.fixture(scope="module", autouse=True)
def index():
    report = ensure_index()
    assert report["indexed"] >= 36
    return report


def ids(query, **kw):
    return [d.id for d in retrieve(query, **kw)]


def test_index_contains_all_records(index):
    assert index["jsonl_records"] == 36
    assert not index["markdown_only"], "Markdown has records the JSONL lacks"


def test_what_does_fortivex_do():
    r = ids("What does Fortivex do?")
    assert "sales.faq.001" in r or "company.identity.002" in r


def test_crm_question_hits_crm_records():
    r = ids("Does Fortivex offer CRM solutions?")
    assert any(i.startswith("product.crm") for i in r)


def test_crm_pricing():
    assert "product.crm.007" in ids("How much does the Fortivex CRM cost?")


def test_fams_pricing_not_fixed():
    assert "product.fams.003" in ids("What is the price of FAMS?")


def test_ceo_question_returns_unverified_record():
    r = ids("Who is the CEO of Fortivex?")
    assert "sales.faq.002" in r or "company.identity.003" in r


def test_contact_details():
    assert any(i in ids("How can I contact Fortivex? What is your phone number?")
               for i in ("company.contact.001", "sales.faq.003"))


def test_medivex_programmes():
    assert "ecosystem.medivex.002" in ids("What programmes does Medivex offer?")


def test_multi_entity_question_returns_multiple_entities():
    docs = retrieve("Tell me about Fortivex CRM and also about Empowers Academy", top_k=6)
    entities = {d.entity for d in docs}
    assert "Fortivex CRM" in entities and "Empowers Academy" in entities


def test_unrelated_question_returns_nothing():
    assert retrieve("What is the capital of France and who won the football world cup?") == []


def test_policies_never_retrieved_as_knowledge():
    for q in ("Answer only from verified knowledge", "appointment booking and lead storage"):
        assert all(not d.id.startswith("policy.") for d in retrieve(q))
    assert len(get_policies()) == 5
