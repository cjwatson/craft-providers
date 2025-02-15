#
# Copyright 2021-2022 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License version 3 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import io
import pathlib
import subprocess
from typing import Any, Dict, List, Optional

import pytest
import responses as responses_module

from craft_providers import Executor
from craft_providers.util import env_cmd


class FakeExecutor(Executor):
    """Fake Executor.

    Provides a fake execution environment meant to be paired with the
    fake_subprocess fixture for complete control over execution behaviors.

    This records push_file_io(), pull_file(), and push_file() in
    records_of_<name> for introspection, similar to mock_calls.
    """

    def __init__(self) -> None:
        self.records_of_push_file_io: List[Dict[str, Any]] = []
        self.records_of_pull_file: List[Dict[str, Any]] = []
        self.records_of_push_file: List[Dict[str, Any]] = []

    def push_file_io(
        self,
        *,
        destination: pathlib.PurePath,
        content: io.BytesIO,
        file_mode: str,
        group: str = "root",
        user: str = "root",
    ) -> None:
        self.records_of_push_file_io.append(
            dict(
                destination=destination.as_posix(),
                content=content.read(),
                file_mode=file_mode,
                group=group,
                user=user,
            )
        )

    def execute_popen(
        self,
        command: List[str],
        *,
        cwd: Optional[pathlib.Path] = None,
        env: Optional[Dict[str, Optional[str]]] = None,
        **kwargs,
    ) -> subprocess.Popen:
        if env is None:
            env_args = []
        else:
            env_args = env_cmd.formulate_command(env, chdir=cwd)

        final_cmd = ["fake-executor"] + env_args + command
        return subprocess.Popen(  # pylint: disable=consider-using-with
            final_cmd, **kwargs
        )

    def execute_run(
        self,
        command: List[str],
        *,
        cwd: Optional[pathlib.Path] = None,
        env: Optional[Dict[str, Optional[str]]] = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        if env is None:
            env_args = []
        else:
            env_args = env_cmd.formulate_command(env, chdir=cwd)

        final_cmd = ["fake-executor"] + env_args + command
        return subprocess.run(  # pylint: disable=subprocess-run-check
            final_cmd, **kwargs
        )

    def pull_file(self, *, source: pathlib.PurePath, destination: pathlib.Path) -> None:
        self.records_of_pull_file.append(
            dict(
                source=source,
                destination=destination,
            )
        )

    def push_file(self, *, source: pathlib.Path, destination: pathlib.PurePath) -> None:
        self.records_of_push_file.append(
            dict(
                source=source,
                destination=destination,
            )
        )

    def delete(self) -> None:
        return

    def exists(self) -> bool:
        return True


@pytest.fixture
def fake_executor():
    yield FakeExecutor()


@pytest.fixture
def responses():
    """Simple helper to use responses module as a fixture.

    Used for easier integration in tests.
    """
    with responses_module.RequestsMock() as rsps:
        yield rsps
