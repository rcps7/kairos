class Skill:
    """Base class for all skills."""
    name = "base"
    description = "Base skill"

    def run(self, engine, **kwargs):
        raise NotImplementedError
