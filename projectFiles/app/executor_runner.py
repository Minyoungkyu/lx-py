import sys
import traceback
import importlib.util
import os
import json
import io
import contextlib
import resource
import ast

SANDBOX_UTILS_PATH = "/projectFiles/sandbox_utils.py"
spec = importlib.util.spec_from_file_location("sandbox_utils", SANDBOX_UTILS_PATH)
sandbox_utils = importlib.util.module_from_spec(spec)
sys.modules["sandbox_utils"] = sandbox_utils
spec.loader.exec_module(sandbox_utils)

def apply_resource_limits():
    pass
    # # cpu 제한시간
    # cpu_time_limit = 1  # 3초

    # # 메모리 제한
    memory_limit = 256 * 1024 * 1024

    # # 파일 제한 (혹시몰라 추가함)
    file_limit = 64

    # resource.setrlimit(resource.RLIMIT_CPU, (cpu_time_limit, cpu_time_limit))
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    resource.setrlimit(resource.RLIMIT_NOFILE, (file_limit, file_limit))

def check_keywords_in_code(code_path: str, keywords: list) -> bool:
    """AST를 사용해서 코드에서 키워드 사용 여부를 검사"""
    try:
        with open(code_path, 'r', encoding='utf-8') as f:
            code_content = f.read()
        
        tree = ast.parse(code_content)
        
        class KeywordChecker(ast.NodeVisitor):
            def __init__(self, target_keywords):
                self.found_keywords = set()
                self.target_keywords = set()
                for keyword in target_keywords:
                    # 함수명에서 괄호 제거 (range() -> range)
                    clean_keyword = keyword.replace("()", "").replace("(", "").replace(")", "")
                    self.target_keywords.add(clean_keyword)
            
            def visit_For(self, node):
                if "for" in self.target_keywords:
                    self.found_keywords.add("for")
                self.generic_visit(node)
            
            def visit_While(self, node):
                if "while" in self.target_keywords:
                    self.found_keywords.add("while")
                self.generic_visit(node)
            
            def visit_If(self, node):
                if "if" in self.target_keywords:
                    self.found_keywords.add("if")
                self.generic_visit(node)
            
            def visit_Try(self, node):
                if "try" in self.target_keywords:
                    self.found_keywords.add("try")
                self.generic_visit(node)
            
            def visit_FunctionDef(self, node):
                if "def" in self.target_keywords:
                    self.found_keywords.add("def")
                self.generic_visit(node)
            
            def visit_Return(self, node):
                if "return" in self.target_keywords:
                    self.found_keywords.add("return")
                self.generic_visit(node)
            
            def visit_Call(self, node):
                # 함수 호출 검사 (print, range, input 등)
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in self.target_keywords:
                        self.found_keywords.add(func_name)
                self.generic_visit(node)
            
            def visit_ListComp(self, node):
                if "list_comprehension" in self.target_keywords:
                    self.found_keywords.add("list_comprehension")
                self.generic_visit(node)
            
            def visit_Compare(self, node):
                for op in node.ops:
                    if isinstance(op, ast.In) and "in" in self.target_keywords:
                        self.found_keywords.add("in")
                    elif isinstance(op, ast.Is) and "is" in self.target_keywords:
                        self.found_keywords.add("is")
                self.generic_visit(node)
        
        checker = KeywordChecker(keywords)
        checker.visit(tree)
        
        # 모든 키워드가 발견되었는지 확인
        return checker.target_keywords.issubset(checker.found_keywords)
    
    except Exception as e:
        return False

def run_user_code(path: str, grading: bool = False, inputs: list = None):
    sandbox_utils.override_input(grading_mode=grading)
    if grading and inputs:
        sandbox_utils.set_grading_inputs(inputs)

    try:
        spec = importlib.util.spec_from_file_location("user_code", path)
        user_code = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_code)

    except SyntaxError as e:
        if e.filename == path:
            print(f'  File "{e.filename}", line {e.lineno}', file=sys.stderr)
            if e.text:
                print(f'    {e.text.rstrip()}', file=sys.stderr)
                if e.offset:
                    print("    " + " " * (e.offset - 1) + "^", file=sys.stderr)
            print(f"{type(e).__name__}: {e.msg}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        tb = traceback.TracebackException(type(e), e, e.__traceback__)
        filtered = [frame for frame in tb.stack if frame.filename == path]

        if filtered:
            print("Traceback (most recent call last):", file=sys.stderr)
            for frame in filtered:
                print(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}', file=sys.stderr)
                if frame.line:
                    print(f"    {frame.line.strip()}", file=sys.stderr)
            print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    apply_resource_limits()
    if len(sys.argv) < 2:
        print("Usage: python executor_runner.py <path_to_user_code> [--grading path_to_testcases.json] [--keywords path_to_keywords.json]")
        sys.exit(1)

    user_code_path = sys.argv[1]

    if len(sys.argv) >= 4 and sys.argv[2] == "--grading":
        with open(sys.argv[3], "r") as f:
            testcases = json.load(f)

        # 키워드 검사 파일 경로 확인
        keywords = []
        all_keywords_found = False
        
        if len(sys.argv) >= 6 and sys.argv[4] == "--keywords":
            try:
                with open(sys.argv[5], "r") as f:
                    keywords = json.load(f)
                # 키워드 검사 실행
                all_keywords_found = check_keywords_in_code(user_code_path, keywords)
            except Exception as e:
                all_keywords_found = False

        results = []
        for case in testcases:
            output_buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(output_buffer):
                    run_user_code(user_code_path, grading=True, inputs=case["input"].splitlines())
                actual = output_buffer.getvalue().strip()
                results.append({
                    "input": case["input"],
                    "expected": case["output"].strip(),
                    "actual": actual,
                    "passed": actual == case["output"].strip()
                })
            except Exception as e:
                results.append({
                    "input": case["input"],
                    "expected": case["output"],
                    "actual": f"Exception: {str(e)}",
                    "passed": False
                })

        # 결과에 키워드 검사 결과도 포함
        final_result = {
            "testcase_results": results,
            "keyword_results": all_keywords_found
        }

        print("__RESULT__START__")
        print(json.dumps(final_result, ensure_ascii=False))
        print("__RESULT__END__")
    else:
        run_user_code(user_code_path)
