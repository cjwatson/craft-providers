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
import os
import pathlib
import subprocess

import pytest

from craft_providers import bases, lxd
from craft_providers.lxd import project as lxd_project

from . import conftest


@pytest.fixture()
def core20_instance(instance_name):
    with conftest.tmp_instance(
        name=instance_name,
        image="20.04",
        image_remote="ubuntu",
        project="default",
    ):
        instance = lxd.LXDInstance(name=instance_name)

        yield instance

        if instance.exists():
            instance.delete()


@pytest.mark.parametrize(
    "alias,image_name",
    [
        pytest.param(
            bases.BuilddBaseAlias.XENIAL,
            "16.04",
        ),
        (bases.BuilddBaseAlias.BIONIC, "18.04"),
        (bases.BuilddBaseAlias.FOCAL, "20.04"),
        # FIXME: enable after image is available
        # (bases.BuilddBaseAlias.JAMMY, "22.04"),
    ],
)
def test_launch_and_run(instance_name, alias, image_name):
    base_configuration = bases.BuilddBase(alias=alias)

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name=image_name,
        image_remote="ubuntu",
    )

    try:
        assert isinstance(instance, lxd.LXDInstance)
        assert instance.exists() is True
        assert instance.is_running() is True

        proc = instance.execute_run(["echo", "hi"], check=True, stdout=subprocess.PIPE)

        assert proc.stdout == b"hi\n"
    finally:
        instance.delete()


def test_launch_with_snapshots(instance_name):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)
    snapshot_name = "snapshot-ubuntu-20.04-buildd-base-v0"
    lxc = lxd.LXC()

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        use_snapshots=True,
    )

    try:
        instance.delete()

        assert lxc.has_image(snapshot_name) is True

        instance = lxd.launch(
            name=instance_name,
            base_configuration=base_configuration,
            image_name="20.04",
            image_remote="ubuntu",
            use_snapshots=True,
        )
    finally:
        if instance.exists():
            instance.delete()

        if lxc.has_image(snapshot_name):
            lxc.image_delete(image=snapshot_name)


def test_launch_creating_project(instance_name, project_name):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)
    lxc = lxd.LXC()

    assert project_name not in lxc.project_list()

    try:
        instance = lxd.launch(
            name=instance_name,
            base_configuration=base_configuration,
            image_name="20.04",
            image_remote="ubuntu",
            auto_create_project=True,
            project=project_name,
            remote="local",
        )

        assert instance.exists()
        assert project_name in lxc.project_list()
    finally:
        lxd_project.purge(lxc=lxc, project=project_name)


def test_launch_with_project_and_snapshots(instance_name, project):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)
    snapshot_name = "snapshot-ubuntu-20.04-buildd-base-v0"
    lxc = lxd.LXC()

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        use_snapshots=True,
        project=project,
        remote="local",
    )

    try:
        instance.delete()

        assert lxc.has_image(snapshot_name, project=project, remote="local") is True

        instance = lxd.launch(
            name=instance_name,
            base_configuration=base_configuration,
            image_name="20.04",
            image_remote="ubuntu",
            use_snapshots=True,
            project=project,
            remote="local",
        )
    finally:
        if instance.exists():
            instance.delete()

        if lxc.has_image(snapshot_name, project=project, remote="local"):
            lxc.image_delete(image=snapshot_name, project=project, remote="local")


def test_launch_ephemeral(instance_name):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        ephemeral=True,
    )

    try:
        instance.stop()

        assert instance.exists() is False
    finally:
        if instance.exists():
            instance.delete()


def test_launch_map_user_uid_true(instance_name, tmp_path):
    tmp_path.chmod(0o755)

    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        map_user_uid=True,
        uid=os.stat(tmp_path).st_uid,
    )

    try:
        instance.mount(host_source=tmp_path, target=pathlib.Path("/mnt"))

        # If user ID mappings are enabled, we will be able to write.
        instance.execute_run(["touch", "/mnt/foo"], capture_output=True, check=True)
    finally:
        if instance.exists():
            instance.delete()


def test_launch_map_user_uid_true_no_uid(instance_name, tmp_path):
    tmp_path.chmod(0o755)

    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        map_user_uid=True,
    )

    try:
        instance.mount(host_source=tmp_path, target=pathlib.Path("/mnt"))

        # If user ID mappings are enabled, we will be able to write.
        instance.execute_run(["touch", "/mnt/foo"], capture_output=True, check=True)
    finally:
        if instance.exists():
            instance.delete()


def test_launch_map_user_uid_false(instance_name, tmp_path):
    tmp_path.chmod(0o755)

    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        map_user_uid=False,
    )

    try:
        instance.mount(host_source=tmp_path, target=pathlib.Path("/mnt"))

        # If user ID mappings are not enabled, we won't be able to write.
        with pytest.raises(subprocess.CalledProcessError):
            instance.execute_run(["touch", "/mnt/foo"], capture_output=True, check=True)
    finally:
        if instance.exists():
            instance.delete()


def test_launch_existing_instance(core20_instance):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    instance = lxd.launch(
        name=core20_instance.name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
    )

    assert instance.exists() is True
    assert instance.is_running() is True

    proc = instance.execute_run(["echo", "hi"], check=True, stdout=subprocess.PIPE)

    assert proc.stdout == b"hi\n"


def test_launch_os_incompatible_instance(core20_instance):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    core20_instance.push_file_io(
        destination=pathlib.Path("/etc/os-release"),
        content=io.BytesIO(b"NAME=Fedora\nVERSION_ID=32\n"),
        file_mode="0644",
    )

    # Should raise compatibility error with auto_clean=False.
    with pytest.raises(bases.BaseCompatibilityError) as exc_info:
        lxd.launch(
            name=core20_instance.name,
            base_configuration=base_configuration,
            image_name="20.04",
            image_remote="ubuntu",
        )

    assert (
        exc_info.value.brief
        == "Incompatible base detected: Expected OS 'Ubuntu', found 'Fedora'."
    )

    # Retry with auto_clean=True.
    lxd.launch(
        name=core20_instance.name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        auto_clean=True,
    )

    assert core20_instance.exists() is True
    assert core20_instance.is_running() is True


def test_launch_instance_config_incompatible_instance(core20_instance):
    base_configuration = bases.BuilddBase(alias=bases.BuilddBaseAlias.FOCAL)

    core20_instance.push_file_io(
        destination=base_configuration.instance_config_path,
        content=io.BytesIO(b"compatibility_tag: invalid\n"),
        file_mode="0644",
    )

    # Should raise compatibility error with auto_clean=False.
    with pytest.raises(bases.BaseCompatibilityError) as exc_info:
        lxd.launch(
            name=core20_instance.name,
            base_configuration=base_configuration,
            image_name="20.04",
            image_remote="ubuntu",
        )

    assert exc_info.value.brief == (
        "Incompatible base detected:"
        " Expected image compatibility tag 'buildd-base-v0', found 'invalid'."
    )

    # Retry with auto_clean=True.
    lxd.launch(
        name=core20_instance.name,
        base_configuration=base_configuration,
        image_name="20.04",
        image_remote="ubuntu",
        auto_clean=True,
    )

    assert core20_instance.exists() is True
    assert core20_instance.is_running() is True
