class Skill:
    """Base class for all skills."""
    name = "base"
    description = "Base skill"
    # Set True for skills that open Qt dialogs (they run in-process on the
    # main thread and cannot be sandboxed).
    uses_ui = False

    def run(self, engine, **kwargs):
        raise NotImplementedError
