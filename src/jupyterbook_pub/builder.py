from traitlets import Bool, Unicode, List
from traitlets.config import LoggingConfigurable

import enum
import pathlib


class ReservedCommands(enum.StrEnum):
    python = "python"


class Builder(LoggingConfigurable):
    def entrypoint(
        self,
        repo_path: pathlib.Path,
        build_path: pathlib.Path,
        base_url: str,
        config_path: pathlib.Path = None,
    ) -> tuple[ReservedCommands | str, ...]:
        raise NotImplementedError


class GenericBuilder(Builder):
    reserved_program = Bool(False, config=True)
    command = List(None, value_trait=Unicode(), allow_none=False, config=True)

    def entrypoint(
        self,
        repo_path: pathlib.Path,
        build_path: pathlib.Path,
        base_url: str,
        config_path: pathlib.Path = None,
    ) -> tuple[ReservedCommands | str, ...]:
        template_variables = {
            "repo": repo_path,
            "build": build_path,
            "base_url": base_url,
            "config": config_path,
        }
        program, *raw_args = self.command
        args = [arg.format_map(template_variables) for arg in raw_args]

        # Allow "python" to be substituted with ReservedCommands.python
        if self.reserved_program:
            program = ReservedCommands.__members__.get(program, program)

        return (program, *args)
