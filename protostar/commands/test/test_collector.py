# pylint: disable=no-self-use

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch
from glob import glob
from logging import Logger
from pathlib import Path
from typing import Dict, Generator, List, Optional, Pattern, Set, cast

from starkware.cairo.lang.compiler.preprocessor.preprocessor_error import (
    PreprocessorError,
)
from starkware.starknet.compiler.starknet_preprocessor import (
    StarknetPreprocessedProgram,
)

from protostar.commands.test.test_suite import TestSuite
from protostar.protostar_exception import ProtostarException
from protostar.utils.starknet_compilation import StarknetCompiler

TestSuiteGlob = str
TestSuitePath = Path
TestCaseGlob = str
Target = str
"""e.g. `tests/**/::test_*`"""
TestCaseGlobsDict = Dict[TestSuitePath, Set[TestCaseGlob]]


@dataclass(frozen=True)
class ParsedTarget:
    test_suite_glob: TestSuiteGlob
    test_case_glob: TestCaseGlob

    @classmethod
    def from_target(
        cls, target: Target, default_test_suite_glob: Optional[TestSuiteGlob]
    ):
        test_suite_glob: Optional[TestSuiteGlob] = target
        test_case_glob: Optional[TestCaseGlob] = None
        if "::" in target:
            (test_suite_glob, test_case_glob) = target.split("::")
        test_suite_glob = test_suite_glob or default_test_suite_glob or "."

        if not test_case_glob:
            test_case_glob = "*"

        return cls(test_suite_glob, test_case_glob)


@dataclass
class TestSuiteInfo:
    path: Path
    test_case_globs: Set[TestCaseGlob]
    ignored_test_case_globs: Set[TestCaseGlob]

    def match_test_case_names(self, test_case_names: List[str]) -> List[str]:
        matches = self._find_matching_any_test_case_glob(test_case_names)
        result = self._filter_out_matching_any_ignored_test_case_glob(matches)
        return list(result)

    def _find_matching_any_test_case_glob(self, test_case_names: List[str]) -> Set[str]:
        result: Set[str] = set()
        for test_case_name in test_case_names:
            for test_case_glob in self.test_case_globs:
                if fnmatch(test_case_name, test_case_glob):
                    result.add(test_case_name)
        return result

    def _filter_out_matching_any_ignored_test_case_glob(
        self, test_case_names: Set[str]
    ) -> Set[str]:
        result = (
            test_case_names.copy()
        )  # copy prevents changing lengths of this collection during loop execution
        for test_case_name in test_case_names:
            for ignored_test_case_glob in self.ignored_test_case_globs:
                if fnmatch(test_case_name, ignored_test_case_glob):
                    result.remove(test_case_name)
                    break
        return result


TestSuiteInfoDict = Dict[TestSuitePath, TestSuiteInfo]


class TestCollectingException(ProtostarException):
    pass


