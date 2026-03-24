import asyncio
import os
import json
from tempfile import NamedTemporaryFile

class InteractiveSession:
    def __init__(self, ws, session_id):
        self.ws = ws
        self.session_id = session_id
        self.proc = None
        self.timeout_task = None

    async def run_file(self, file_path: str):
        if not os.path.isfile(file_path):
            await self.ws.send_json({
                "type": "error",
                "sessionId": self.session_id,
                "value": f"File not found: {file_path}"
            })
            return

        self.proc = await asyncio.create_subprocess_exec(
            "python", "-u", "/projectFiles/executor_runner.py", file_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_task = asyncio.create_task(self._read_stream(self.proc.stdout, "output"))
        stderr_task = asyncio.create_task(self._read_stream(self.proc.stderr, "stderr"))
        self.timeout_task = asyncio.create_task(self._enforce_timeout(30))

        # 둘 다 완료될 때까지 기다렸다가 실행 종료 메시지 전송
        async def notify_done():
            await asyncio.gather(stdout_task, stderr_task)
            await self.proc.wait()
            await self.ws.send_json({
                "type": "done",
                "sessionId": self.session_id,
                "value": "▶  실행 종료"
            })
            print(f"[Python] 실행 종료: sessionId={self.session_id}")

        asyncio.create_task(notify_done())

    async def _read_stream(self, stream, msg_type: str):
        try:
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    break

                decoded = chunk.decode()
                if msg_type == "output" and decoded.startswith("__NEED_INPUT__"):
                    prompt = decoded[len("__NEED_INPUT__"):]
                    await self.ws.send_json({
                        "type": "input_required",
                        "sessionId": self.session_id,
                        "prompt": prompt
                    })
                else:
                    await self.ws.send_json({
                        "type": msg_type,
                        "sessionId": self.session_id,
                        "value": decoded
                    })
        except Exception as e:
            await self.ws.send_json({
                "type": "error",
                "sessionId": self.session_id,
                "message": str(e)
            })
        finally:
            if self.timeout_task:
                self.timeout_task.cancel()

    async def send_stdin(self, value: str):
        if self.proc and self.proc.stdin:
            self.proc.stdin.write((value + "\n").encode())
            await self.proc.stdin.drain()

    async def _enforce_timeout(self, seconds: int):
        try:
            await asyncio.sleep(seconds)
            if self.proc and self.proc.returncode is None:
                self.proc.kill()
                await self.ws.send_json({
                    "type": "error",
                    "sessionId": self.session_id,
                    "value": f"▶  실행 제한시간이 초과되었습니다."
                })
        except asyncio.CancelledError:
            pass

    async def cleanup(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()


    async def run_grading(self, file_path: str, testcases: list):
        if not os.path.isfile(file_path):
            await self.ws.send_json({
                "type": "error",
                "sessionId": self.session_id,
                "message": f"File not found: {file_path}"
            })
            return

        with NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            json.dump(testcases, tmp)
            testcase_path = tmp.name

        self.proc = await asyncio.create_subprocess_exec(
            "python", "-u", "/projectFiles/executor_runner.py", file_path, "--grading", testcase_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_data, stderr_data = await self.proc.communicate()

        output = stdout_data.decode()
        result_json = self._extract_result_json(output)

        await self.ws.send_json({
            "type": "grading_result",
            "sessionId": self.session_id,
            "results": result_json
        })

        # await self.ws.send_json({
        #     "type": "grading_result",
        #     "sessionId": self.session_id,
        #     "results": result_json
        # })

    def _extract_result_json(self, output):
        import re
        match = re.search(r"__RESULT__START__(.*?)__RESULT__END__", output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except:
                return [{"error": "JSON parse error"}]
        return [{"error": "No result found"}]

    async def run_with_bwrap(self, file_path: str, sandbox_root: str):
        if not os.path.isfile(file_path):
            await self.ws.send_json({
                "type": "error",
                "sessionId": self.session_id,
                "value": f"File not found: {file_path}"
            })
            return

        self.proc = await asyncio.create_subprocess_exec(
            "bwrap",
            "--setenv", "PYTHONUNBUFFERED", "1",
            "--setenv", "OPENBLAS_NUM_THREADS", "1",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc", "/etc",
            "--ro-bind", "/projectFiles", "/projectFiles",
            "--bind", sandbox_root, "/code",
            "--dev", "/dev",
           # "--proc", "/proc",
            "--unshare-all",
            "--share-net",
            "--ro-bind", "/dev/null", "/etc/resolv.conf",
            "--die-with-parent",
            "/usr/local/bin/python3", "/projectFiles/executor_runner.py",
            f"/code/{os.path.basename(file_path)}",
            # "/usr/local/bin/python3", "/code/" + os.path.basename(file_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await self.ws.send_json({
            "type": "running_start",
            "sessionId": self.session_id,
            "value": True
        })

        stdout_task = asyncio.create_task(self._read_stream(self.proc.stdout, "output"))
        stderr_task = asyncio.create_task(self._read_stream(self.proc.stderr, "stderr"))
        self.timeout_task = asyncio.create_task(self._enforce_timeout(30))

        async def notify_done():
            await asyncio.gather(stdout_task, stderr_task)
            await self.proc.wait()
            await self.ws.send_json({
                "type": "done",
                "sessionId": self.session_id,
                "value": "▶  실행 종료"
            })
            print(f"[Python] 실행 종료: sessionId={self.session_id}")

        asyncio.create_task(notify_done())


    async def run_grading_bwrap(self, file_path: str, sandbox_root: str, testcases: list, keywords: list = None):
        try:
            if not os.path.isfile(file_path):
                await self.ws.send_json({
                    "type": "error",
                    "sessionId": self.session_id,
                    "message": f"File not found: {file_path}"
                })
                return

            # 테스트케이스 임시 JSON 파일 저장
            with NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
                json.dump(testcases, tmp)
                testcase_path = tmp.name
            
            # 키워드 검사를 위한 임시 JSON 파일 저장
            keyword_path = None
            if keywords:
                with NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
                    json.dump(keywords, tmp)
                    keyword_path = tmp.name
                
        except Exception as e:
            return

        # bwrap 명령 구성
        bwrap_cmd = [
            "bwrap",
            "--setenv", "PYTHONUNBUFFERED", "1",
            "--setenv", "OPENBLAS_NUM_THREADS", "1",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/usr/local", "/usr/local",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc", "/etc",
            "--ro-bind", "/projectFiles", "/projectFiles",
            "--bind", "/tmp", "/tmp",
            "--bind", sandbox_root, "/code",
            "--dev", "/dev",
           # "--proc", "/proc",
            "--unshare-all",
            "--share-net",
            "--ro-bind", "/dev/null", "/etc/resolv.conf",
            "--die-with-parent",
            "/usr/local/bin/python3", "/projectFiles/executor_runner.py",
            f"/code/{os.path.basename(file_path)}", "--grading", testcase_path
        ]
        
        # 키워드 검사가 있으면 명령에 추가
        if keyword_path:
            bwrap_cmd.extend(["--keywords", keyword_path])
        
        self.proc = await asyncio.create_subprocess_exec(
            *bwrap_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await self.ws.send_json({
            "type": "running_start",
            "sessionId": self.session_id,
            "value": True
        })

        # grading 결과 수집을 위한 데이터 저장소
        self.grading_stdout_data = []
        self.grading_stderr_data = []

        # grading용 스트림 읽기 메서드
        async def read_grading_stream(stream, data_list):
            try:
                while True:
                    chunk = await stream.read(1024)
                    if not chunk:
                        break
                    data_list.append(chunk)
            except Exception as e:
                pass

        # 스트림 읽기 태스크 생성
        stdout_task = asyncio.create_task(read_grading_stream(self.proc.stdout, self.grading_stdout_data))
        stderr_task = asyncio.create_task(read_grading_stream(self.proc.stderr, self.grading_stderr_data))
        self.timeout_task = asyncio.create_task(self._enforce_timeout(30))

        # 프로세스 완료 및 결과 처리
        async def process_grading_result():
            try:
                # 스트림 읽기 완료 대기
                await asyncio.gather(stdout_task, stderr_task)
                await self.proc.wait()

                # 데이터 처리
                output = b''.join(self.grading_stdout_data).decode()
                error = b''.join(self.grading_stderr_data).decode()
                
                result_json = self._extract_result_json(output)

                # 결과 형식 확인 및 분리
                if isinstance(result_json, dict) and "testcase_results" in result_json:
                    # 새로운 형식: testcase_results와 keyword_results가 분리됨
                    testcase_results = result_json.get("testcase_results", [])
                    keyword_results = result_json.get("keyword_results", {})
                else:
                    # 기존 형식: 하위 호환성 유지
                    testcase_results = result_json
                    keyword_results = {}
                await self.ws.send_json({
                    "type": "grading_result",
                    "sessionId": self.session_id,
                    "results": testcase_results,
                    "keyword_results": keyword_results
                })

                await self.ws.send_json({
                    "type": "done",
                    "sessionId": self.session_id,
                    "value": "▶  실행 종료"
                })
                
            except Exception as e:
                pass
            finally:
                # 타임아웃 태스크 정리
                if self.timeout_task:
                    self.timeout_task.cancel()

        # 결과 처리 태스크 생성
        asyncio.create_task(process_grading_result())

    async def terminate_process(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
