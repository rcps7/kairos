"""Lightweight in-Kairos prediction fallback.

Runs a small multi-agent debate (a handful of personas, two rounds) using the
engine's own LLM, then synthesizes a prediction report. No external service
required.
"""

import logging

logger = logging.getLogger(__name__)

PERSONAS = [
    "an optimistic analyst focused on upside and opportunities",
    "a pessimistic risk-analyst focused on downside and threats",
    "a neutral data-driven researcher who weighs evidence",
]


class QuickPredictor:
    def __init__(self, engine):
        self.engine = engine

    def predict(self, seed: str, question: str) -> str:
        # Round 1: each persona gives an initial view
        views = []
        for persona in PERSONAS:
            prompt = (
                f"You are {persona}.\n\n"
                f"Context:\n{seed[:6000]}\n\n"
                f"Question: {question}\n\n"
                "Give your initial assessment in 3-5 concise bullet points."
            )
            try:
                view = self.engine.ask_llm(prompt)
            except Exception as e:
                view = f"(error: {e})"
            views.append(f"### {persona}\n{view}")

        # Round 2: personas react to each other
        debate = "\n\n".join(views)
        reactions = []
        for persona in PERSONAS[:2]:
            prompt = (
                f"You are {persona}.\n\n"
                f"Here are the initial views of several analysts:\n{debate[:6000]}\n\n"
                "Now that you have seen the others, give a revised view in 2-3 bullet points, "
                "noting where you agree or disagree."
            )
            try:
                reaction = self.engine.ask_llm(prompt)
            except Exception as e:
                reaction = f"(error: {e})"
            reactions.append(f"### {persona} (revised)\n{reaction}")

        # Synthesis
        all_views = debate + "\n\n" + "\n\n".join(reactions)
        synth_prompt = (
            "You are a chief forecaster. Synthesize the following analyst views into a "
            "final prediction report with these sections:\n"
            "1) MOST LIKELY OUTCOME\n"
            "2) KEY DRIVERS\n"
            "3) RISKS\n"
            "4) CONFIDENCE (low/medium/high) + one-sentence rationale\n\n"
            f"QUESTION: {question}\n\nANALYST VIEWS:\n{all_views[:8000]}"
        )
        return self.engine.ask_llm(synth_prompt)
