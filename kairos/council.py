"""Multi-LLM council for complex tasks.

Three configured LLMs:
1. review the task, self-assess their best-fit role and vote for a lead,
2. the elected Primary divides the work between the two workers,
3. workers execute their parts,
4. the Primary verifies, corrects and optimizes the result.

Call budget (standard): 3 (aptitude) + 1 (division) + 2 (work) + 1 (verify) = 7.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _strip_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    # Extract the first {...} or [...] block
    m = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


class Council:
    def __init__(self, engine):
        self.engine = engine

    # ---- helpers ----
    def _call(self, member, system, user, images=None, use_character=True):
        if images and self.engine.llm.is_vision(member):
            return self.engine.generate_with_images(
                user, images, system_prompt=system, provider_id=member,
                use_character=use_character,
            )
        return self.engine.ask_llm(
            user, provider_id=member, system_prompt=system,
            use_character=use_character,
        )

    def _emit(self, progress, text):
        logger.info("[council] %s", text)
        if progress:
            try:
                progress(text)
            except Exception:
                pass

    # ---- main ----
    def run(self, prompt: str, members, context: str = "", image_paths=None,
            mode: str = "standard", progress=None) -> dict:
        members = [m for m in (members or []) if m]
        if len(members) < 2:
            raise RuntimeError("Council needs at least two LLM members.")

        image_paths = image_paths or []
        task = f"TASK:\n{prompt}"
        if context:
            task += f"\n\nATTACHED MATERIAL:\n{context}"

        # --- Stage 1: aptitude + vote ---
        self._emit(progress, "Stage 1: members assessing aptness…")
        assessments = {}
        for m in members:
            system = (
                "You are one member of a 3-model AI council. Assess the task and "
                "decide which member role you are best suited for. "
                "Reply ONLY with JSON: "
                '{"role": "<specialist role>", "confidence": <0-100>, '
                '"approach": "<brief plan>", "vote": "<member id you think should lead>"}. '
                f"Council members: {', '.join(members)}."
            )
            try:
                raw = self._call(m, system, task, image_paths, use_character=False)
            except Exception as e:
                raw = f'{{"role":"generalist","confidence":0,"approach":"error: {e}","vote":"{members[0]}"}}'
            data = _strip_json(raw) or {"role": "generalist", "confidence": 0, "approach": raw[:200], "vote": members[0]}
            assessments[m] = data
            self._emit(progress, f"  {m}: role={data.get('role')} conf={data.get('confidence')} vote={data.get('vote')}")

        # --- Stage 2: elect primary ---
        votes = {}
        for m in members:
            v = assessments[m].get("vote")
            if v in members:
                votes[v] = votes.get(v, 0) + 1
        if votes:
            primary = max(votes, key=lambda k: (votes[k], assessments.get(k, {}).get("confidence", 0)))
        else:
            primary = max(members, key=lambda m: assessments[m].get("confidence", 0))
        workers = [m for m in members if m != primary]
        self._emit(progress, f"Primary elected: {primary} (votes={votes}); workers={workers}")

        # --- Stage 3: division of work (primary) ---
        self._emit(progress, "Stage 3: primary dividing the work…")
        roles = {m: assessments[m].get("role", "generalist") for m in members}
        div_system = (
            "You are the elected PRIMARY of an AI council. Divide the task into concrete "
            "subtasks and assign each to one worker. Reply ONLY with JSON: "
            '{"subtasks": [{"title": "...", "details": "...", "assignee": "<member id>"}]}. '
            f"Workers: {', '.join(workers)}."
        )
        div_user = (
            f"{task}\n\nMember strengths: {json.dumps(roles)}\n"
            "Create 2-4 subtasks covering the whole task."
        )
        try:
            raw = self._call(primary, div_system, div_user, image_paths, use_character=False)
            plan = _strip_json(raw) or {}
        except Exception as e:
            plan = {}
            self._emit(progress, f"  division failed ({e}); using default split")
        subtasks = plan.get("subtasks") or []
        if not subtasks:
            # Fallback split
            subtasks = [
                {"title": "Part A", "details": "Complete the first half of the task.", "assignee": workers[0]},
                {"title": "Part B", "details": "Complete the second half of the task.", "assignee": workers[1] if len(workers) > 1 else workers[0]},
            ]

        # --- Stage 4: execution (workers) ---
        self._emit(progress, "Stage 4: workers executing…")
        outputs = []
        for m in workers:
            mine = [s for s in subtasks if s.get("assignee") == m]
            if not mine:
                continue
            details = "\n".join(f"- {s.get('title')}: {s.get('details')}" for s in mine)
            work_system = (
                f"You are council member '{m}', specializing as {assessments.get(m, {}).get('role', 'generalist')}. "
                "Complete your assigned subtasks thoroughly and return the finished work."
            )
            work_user = f"{task}\n\nYOUR SUBTASKS:\n{details}\n\nProduce your completed work now."
            try:
                out = self._call(m, work_system, work_user, image_paths)
            except Exception as e:
                out = f"(worker {m} failed: {e})"
            outputs.append(f"### Work by {m}\n{out}")
            self._emit(progress, f"  {m} finished")

        # --- Stage 5: verification / optimization (primary) ---
        self._emit(progress, "Stage 5: primary verifying and optimizing…")
        verify_system = (
            "You are the elected PRIMARY. Review the workers' output against the original task. "
            "Fix errors, fill gaps, optimize, and produce the FINAL deliverable. "
            "Be complete and well-structured; include code with correct indentation where relevant."
        )
        verify_user = (
            f"{task}\n\nWORKER OUTPUT:\n" + "\n\n".join(outputs) +
            "\n\nProduce the final verified result for the user."
        )
        try:
            final = self._call(primary, verify_system, verify_user, image_paths)
        except Exception as e:
            final = "\n\n".join(outputs) + f"\n\n(verification failed: {e})"
        self._emit(progress, "Council finished.")

        return {
            "final": final,
            "primary": primary,
            "workers": workers,
            "assessments": assessments,
            "subtasks": subtasks,
        }
