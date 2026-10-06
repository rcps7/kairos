"""Wave 6 tests: GUI split, computer-use loop, RAG reranking."""

from unittest import mock

from kairos import rerank, computer


def test_gui_split_reexports():
    import kairos.gui.main_window as m
    for name in ("KairosGUI", "TelegramDialog", "CharacterDialog", "CollaborationWindow",
                 "AgentSettingsDialog", "LLMWorker", "MessageBubble"):
        assert hasattr(m, name), f"main_window missing {name}"


def test_rerank_lexical():
    items = [{"text": "cats and dogs"}, {"text": "quantum physics research"},
             {"text": "dog training tips"}]
    out = rerank.rerank("dog training", items, top_k=2, embed_fn=None)
    assert out[0]["text"] == "dog training tips"


def test_rerank_embeddings():
    def ef(texts):
        return [[1.0, 0.0] if "a" in t else [0.0, 1.0] for t in texts]
    out = rerank.rerank("a", [{"text": "b"}, {"text": "a"}], top_k=1, embed_fn=ef)
    assert out[0]["text"] == "a"


class _PlanEngine:
    def __init__(self):
        self.n = 0

    def ask_llm(self, prompt, system_prompt=None, use_character=True):
        self.n += 1
        if self.n == 1:
            return '```json\n{"action": "goto", "url": "http://example"}\n```'
        return '{"action": "done", "text": "the answer"}'


def test_computer_loop():
    with mock.patch.object(computer.browser, "available", return_value=True), \
         mock.patch.object(computer.browser, "fetch_text", return_value="page body"), \
         mock.patch.object(computer.browser, "run_actions", return_value="TEXT:\npage"):
        res = computer.run(_PlanEngine(), "find something", start_url="http://start", max_steps=5)
    assert res["ok"] is True and res["result"] == "the answer"