@dataclass
class TestCollector:
    class Result:
        def __init__(self, test_suites: List[TestSuite]) -> None:
            self.test_suites = test_suites
            self.test_cases_count = sum(
                [len(test_suite.test_case_names) for test_suite in test_suites]
            )

        def log(self, logger: Logger):
            if self.test_cases_count:
                result: List[str] = ["Collected"]
                suites_count = len(self.test_suites)
                if suites_count == 1:
                    result.append("1 suite,")
                else:
                    result.append(f"{suites_count} suites,")

                result.append("and")
                if self.test_cases_count == 1:
                    result.append("1 test case")
                else:
                    result.append(f"{self.test_cases_count} test cases")

                logger.info(" ".join(result))
            else:
                logger.warning("No cases found")

    def __init__(
        self,
        starknet_compiler: StarknetCompiler,
    ) -> None:
        self._starknet_compiler = starknet_compiler

    supported_test_suite_filename_patterns = [
        re.compile(r"^test_.*\.cairo"),
        re.compile(r"^.*_test.cairo"),
    ]

    def collect(
        self,
        target: Path,
        omit_pattern: Optional[Pattern] = None,
    ) -> "TestCollector.Result":
        target_test_case: Optional[str] = None
        if re.match(r"^.*\.cairo::.*", target.name):
            file_name, target_test_case = target.name.split("::")
            target = target.parent / file_name
            assert not target.is_dir()

        test_suite_paths = self._get_test_suite_paths(target)

        if omit_pattern:
            test_suite_paths = filter(
                lambda file_path: not cast(Pattern, omit_pattern).match(str(file_path)),
                test_suite_paths,
            )

        test_suites: List[TestSuite] = []
        for test_suite in test_suite_paths:
            test_suites.append(self._build_test_suite(test_suite, target_test_case))

        non_empty_test_suites = list(
            filter(lambda test_file: (test_file.test_case_names) != [], test_suites)
        )

        return TestCollector.Result(
            test_suites=non_empty_test_suites,
        )

    @classmethod
    def is_test_suite(cls, filename: str) -> bool:
        return any(
            test_re.match(filename)
            for test_re in cls.supported_test_suite_filename_patterns
        )

    def _build_test_suite(
        self, file_path: Path, target_test_case_name: Optional[str]
    ) -> TestSuite:
        preprocessed = self._preprocess_contract(file_path)
        test_case_names = self._collect_test_case_names(preprocessed)
        if target_test_case_name:
            test_case_names = [
                test_case_name
                for test_case_name in test_case_names
                if test_case_name == target_test_case_name
            ]

        return TestSuite(
            test_path=file_path,
            test_case_names=test_case_names,
            preprocessed_contract=preprocessed,
            setup_fn_name=self._find_setup_hook_name(preprocessed),
        )

    def _get_test_suite_paths(self, target: Path) -> Generator[Path, None, None]:
        if not target.is_dir():
            yield target
            return
        for root, _, files in os.walk(target):
            test_suite_paths = [Path(root, file) for file in files]
            test_suite_paths = filter(
                lambda file: self.is_test_suite(file.name), test_suite_paths
            )
            for test_suite_path in test_suite_paths:
                yield test_suite_path

    def _collect_test_case_names(
        self, preprocessed: StarknetPreprocessedProgram
    ) -> List[str]:
        return self._starknet_compiler.get_function_names(
            preprocessed, predicate=lambda fn_name: fn_name.startswith("test_")
        )

    def _find_setup_hook_name(
        self, preprocessed: StarknetPreprocessedProgram
    ) -> Optional[str]:
        function_names = self._starknet_compiler.get_function_names(
            preprocessed, predicate=lambda fn_name: fn_name == "__setup__"
        )
        return function_names[0] if len(function_names) > 0 else None

    def _preprocess_contract(self, file_path: Path) -> StarknetPreprocessedProgram:
        try:
            return self._starknet_compiler.preprocess_contract(file_path)
        except PreprocessorError as p_err:
            print(p_err)
            raise TestCollectingException("Failed to collect test cases") from p_err

    def collect_from_targets(
        self,
        targets: List[Target],
        ignored_targets: Optional[List[Target]] = None,
        default_test_suite_glob: Optional[str] = None,
    ) -> "TestCollector.Result":
        parsed_targets = self.parse_targets(set(targets), default_test_suite_glob)
        ignored_parsed_targets = self.parse_targets(
            set(ignored_targets or []), default_test_suite_glob
        )

        test_case_globs_dict = self.build_test_case_globs_dict(parsed_targets)
        ignored_test_case_globs_dict = self.build_test_case_globs_dict(
            ignored_parsed_targets
        )

        filtered_test_case_globs_dict = self.filter_out_ignored_test_suites(
            test_case_globs_dict,
            ignored_test_case_globs_dict,
        )

        test_suite_info_dict = self.build_test_suite_info_dict(
            filtered_test_case_globs_dict,
            ignored_test_case_globs_dict,
        )

        test_suites = self._build_test_suites_from_test_suite_info_dict(
            test_suite_info_dict
        )

        non_empty_test_suites = list(
            filter(lambda test_file: (test_file.test_case_names) != [], test_suites)
        )

        return TestCollector.Result(
            test_suites=non_empty_test_suites,
        )

    def build_test_case_globs_dict(
        self,
        parsed_targets: Set[ParsedTarget],
    ) -> TestCaseGlobsDict:
        results: TestCaseGlobsDict = defaultdict(set)

        for parsed_target in parsed_targets:
            test_suite_paths = self._find_test_suite_paths_from_glob(
                parsed_target.test_suite_glob
            )
            for test_suite_path in test_suite_paths:
                results[test_suite_path].add(parsed_target.test_case_glob)
        return results

    def parse_targets(
        self, targets: Set[Target], default_test_suite_glob: Optional[str] = None
    ) -> Set[ParsedTarget]:
        return {
            ParsedTarget.from_target(target, default_test_suite_glob)
            for target in targets
        }

    def filter_out_ignored_test_suites(
        self,
        test_case_globs_dict: TestCaseGlobsDict,
        ignored_test_case_globs_dict: TestCaseGlobsDict,
    ) -> TestCaseGlobsDict:
        result = test_case_globs_dict.copy()
        for ignored_target_path in ignored_test_case_globs_dict:
            if (
                "*" in ignored_test_case_globs_dict[ignored_target_path]
                and ignored_target_path in result
            ):
                del result[ignored_target_path]
        return result

    def build_test_suite_info_dict(
        self,
        test_case_globs_dict: TestCaseGlobsDict,
        ignored_test_case_globs_dict: TestCaseGlobsDict,
    ) -> TestSuiteInfoDict:
        result: TestSuiteInfoDict = {}
        for test_suite_path in test_case_globs_dict:
            test_suite_info = result.setdefault(
                test_suite_path,
                TestSuiteInfo(
                    test_case_globs=set(),
                    ignored_test_case_globs=set(),
                    path=test_suite_path,
                ),
            )
            test_suite_info.test_case_globs = test_case_globs_dict[test_suite_path]
            if test_suite_path in ignored_test_case_globs_dict:
                test_suite_info.ignored_test_case_globs = ignored_test_case_globs_dict[
                    test_suite_path
                ]
        return result

    def _find_test_suite_paths_from_glob(
        self, test_suite_glob: str
    ) -> Set[TestSuitePath]:
        results: Set[Path] = set()
        matches = glob(test_suite_glob, recursive=True)
        for match in matches:
            path = Path(match)
            if path.is_dir():
                results.update(self._find_test_suite_paths_in_dir(path))
            elif path.is_file() and TestCollector.is_test_suite(path.name):
                results.add(path)
        return results

    def _find_test_suite_paths_in_dir(self, path: Path) -> Set[TestSuitePath]:
        filepaths = set(glob(f"{path}/**/*.cairo", recursive=True))
        results: Set[Path] = set()
        for filepath in filepaths:
            path = Path(filepath)
            if TestCollector.is_test_suite(path.name):
                results.add(path)
        return results

    def _build_test_suites_from_test_suite_info_dict(
        self,
        test_suite_info_dict: TestSuiteInfoDict,
    ) -> List[TestSuite]:
        return [
            self._build_test_suite_from_test_suite_info(
                test_suite_info,
            )
            for test_suite_info in test_suite_info_dict.values()
        ]

    def _build_test_suite_from_test_suite_info(
        self,
        test_suite_info: TestSuiteInfo,
    ) -> TestSuite:
        preprocessed = self._preprocess_contract(test_suite_info.path)
        collected_test_case_names = self._collect_test_case_names(preprocessed)
        matching_test_case_names = test_suite_info.match_test_case_names(
            collected_test_case_names
        )

        return TestSuite(
            test_path=test_suite_info.path,
            test_case_names=matching_test_case_names,
            preprocessed_contract=preprocessed,
            setup_fn_name=self._find_setup_hook_name(preprocessed),
        )
