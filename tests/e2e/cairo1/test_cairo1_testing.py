import os

from pathlib import Path

from tests.e2e.conftest import CopyFixture, ProtostarFixture


def test_cairo1_test(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/test_a.cairo", "./cairo1_project/tests/test_a.cairo")
    os.chdir("./cairo1_project")

    result = protostar(["test", "tests"])

    assert "Collected 1 suite, and 3 test cases" in result
    assert "3 passed" in result


def test_no_scarb_toml_found(protostar: ProtostarFixture):
    result = protostar(["test", "tests"], expect_exit_code=1)

    assert "Scarb.toml not found" in result


def test_no_tests_found(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    os.chdir("./cairo1_project")

    result = protostar(["test", "tests"])

    assert "No test cases found" in result


def test_failing_tests(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture(
        "cairo1/failing_test.cairo", "./cairo1_project/tests/failing_test.cairo"
    )
    os.chdir("./cairo1_project")

    result = protostar(["--no-color", "test", "tests"], ignore_exit_code=True)

    expected_output_lines = [
        "Collected 1 suite, and 3 test cases",
        "[FAIL] tests/failing_test.cairo test_panic_single_value",
        "Test failed with data:",
        "[21] (integer representation)",
        "['\\x15'] (short-string representation)",
        "[PASS] tests/failing_test.cairo test_ok",
        "[FAIL] tests/failing_test.cairo test_panic_multiple_values",
        "Test failed with data: ",
        "[1870930782904301745253, 482670963043, 31066316372818838395891839589] (integer representation)",
        "['elaborate', 'panic', 'data is here'] (short-string representation)",
        "Test suites: 1 failed, 1 total",
        "Tests:       2 failed, 1 passed, 3 total",
    ]

    for expected_output_line in expected_output_lines:
        assert expected_output_line in result


def test_targeted_collecting(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/test_a.cairo", "./cairo1_project/tests/test_a.cairo")
    os.chdir("./cairo1_project")

    result = protostar(["test", "::test_B"])

    assert "Collected 1 suite, and 1 test case" in result
    assert "test_B" in result


def test_glob_collecting(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/nested", "./cairo1_project/tests/nested")
    os.chdir("./cairo1_project")

    result = protostar(["test", "./tests/**/*nested*::nested*"])

    assert "Collected 1 suite, and 2 test cases" in result
    assert "nested_1" in result
    assert "nested_2" in result


def test_ignoring_dir(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/test_a.cairo", "./cairo1_project/tests/test_a.cairo")
    copy_fixture("cairo1/nested", "./cairo1_project/tests/nested")

    os.chdir("./cairo1_project")

    result = protostar(["test", "./tests", "--ignore", "**/nested"])

    assert "nested_1" not in result
    assert "nested_2" not in result


def test_ignoring_cases(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    os.chdir("./cairo1_project")

    result = protostar(["test", "./tests", "--ignore", "**/*::*nested*"])

    assert "nested_1" not in result
    assert "nested_2" not in result


def test_exit_first(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/failing_test.cairo", "./cairo1_project/tests")
    os.chdir("./cairo1_project")

    result = protostar(
        ["--no-color", "test", "--exit-first", "./tests"], ignore_exit_code=True
    )
    # The test suite contains 2 failing tests, so it should fail only one of them when using exit-first
    assert "1 failed" in result


def test_last_failed(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/failing_test.cairo", "./cairo1_project/tests")
    os.chdir("./cairo1_project")

    result = protostar(["--no-color", "test", "./tests"], ignore_exit_code=True)
    # Suite consisting of 1 passing, and 2 failing
    assert "2 failed" in result
    assert "1 passed" in result
    assert "3 total" in result

    result = protostar(["--no-color", "test", "--last-failed"], ignore_exit_code=True)

    # Only ran 2 failed ones
    assert "Running previously failed tests" in result
    assert "Collected 1 suite, and 2 test cases" in result
    assert "test_panic_multiple_values" in result
    assert "test_panic_single_value" in result
    assert "test_ok" not in result

    assert "2 failed" in result
    assert "2 total" in result


def test_report_slowest(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture("cairo1/failing_test.cairo", "./cairo1_project/tests")
    os.chdir("./cairo1_project")

    result = protostar(
        ["--no-color", "test", "./tests", "--report-slowest-tests", "10"],
        ignore_exit_code=True,
    )
    assert "Slowest test cases" in result


def test_dependencies(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture(
        "cairo1/test_with_deps.cairo", "./cairo1_project/tests/test_with_deps.cairo"
    )
    os.chdir("./cairo1_project")

    result = protostar(["--no-color", "test", "tests"])

    assert "Collected 1 suite, and 1 test case" in result
    assert "test_assert_true" in result
    assert "1 passed, 1 total" in result


def test_dependencies_fail(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_project", "./cairo1_project")
    copy_fixture(
        "cairo1/test_with_deps.cairo", "./cairo1_project/tests/test_with_deps.cairo"
    )
    os.chdir("./cairo1_project")

    scarb_toml = Path("Scarb.toml")
    scarb_toml.write_text(
        scarb_toml.read_text().replace(
            'external_lib_bar = { path = "libraries/external_lib_bar"}', ""
        )
    )
    result = protostar(["--no-color", "test", "tests"], expect_exit_code=1)

    assert "for a detailed information, please go through the logs above" in result
    assert "Detailed error information" in result


def test_modules(protostar: ProtostarFixture, copy_fixture: CopyFixture):
    copy_fixture("cairo1_modules", "./cairo_project")
    os.chdir("./cairo_project")

    result = protostar(["--no-color", "test", "tests"])

    assert "Collected 1 suite, and 1 test case" in result
    assert "tests/test_main.cairo test_modules" in result
    assert "1 passed, 1 total" in result
