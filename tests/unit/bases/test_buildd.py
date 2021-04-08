# Copyright 2021 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from textwrap import dedent
from unittest import mock

import pytest

from craft_providers.bases import buildd, errors
from craft_providers.errors import details_from_called_process_error
from craft_providers.util import env_cmd

DEFAULT_FAKE_CMD = [
    "fake-executor",
    *env_cmd.formulate_command(buildd.default_command_environment()),
]


@pytest.mark.parametrize(
    "alias,hostname",
    [
        (buildd.BuilddBaseAlias.XENIAL, "test-xenial-host"),
        (buildd.BuilddBaseAlias.BIONIC, "test-bionic-host"),
        (buildd.BuilddBaseAlias.FOCAL, "test-focal-host"),
    ],
)
@pytest.mark.parametrize(
    "command_environment, etc_environment_content",
    [
        (
            None,
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin\n".encode(),
        ),
        (
            dict(
                https_proxy="http://foo.bar:8081",
                PATH="/snap",
                http_proxy="http://foo.bar:8080",
            ),
            "https_proxy=http://foo.bar:8081\nPATH=/snap\nhttp_proxy=http://foo.bar:8080\n".encode(),
        ),
    ],
)
def test_setup(  # pylint: disable=too-many-arguments
    fake_process,
    fake_executor,
    alias,
    hostname,
    command_environment,
    etc_environment_content,
):
    base_config = buildd.BuilddBase(
        alias=alias,
        hostname=hostname,
        command_environment=command_environment,
    )

    if command_environment is None:
        command_environment = buildd.default_command_environment()

    fake_cmd = ["fake-executor", *env_cmd.formulate_command(command_environment)]

    fake_process.register_subprocess(
        [*fake_cmd, "cat", "/etc/os-release"],
        stdout=dedent(
            f"""\
            NAME="Ubuntu"
            ID=ubuntu
            ID_LIKE=debian
            VERSION_ID="{alias.value}"
            """
        ),
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "is-system-running"], stdout="degraded"
    )
    fake_process.register_subprocess([*fake_cmd, "hostname", "-F", "/etc/hostname"])
    fake_process.register_subprocess(
        [*fake_cmd, "ln", "-sf", "/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "enable", "systemd-resolved"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "restart", "systemd-resolved"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "enable", "systemd-networkd"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "restart", "systemd-networkd"]
    )
    fake_process.register_subprocess([*fake_cmd, "getent", "hosts", "snapcraft.io"])
    fake_process.register_subprocess([*fake_cmd, "apt-get", "update"])
    fake_process.register_subprocess(
        [*fake_cmd, "apt-get", "install", "-y", "apt-utils"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "apt-get", "install", "-y", "fuse", "udev"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "enable", "systemd-udevd"]
    )
    fake_process.register_subprocess([*fake_cmd, "systemctl", "start", "systemd-udevd"])
    fake_process.register_subprocess([*fake_cmd, "apt-get", "install", "-y", "snapd"])
    fake_process.register_subprocess([*fake_cmd, "systemctl", "start", "snapd.socket"])
    fake_process.register_subprocess(
        [*fake_cmd, "systemctl", "restart", "snapd.service"]
    )
    fake_process.register_subprocess(
        [*fake_cmd, "snap", "wait", "system", "seed.loaded"]
    )

    base_config.setup(executor=fake_executor)

    assert fake_executor.records_of_create_file == [
        dict(
            destination="/etc/environment",
            content=etc_environment_content,
            file_mode="0644",
            group="root",
            user="root",
        ),
        dict(
            destination="/etc/hostname",
            content=f"{hostname}\n".encode(),
            file_mode="0644",
            group="root",
            user="root",
        ),
        dict(
            destination="/etc/systemd/network/10-eth0.network",
            content=dedent(
                """\
                [Match]
                Name=eth0

                [Network]
                DHCP=ipv4
                LinkLocalAddressing=ipv6

                [DHCP]
                RouteMetric=100
                UseMTU=true
                """
            ).encode(),
            file_mode="0644",
            group="root",
            user="root",
        ),
        dict(
            destination="/etc/apt/apt.conf.d/00no-recommends",
            content=b'Apt::Install-Recommends "false";\n',
            file_mode="0644",
            group="root",
            user="root",
        ),
    ]
    assert fake_executor.records_of_pull_file == []
    assert fake_executor.records_of_push_file == []


@mock.patch("time.time", side_effect=[0.0, 1.0])
def test_setup_timeout(  # pylint: disable=unused-argument
    mock_time, fake_executor, fake_process, monkeypatch
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess([fake_process.any()])

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config.setup(
            executor=fake_executor,
            retry_wait=0.01,
            timeout=0.0,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Timed out configuring environment."
    )


def test_setup_hostname_failure(
    fake_process,
    fake_executor,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "hostname", "-F", "/etc/hostname"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_hostname(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to set hostname.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


def test_setup_networkd_enable_failure(
    fake_process,
    fake_executor,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "enable", "systemd-networkd"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_networkd(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to setup systemd-networkd.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


def test_setup_networkd_restart_failure(
    fake_process,
    fake_executor,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "enable", "systemd-networkd"],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "restart", "systemd-networkd"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_networkd(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to setup systemd-networkd.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


def test_setup_resolved_enable_failure(
    fake_process,
    fake_executor,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess(
        [
            *DEFAULT_FAKE_CMD,
            "ln",
            "-sf",
            "/run/systemd/resolve/resolv.conf",
            "/etc/resolv.conf",
        ],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "enable", "systemd-resolved"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_resolved(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to setup systemd-resolved.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


def test_setup_resolved_restart_failure(
    fake_process,
    fake_executor,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)
    fake_process.register_subprocess(
        [
            *DEFAULT_FAKE_CMD,
            "ln",
            "-sf",
            "/run/systemd/resolve/resolv.conf",
            "/etc/resolv.conf",
        ],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "enable", "systemd-resolved"],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "restart", "systemd-resolved"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_resolved(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to setup systemd-resolved.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


@pytest.mark.parametrize("fail_index", list(range(0, 7)))
def test_setup_snapd_failures(
    fake_process,
    fake_executor,
    fail_index,
):
    base_config = buildd.BuilddBase(alias=buildd.BuilddBaseAlias.FOCAL)

    return_codes = [0, 0, 0, 0, 0, 0, 0]
    return_codes[fail_index] = 1

    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "apt-get", "install", "-y", "fuse", "udev"],
        returncode=return_codes[0],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "enable", "systemd-udevd"],
        returncode=return_codes[1],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "start", "systemd-udevd"],
        returncode=return_codes[2],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "apt-get", "install", "-y", "snapd"],
        returncode=return_codes[3],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "start", "snapd.socket"],
        returncode=return_codes[4],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "restart", "snapd.service"],
        returncode=return_codes[5],
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "snap", "wait", "system", "seed.loaded"],
        returncode=return_codes[6],
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config._setup_snapd(  # pylint: disable=protected-access
            executor=fake_executor,
            deadline=None,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Failed to setup snapd.",
        details=details_from_called_process_error(exc_info.value.__cause__),  # type: ignore
    )


@pytest.mark.parametrize(
    "alias",
    [
        buildd.BuilddBaseAlias.XENIAL,
        buildd.BuilddBaseAlias.BIONIC,
        buildd.BuilddBaseAlias.FOCAL,
    ],
)
@pytest.mark.parametrize("system_running_ready_stdout", ["degraded", "running"])
def test_wait_for_system_ready(
    fake_executor, fake_process, alias, system_running_ready_stdout
):
    base_config = buildd.BuilddBase(alias=alias)
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "is-system-running"],
        stdout="not-ready",
        returncode=-1,
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "is-system-running"], stdout="still-not-ready"
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "is-system-running"],
        stdout=system_running_ready_stdout,
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "getent", "hosts", "snapcraft.io"],
        returncode=-1,
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "getent", "hosts", "snapcraft.io"],
        returncode=0,
    )

    base_config.wait_until_ready(executor=fake_executor, retry_wait=0.01)

    assert fake_executor.records_of_create_file == []
    assert fake_executor.records_of_pull_file == []
    assert fake_executor.records_of_push_file == []
    assert list(fake_process.calls) == [
        [
            *DEFAULT_FAKE_CMD,
            "systemctl",
            "is-system-running",
        ],
        [
            *DEFAULT_FAKE_CMD,
            "systemctl",
            "is-system-running",
        ],
        [
            *DEFAULT_FAKE_CMD,
            "systemctl",
            "is-system-running",
        ],
        [
            *DEFAULT_FAKE_CMD,
            "getent",
            "hosts",
            "snapcraft.io",
        ],
        [
            *DEFAULT_FAKE_CMD,
            "getent",
            "hosts",
            "snapcraft.io",
        ],
    ]


