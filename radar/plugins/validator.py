"""AST-based code validation for plugins."""

import ast


class CodeValidator:
    """Validates plugin code using AST analysis."""

    # Forbidden imports that could be dangerous
    FORBIDDEN_IMPORTS = {
        # System / process
        "os", "subprocess", "sys", "shutil",
        "multiprocessing", "threading", "ctypes", "signal",
        # Serialization
        "pickle", "marshal",
        # Network
        "socket", "urllib", "http", "requests", "httpx", "aiohttp",
        # Dynamic imports / code execution
        "importlib", "runpy", "code", "codeop",
        # Filesystem
        "tempfile", "pathlib", "glob", "fnmatch",
    }

    # Forbidden function calls
    FORBIDDEN_CALLS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
    }

    # Forbidden attribute access patterns
    FORBIDDEN_ATTRIBUTES = {
        "__code__",
        "__globals__",
        "__builtins__",
        "__subclasses__",
        "__bases__",
        "__mro__",
    }

    def __init__(self, allowed_imports: set[str] | None = None):
        """Initialize validator with optional allowed imports."""
        self.allowed_imports = allowed_imports or set()

    def validate(self, code: str) -> tuple[bool, list[str]]:
        """Validate code and return (is_valid, list of issues)."""
        issues = []

        # Try to parse the code
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"Syntax error: {e}"]

        # Check for forbidden patterns
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module in self.FORBIDDEN_IMPORTS and module not in self.allowed_imports:
                        issues.append(f"Forbidden import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if module in self.FORBIDDEN_IMPORTS and module not in self.allowed_imports:
                        issues.append(f"Forbidden import from: {node.module}")

            # Check function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_CALLS:
                        issues.append(f"Forbidden call: {node.func.id}()")
                elif isinstance(node.func, ast.Attribute):
                    # Check for things like obj.__import__()
                    if node.func.attr in self.FORBIDDEN_CALLS:
                        issues.append(f"Forbidden call: .{node.func.attr}()")

            # Check attribute access
            elif isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRIBUTES:
                    issues.append(f"Forbidden attribute access: {node.attr}")

        # Check for function definition
        has_function = any(isinstance(node, ast.FunctionDef) for node in ast.walk(tree))
        if not has_function:
            issues.append("Code must define at least one function")

        return len(issues) == 0, issues
