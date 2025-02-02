from pathlib import Path
from filecmp import dircmp, cmpfiles

import pytest

from protostar.cairo import CairoVersion
from tests.integration.conftest import CreateProtostarProjectFixture
from tests.conftest import PROJECT_ROOT


@pytest.mark.parametrize("cairo_version", [CairoVersion.cairo0, CairoVersion.cairo1])
def test_init(
    create_protostar_project: CreateProtostarProjectFixture, cairo_version: CairoVersion
):
    with create_protostar_project(cairo_version):
        mocker_project_path = Path(".")
        template_project_path = PROJECT_ROOT / "templates" / cairo_version.value

        dir_compare_object = dircmp(
            mocker_project_path, template_project_path, hide=[".DS_Store"]
        )
        compare_directories(dir_compare_object)


def test_init_cairo1_minimal(create_protostar_project: CreateProtostarProjectFixture):
    with create_protostar_project(CairoVersion.cairo1, True):
        mocker_project_path = Path(".")
        template_project_path = PROJECT_ROOT / "templates" / "cairo1_minimal"

        dir_compare_object = dircmp(mocker_project_path, template_project_path)
        compare_directories(dir_compare_object)


def compare_directories(dcmp: dircmp):
    assert not (dcmp.left_only or dcmp.right_only or dcmp.diff_files), (
        f"files or directories with different os.stat() (probably different content) signatures: {dcmp.diff_files}\n "
        f"files or directories not present in real templates directory: {dcmp.left_only}\n"
        f"files or directories not present in mock templates directory: {dcmp.right_only}"
    )

    _, diff, errors = cmpfiles(dcmp.left, dcmp.right, dcmp.same_files, shallow=False)

    assert not (diff or errors), (
        f"files with different content: {diff}\n"
        f"files which could not be compared: {errors}"
    )

    for sub_dcmp in dcmp.subdirs.values():
        compare_directories(sub_dcmp)