@mock.patch("time.time", side_effect=[0.0, 1.0])
@pytest.mark.parametrize(
    "alias",
    [
        buildd.BuilddBaseAlias.XENIAL,
        buildd.BuilddBaseAlias.BIONIC,
        buildd.BuilddBaseAlias.FOCAL,
    ],
)
def test_wait_for_system_ready_timeout(  # pylint: disable=unused-argument
    mock_time, fake_executor, fake_process, alias
):
    base_config = buildd.BuilddBase(
        alias=alias,
    )
    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "systemctl", "is-system-running"],
        stdout="not-ready",
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config.wait_until_ready(
            executor=fake_executor,
            retry_wait=0.01,
            timeout=0.0,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Timed out waiting for environment to be ready."
    )


@mock.patch("time.time", side_effect=[0.0, 1.0])
@pytest.mark.parametrize(
    "alias",
    [
        buildd.BuilddBaseAlias.XENIAL,
        buildd.BuilddBaseAlias.BIONIC,
        buildd.BuilddBaseAlias.FOCAL,
    ],
)
def test_wait_for_system_ready_timeout_in_network(  # pylint: disable=unused-argument
    mock_time, fake_executor, fake_process, alias, monkeypatch
):
    base_config = buildd.BuilddBase(alias=alias)
    monkeypatch.setattr(
        base_config, "_setup_wait_for_system_ready", lambda **kwargs: None
    )

    fake_process.register_subprocess(
        [*DEFAULT_FAKE_CMD, "getent", "hosts", "snapcraft.io"],
        returncode=-1,
    )

    with pytest.raises(errors.BaseConfigurationError) as exc_info:
        base_config.wait_until_ready(
            executor=fake_executor,
            retry_wait=0.01,
            timeout=1.0,
        )

    assert exc_info.value == errors.BaseConfigurationError(
        brief="Timed out waiting for networking to be ready."
    )
