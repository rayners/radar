"""Sandboxed test execution for plugins."""

import traceback
from typing import Callable

from radar.plugins.models import TestCase


class TestRunner:
    """Runs tests for plugins in a sandboxed environment."""

    def __init__(self, timeout_seconds: int = 10):
        """Initialize test runner with timeout."""
        self.timeout_seconds = timeout_seconds

    def run_tests(
        self, code: str, test_cases: list[TestCase], function_name: str
    ) -> tuple[bool, list[dict]]:
        """Run test cases against the code.

        Returns (all_passed, list of test results).
        """
        results = []

        # Create a restricted namespace for execution
        namespace = self._create_safe_namespace()

        # Execute the code to define the function
        # Note: This uses exec() intentionally for sandboxed plugin execution
        # The code has been validated by CodeValidator before reaching here
        try:
            exec(code, namespace)  # nosec: validated code execution
        except Exception as e:
            return False, [
                {
                    "name": "code_execution",
                    "passed": False,
                    "error": f"Failed to execute code: {e}",
                    "traceback": traceback.format_exc(),
                }
            ]

        # Get the function
        if function_name not in namespace:
            return False, [
                {
                    "name": "function_check",
                    "passed": False,
                    "error": f"Function '{function_name}' not defined in code",
                }
            ]

        func = namespace[function_name]

        # Run each test case
        all_passed = True
        for test in test_cases:
            result = self._run_single_test(func, test)
            results.append(result)
            if not result["passed"]:
                all_passed = False

        return all_passed, results

    def _run_single_test(self, func: Callable, test: TestCase) -> dict:
        """Run a single test case."""
        result = {
            "name": test.name,
            "input": test.input_args,
            "passed": False,
            "output": None,
            "error": None,
            "traceback": None,
        }

        try:
            output = func(**test.input_args)
            result["output"] = str(output) if output is not None else None

            # Check expected output
            if test.expected_output is not None:
                if str(output) == test.expected_output:
                    result["passed"] = True
                else:
                    result["error"] = f"Expected '{test.expected_output}', got '{output}'"
            elif test.expected_contains is not None:
                if test.expected_contains in str(output):
                    result["passed"] = True
                else:
                    result["error"] = f"Output doesn't contain '{test.expected_contains}'"
            else:
                # No expected output, just check it ran without error
                result["passed"] = True

        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

        return result

    def _create_safe_namespace(self) -> dict:
        """Create a restricted namespace for code execution."""
        # Start with basic builtins
        safe_builtins = {
            "True": True,
            "False": False,
            "None": None,
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "chr": chr,
            "dict": dict,
            "divmod": divmod,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "format": format,
            "frozenset": frozenset,
            "hash": hash,
            "hex": hex,
            "int": int,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "iter": iter,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "next": next,
            "oct": oct,
            "ord": ord,
            "pow": pow,
            "print": print,  # Allow print for debugging
            "range": range,
            "repr": repr,
            "reversed": reversed,
            "round": round,
            "set": set,
            "slice": slice,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "type": type,
            "zip": zip,
        }

        return {"__builtins__": safe_builtins}
